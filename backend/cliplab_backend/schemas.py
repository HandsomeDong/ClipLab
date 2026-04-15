from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


TaskType = Literal["download", "remove_watermark"]
TaskStatus = Literal["queued", "running", "succeeded", "failed", "canceled", "interrupted"]
AlgorithmId = Literal["sttn_auto", "lama", "propainter"]


class WatermarkRegion(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class MediaSource(BaseModel):
    platform: str
    shareUrl: str
    resolvedId: str
    title: str
    author: str
    duration: float
    coverUrl: str | None = None
    downloadUrl: str | None = None


class TaskRecord(BaseModel):
    id: str
    type: TaskType
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    input: str
    outputPath: str | None = None
    errorCode: str | None = None
    errorMessage: str | None = None
    createdAt: datetime
    updatedAt: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class LogRecord(BaseModel):
    id: str
    level: Literal["info", "warning", "error"]
    source: Literal["desktop", "api", "task", "remote_web"]
    message: str
    createdAt: datetime
    taskId: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ModelPackage(BaseModel):
    id: str
    version: str
    size: int
    installed: bool
    downloadStatus: Literal["idle", "downloading", "failed", "ready"]
    checksum: str | None = None
    description: str


class ResolveLinkRequest(BaseModel):
    shareUrl: str
    douyinCookie: str = ""
    kuaishouCookie: str = ""


class ResolveLinkResponse(BaseModel):
    """解析链接响应"""
    type: Literal["single", "batch"]  # 单视频还是批量（用户主页）
    media: MediaSource | None = None  # 单视频时使用
    mediaList: list[MediaSource] = Field(default_factory=list)  # 批量时使用
    userId: str | None = None  # 用户 ID（批量时）
    userName: str | None = None  # 用户名（批量时）
    fanCount: int = 0  # 粉丝数（批量时）
    photoCount: int = 0  # 作品数（批量时）


class CreateDownloadTaskRequest(BaseModel):
    shareUrl: str
    outputDirectory: str
    douyinCookie: str = ""
    kuaishouCookie: str = ""


class CreateBatchDownloadRequest(BaseModel):
    shareUrls: list[str]
    outputDirectory: str
    douyinCookie: str = ""
    kuaishouCookie: str = ""


class BatchTaskError(BaseModel):
    input: str
    error: str


class BatchDownloadResponse(BaseModel):
    tasks: list[TaskRecord]
    failed: list[BatchTaskError] = Field(default_factory=list)


class CreateWatermarkTaskRequest(BaseModel):
    inputPath: str
    outputDirectory: str = ""
    region: WatermarkRegion
    algorithm: AlgorithmId = "sttn_auto"


class ClearHistoryResponse(BaseModel):
    clearedTasks: int
    clearedLogs: int


class DownloadModelRequest(BaseModel):
    modelId: str


class EventMessage(BaseModel):
    type: Literal["heartbeat", "task_update", "log_update"]
    task: TaskRecord | None = None
    log: LogRecord | None = None


class ServerInfo(BaseModel):
    appName: str
    localApiUrl: str
    remoteSubmitUrls: list[str]
    remoteWebUrls: list[str]


class ResolverAdapter:
    def can_handle(self, url: str) -> bool: ...

    def resolve(self, url: str) -> MediaSource: ...


class DownloadAdapter:
    def download(self, media: MediaSource, output_dir: str, progress_callback) -> str: ...
