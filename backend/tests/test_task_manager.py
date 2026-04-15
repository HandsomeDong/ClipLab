import asyncio

from cliplab_backend.schemas import CreateWatermarkTaskRequest, WatermarkRegion
from cliplab_backend.services.events import EventBus
from cliplab_backend.services.task_manager import TaskManager
from cliplab_backend.services.watermark import WatermarkProcessResult
from cliplab_backend.storage.db import Database, LogRepository, TaskRepository


class StubResolverService:
    pass


class StubModelManager:
    pass


class StubWatermarkService:
    def process(self, input_path, output_directory, region, algorithm, progress_callback):
        progress_callback(90)
        return WatermarkProcessResult(
            output_path=f"{output_directory}/demo_no_watermark.mp4",
            audio_merged=False,
            warning_message="音轨合并失败，已输出静音视频：demo warning",
        )


def test_task_manager_persists_warning_metadata_for_watermark_tasks(tmp_path):
    async def scenario():
        database = Database(tmp_path / "cliplab.sqlite3")
        repository = TaskRepository(database)
        log_repository = LogRepository(database)
        manager = TaskManager(
            repository=repository,
            log_repository=log_repository,
            event_bus=EventBus(),
            resolver=StubResolverService(),
            watermark_service=StubWatermarkService(),
            model_manager=StubModelManager(),
        )
        await manager.start()
        try:
            task = await manager.create_watermark_task(
                CreateWatermarkTaskRequest(
                    inputPath="/tmp/input.mp4",
                    outputDirectory="/tmp/output",
                    region=WatermarkRegion(x=0.1, y=0.2, width=0.3, height=0.2),
                    algorithm="sttn_auto",
                )
            )
            await asyncio.wait_for(manager.queue.join(), timeout=2)
            return repository.get(task.id), log_repository.list(limit=20)
        finally:
            await manager.stop()

    task, logs = asyncio.run(scenario())

    assert task is not None
    assert task.status == "succeeded"
    assert task.outputPath == "/tmp/output/demo_no_watermark.mp4"
    assert task.metadata["audioMerged"] is False
    assert task.metadata["warnings"] == ["音轨合并失败，已输出静音视频：demo warning"]
    assert any(log.level == "warning" and "音轨合并失败" in log.message for log in logs)
