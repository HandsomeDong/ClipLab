from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from cliplab_backend.config import settings
from cliplab_backend.schemas import (
    BatchDownloadResponse,
    BatchTaskError,
    ClearHistoryResponse,
    CreateBatchDownloadRequest,
    CreateDownloadTaskRequest,
    CreateWatermarkTaskRequest,
    DownloadModelRequest,
    LogRecord,
    ResolveLinkRequest,
    ResolveLinkResponse,
    ServerInfo,
    TaskRecord,
)
from cliplab_backend.services.events import EventBus
from cliplab_backend.services.model_manager import ModelManager
from cliplab_backend.services.resolver import ResolverService
from cliplab_backend.services.server_info import build_server_info
from cliplab_backend.services.task_manager import TaskManager
from cliplab_backend.services.watermark import WatermarkService
from cliplab_backend.storage.db import Database, LogRepository, TaskRepository


event_bus = EventBus()
database = Database(settings.database_path)
repository = TaskRepository(database)
log_repository = LogRepository(database)
resolver = ResolverService()
model_manager = ModelManager()
watermark_service = WatermarkService()
task_manager = TaskManager(repository, log_repository, event_bus, resolver, watermark_service, model_manager)


def _write_pid_file() -> None:
    pid_path = settings.pid_path
    if pid_path is None:
        return
    pid_path.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid_file() -> None:
    pid_path = settings.pid_path
    if pid_path is None:
        return
    with suppress(FileNotFoundError):
        pid_path.unlink()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _write_pid_file()
    heartbeat: asyncio.Task[None] | None = None
    try:
        await task_manager.start()
        heartbeat = asyncio.create_task(_heartbeat_loop())
        yield
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        await task_manager.stop()
        _remove_pid_file()


async def _heartbeat_loop() -> None:
    while True:
        await event_bus.publish_heartbeat()
        await asyncio.sleep(10)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/server-info")
async def server_info() -> ServerInfo:
    return build_server_info()


@app.post("/api/resolve-link")
async def resolve_link(payload: ResolveLinkRequest):
    try:
        media = resolver.resolve(payload.shareUrl, payload.douyinCookie, payload.kuaishouCookie)
        return ResolveLinkResponse(type="single", media=media)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/tasks/download")
async def create_download_task(payload: CreateDownloadTaskRequest, request: Request) -> TaskRecord:
    try:
        normalized = payload.model_copy(
            update={
                "outputDirectory": payload.outputDirectory.strip() or str(settings.default_output_dir),
            }
        )
        task = await task_manager.create_download_task(normalized)
        source = request.headers.get("x-cliplab-source", "api")
        await task_manager.log_external(
            "info",
            "remote_web" if source == "remote_web" else "api",
            f"收到下载任务：{payload.shareUrl}",
            {"outputDirectory": normalized.outputDirectory},
        )
        return task
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/tasks/download/batch")
async def create_batch_download_tasks(payload: CreateBatchDownloadRequest, request: Request) -> BatchDownloadResponse:
    try:
        output_dir = payload.outputDirectory.strip() or str(settings.default_output_dir)
        tasks: list[TaskRecord] = []
        failed: list[BatchTaskError] = []

        for share_url in payload.shareUrls:
            normalized = share_url.strip()
            if not normalized:
                continue
            try:
                task = await task_manager.create_download_task(
                    CreateDownloadTaskRequest(
                        shareUrl=normalized,
                        outputDirectory=output_dir,
                        douyinCookie=payload.douyinCookie,
                        kuaishouCookie=payload.kuaishouCookie,
                    )
                )
                tasks.append(task)
            except Exception as error:  # pragma: no cover - defensive around task creation
                failed.append(BatchTaskError(input=normalized, error=str(error)))

        if not tasks and failed:
            raise HTTPException(status_code=400, detail=failed[0].error)

        source = request.headers.get("x-cliplab-source", "api")
        await task_manager.log_external(
            "info",
            "remote_web" if source == "remote_web" else "api",
            f"收到批量下载任务：成功 {len(tasks)} 个，失败 {len(failed)} 个",
            {"outputDirectory": output_dir, "count": len(tasks), "failed": len(failed)},
        )
        return BatchDownloadResponse(tasks=tasks, failed=failed)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/tasks/remove-watermark")
async def create_watermark_task(payload: CreateWatermarkTaskRequest, request: Request) -> TaskRecord:
    try:
        normalized = payload.model_copy(
            update={
                "outputDirectory": payload.outputDirectory.strip(),
            }
        )
        task = await task_manager.create_watermark_task(normalized)
        source = request.headers.get("x-cliplab-source", "api")
        await task_manager.log_external(
            "info",
            "remote_web" if source == "remote_web" else "api",
            f"收到去水印任务：{payload.inputPath}",
            {"algorithm": normalized.algorithm},
        )
        return task
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/tasks")
async def list_tasks() -> list[TaskRecord]:
    return repository.list()


@app.get("/api/logs")
async def list_logs() -> list[LogRecord]:
    return log_repository.list()


