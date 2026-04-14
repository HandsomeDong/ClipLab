from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import timezone
from uuid import uuid4

from cliplab_backend.schemas import (
    CreateDownloadTaskRequest,
    CreateWatermarkTaskRequest,
    LogRecord,
    MediaSource,
    TaskRecord,
    TaskType,
)
from cliplab_backend.services.events import EventBus
from cliplab_backend.services.model_manager import ModelManager
from cliplab_backend.services.resolver import ResolverService
from cliplab_backend.services.watermark import WatermarkService
from cliplab_backend.storage.db import LogRepository, TaskRepository, utcnow


@dataclass
class QueuedTask:
    task_id: str
    task_type: TaskType
    payload: CreateDownloadTaskRequest | CreateWatermarkTaskRequest


class TaskManager:
    def __init__(
        self,
        repository: TaskRepository,
        log_repository: LogRepository,
        event_bus: EventBus,
        resolver: ResolverService,
        watermark_service: WatermarkService,
        model_manager: ModelManager,
    ) -> None:
        self.repository = repository
        self.log_repository = log_repository
        self.event_bus = event_bus
        self.resolver = resolver
        self.watermark_service = watermark_service
        self.model_manager = model_manager
        self.queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self.worker_task: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self.repository.interrupt_in_flight_tasks()
        self.loop = asyncio.get_running_loop()
        self.worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self.worker_task:
            self.worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker_task

    async def create_download_task(self, payload: CreateDownloadTaskRequest) -> TaskRecord:
        task = self._new_task(
            "download",
            payload.shareUrl,
            {
                "outputDirectory": payload.outputDirectory,
                "hasDouyinCookie": bool(payload.douyinCookie),
                "hasKuaishouCookie": bool(payload.kuaishouCookie),
            },
        )
        await self._enqueue(task, payload)
        return task

    async def create_watermark_task(self, payload: CreateWatermarkTaskRequest) -> TaskRecord:
        task = self._new_task(
            "remove_watermark",
            payload.inputPath,
            {
                "outputDirectory": payload.outputDirectory,
                "algorithm": payload.algorithm,
                "region": payload.region.model_dump(),
            },
        )
        await self._enqueue(task, payload)
        return task

    async def _enqueue(self, task: TaskRecord, payload: CreateDownloadTaskRequest | CreateWatermarkTaskRequest) -> None:
        self.repository.save(task)
        await self.event_bus.publish_task(task)
        await self._log("info", "task", f"任务已入队：{task.input}", task.id, task.metadata)
        await self.queue.put(QueuedTask(task_id=task.id, task_type=task.type, payload=payload))

    async def _worker_loop(self) -> None:
        while True:
            item = await self.queue.get()
            task = self.repository.get(item.task_id)
            if not task:
                self.queue.task_done()
                continue
            await self._update_task(task, status="running", progress=2)
            await self._log("info", "task", f"任务开始执行：{task.input}", task.id, task.metadata)
            try:
                if item.task_type == "download":
                    await self._log("info", "task", f"开始解析链接：{item.payload.shareUrl}", task.id, {})
                    assert isinstance(item.payload, CreateDownloadTaskRequest)
                    media = self.resolver.resolve(
                        item.payload.shareUrl,
                        item.payload.douyinCookie,
                        item.payload.kuaishouCookie,
                    )
                    await self._log("info", "task", f"解析成功：{media.title}（{media.platform}）", task.id, {})
                    self._progress(task.id, 10)
                    await self._log("info", "task", "开始下载视频...", task.id, {})
                    result_path = await asyncio.to_thread(
                        self._run_download,
                        item.task_id,
                        media,
                        item.payload.outputDirectory,
                        item.payload.douyinCookie,
                        item.payload.kuaishouCookie,
                    )
                    await self._log("info", "task", f"下载完成：{result_path}", task.id, {})
                else:
                    await self._log("info", "task", "开始去水印处理...", task.id, {})
                    self._progress(task.id, 10)
                    result_path = await asyncio.to_thread(
                        self._run_watermark,
                        item.task_id,
                        item.payload,
                    )
                    await self._log("info", "task", f"去水印完成：{result_path}", task.id, {})
                await self._update_task(task, status="succeeded", progress=100, outputPath=result_path)
                await self._log("info", "task", f"任务执行成功：{result_path}", task.id, {"outputPath": result_path})
            except Exception as error:
                await self._log("error", "task", f"任务执行失败：{type(error).__name__}: {error}", task.id, {"error": str(error)})
                await self._update_task(
                    task,
                    status="failed",
                    progress=100,
                    errorCode="task_failed",
                    errorMessage=str(error),
                )
            finally:
                self.queue.task_done()

    def _run_download(
        self,
        task_id: str,
        media: MediaSource,
        output_dir: str,
        douyin_cookie: str = "",
        kuaishou_cookie: str = "",
    ) -> str:
        self._progress(task_id, 10)
        output_path = self.resolver.download(
            media,
            output_dir,
            lambda value: self._progress(task_id, value),
            douyin_cookie,
            kuaishou_cookie,
        )
        return output_path

    def _run_watermark(self, task_id: str, payload: CreateDownloadTaskRequest | CreateWatermarkTaskRequest) -> str:
        assert isinstance(payload, CreateWatermarkTaskRequest)
        self._progress(task_id, 10)
        return self.watermark_service.process(
            input_path=payload.inputPath,
            output_directory=payload.outputDirectory,
            region=payload.region,
            algorithm=payload.algorithm,
            progress_callback=lambda value: self._progress(task_id, value),
        )

    def _progress(self, task_id: str, value: int) -> None:
        task = self.repository.get(task_id)
        if not task or self.loop is None:
            return
        task.progress = max(task.progress, min(99, value))
        task.updatedAt = utcnow()
        self.repository.save(task)
        asyncio.run_coroutine_threadsafe(self.event_bus.publish_task(task), self.loop)

    async def _update_task(self, task: TaskRecord, **changes) -> TaskRecord:
        updated = task.model_copy(update={**changes, "updatedAt": utcnow()})
        self.repository.save(updated)
        await self.event_bus.publish_task(updated)
        return updated

    async def log_external(self, level: str, source: str, message: str, context: dict | None = None) -> LogRecord:
        return await self._log(level, source, message, None, context or {})

    async def _log(
        self,
        level: str,
        source: str,
        message: str,
        task_id: str | None,
        context: dict,
    ) -> LogRecord:
        log = self.log_repository.create(
            level=level,
            source=source,
            message=message,
            task_id=task_id,
            context=context,
        )
        await self.event_bus.publish_log(log)
        return log

    @staticmethod
    def _new_task(task_type: TaskType, task_input: str, metadata: dict) -> TaskRecord:
        now = utcnow().astimezone(timezone.utc)
        return TaskRecord(
            id=str(uuid4()),
            type=task_type,
            status="queued",
            progress=0,
            input=task_input,
            outputPath=None,
            errorCode=None,
            errorMessage=None,
            createdAt=now,
            updatedAt=now,
            metadata=metadata,
        )