@app.post("/api/history/clear")
async def clear_history() -> ClearHistoryResponse:
    cleared_tasks = repository.clear_task_history()
    cleared_logs = log_repository.clear_logs()
    return ClearHistoryResponse(clearedTasks=cleared_tasks, clearedLogs=cleared_logs)


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> TaskRecord:
    task = repository.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/models")
async def list_models():
    return model_manager.list_packages()


@app.post("/api/models/download")
async def download_model(payload: DownloadModelRequest):
    try:
        return await model_manager.download(payload.modelId)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/events")
async def events():
    subscriber = event_bus.subscribe()

    async def iterator():
        try:
            while True:
                message = await subscriber.get()
                yield f"data: {message}\n\n"
        finally:
            event_bus.unsubscribe(subscriber)

    return StreamingResponse(iterator(), media_type="text/event-stream")


@app.get("/remote", response_class=HTMLResponse)
async def remote_page() -> HTMLResponse:
    return HTMLResponse(
        """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>ClipLab 内网任务提交</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; margin: 0; background: #f5f7fb; color: #15233b; }
      .wrap { max-width: 720px; margin: 0 auto; padding: 24px 16px 40px; display: grid; gap: 16px; }
      .card { background: white; border-radius: 18px; padding: 18px; box-shadow: 0 12px 30px rgba(17,34,68,.08); }
      h1,h2 { margin: 0 0 10px; }
      p { margin: 0; color: #5f708b; }
      textarea,input,button { font: inherit; }
      textarea,input { width: 100%; box-sizing: border-box; margin-top: 12px; border-radius: 14px; border: 1px solid #d9e0ec; padding: 12px; }
      button { border: 0; border-radius: 14px; padding: 12px 14px; background: #0a7f6f; color: white; margin-top: 12px; width: 100%; }
      .list { display: grid; gap: 10px; margin-top: 14px; }
      .item { padding: 12px; border-radius: 14px; background: #f7f9fc; }
      .meta { font-size: 13px; color: #6c7d96; margin-top: 6px; }
      code { word-break: break-all; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <section class="card">
        <h1>ClipLab 内网下载提交</h1>
        <p>在同一内网下，用手机提交短视频下载任务，桌面端会实时同步显示。</p>
        <input id="outputDirectory" placeholder="输出目录，可留空让桌面端使用默认目录" />
        <textarea id="shareUrl" rows="5" placeholder="粘贴抖音或快手分享文案 / 链接"></textarea>
        <button id="submitButton">提交下载任务</button>
        <p id="notice" class="meta"></p>
      </section>
      <section class="card">
        <h2>最近任务</h2>
        <div id="taskList" class="list"></div>
      </section>
      <section class="card">
        <h2>最近日志</h2>
        <div id="logList" class="list"></div>
      </section>
    </div>
    <script>
      const notice = document.getElementById("notice");
      const taskList = document.getElementById("taskList");
      const logList = document.getElementById("logList");
      const shareUrlInput = document.getElementById("shareUrl");
      const outputDirectoryInput = document.getElementById("outputDirectory");

      async function fetchJson(url, init) {
        const response = await fetch(url, {
          headers: { "Content-Type": "application/json" },
          ...init
        });
        const text = await response.text();
        if (!response.ok) {
          try {
            const parsed = JSON.parse(text);
            throw new Error(parsed.detail || text);
          } catch {
            throw new Error(text || "请求失败");
          }
        }
        return text ? JSON.parse(text) : null;
      }

      function renderTasks(tasks) {
        taskList.innerHTML = tasks.slice(0, 8).map((task) => `
          <div class="item">
            <strong>${task.type === "download" ? "下载任务" : "去水印任务"}</strong>
            <div class="meta">${task.input}</div>
            <div class="meta">状态：${task.status} · 进度：${task.progress}%</div>
          </div>
        `).join("") || "<div class='item'>还没有任务</div>";
      }

      function renderLogs(logs) {
        logList.innerHTML = logs.slice(0, 10).map((log) => `
          <div class="item">
            <strong>${log.source}</strong>
            <div class="meta">${log.message}</div>
            <div class="meta">${new Date(log.createdAt).toLocaleString()}</div>
          </div>
        `).join("") || "<div class='item'>还没有日志</div>";
      }

      async function refresh() {
        const [tasks, logs] = await Promise.all([
          fetchJson("/api/tasks"),
          fetchJson("/api/logs")
        ]);
        renderTasks(tasks);
        renderLogs(logs);
      }

      document.getElementById("submitButton").addEventListener("click", async () => {
        const shareUrl = shareUrlInput.value.trim();
        const outputDirectory = outputDirectoryInput.value.trim();
        if (!shareUrl) {
          notice.textContent = "请先粘贴分享链接。";
          return;
        }
        try {
          await fetchJson("/api/tasks/download", {
            method: "POST",
            headers: { "Content-Type": "application/json", "x-cliplab-source": "remote_web" },
            body: JSON.stringify({ shareUrl, outputDirectory })
          });
          notice.textContent = "任务已提交，桌面端会同步显示。";
          shareUrlInput.value = "";
          await refresh();
        } catch (error) {
          notice.textContent = error.message;
        }
      });

      refresh();
      const source = new EventSource("/api/events");
      source.onmessage = () => refresh();
    </script>
  </body>
</html>
        """
    )
