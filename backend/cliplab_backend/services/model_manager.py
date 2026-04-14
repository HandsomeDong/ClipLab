from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from cliplab_backend.config import settings
from cliplab_backend.schemas import ModelPackage


@dataclass(frozen=True)
class PackageConfig:
    model_id: str
    version: str
    size: int
    description: str
    filename: str
    source_url: str


class ModelManager:
    STTN_RUNTIME_FILENAME = "sttn_auto.pth"
    STTN_BUILTIN_MARKER = "sttn_auto.builtin"

    def __init__(self) -> None:
        self.download_status: dict[str, str] = {
            "sttn_auto": "ready",
            "lama": "idle",
        }
        self.registry: dict[str, PackageConfig] = {
            "sttn_auto": PackageConfig(
                model_id="sttn_auto",
                version="mvp-sttn-ready",
                size=95 * 1024 * 1024,
                description="已接入 STTN 推理入口；装好 torch 并下载权重后会启用真实模型，否则自动回退到内置时序修复。",
                filename=self.STTN_RUNTIME_FILENAME,
                source_url=settings.sttn_auto_model_url,
            ),
            "lama": PackageConfig(
                model_id="lama",
                version="1.0.0",
                size=128 * 1024 * 1024,
                description="LaMa 兼容兜底模型，适合单帧或轻量视频修复。",
                filename="big-lama.pt",
                source_url=settings.lama_model_url,
            ),
        }
        self._mark_builtin_installed()

    def _mark_builtin_installed(self) -> None:
        marker = settings.models_dir / self.STTN_BUILTIN_MARKER
        if not marker.exists():
            marker.write_text("builtin", encoding="utf-8")

    def _path_for(self, config: PackageConfig) -> Path:
        return settings.models_dir / config.filename

    def get_runtime_path(self, model_id: str) -> Path:
        if model_id not in self.registry:
            raise ValueError(f"Unknown model package: {model_id}")
        return self._path_for(self.registry[model_id])

    def has_builtin_fallback(self, model_id: str) -> bool:
        return model_id == "sttn_auto" and (settings.models_dir / self.STTN_BUILTIN_MARKER).exists()

    def list_packages(self) -> list[ModelPackage]:
        packages: list[ModelPackage] = []
        for item in self.registry.values():
            installed = self._path_for(item).exists() or self.has_builtin_fallback(item.model_id)
            packages.append(
                ModelPackage(
                    id=item.model_id,
                    version=item.version,
                    size=item.size,
                    installed=installed,
                    downloadStatus="ready" if installed else self.download_status.get(item.model_id, "idle"),  # type: ignore[arg-type]
                    checksum=None,
                    description=item.description,
                )
            )
        return packages

    async def download(self, model_id: str) -> ModelPackage:
        if model_id not in self.registry:
            raise ValueError(f"Unknown model package: {model_id}")
        package = self.registry[model_id]
        destination = self._path_for(package)
        if destination.exists():
            self.download_status[model_id] = "ready"
            return self.list_by_id(model_id)
        if not package.source_url:
            raise ValueError(f"Model URL not configured for {model_id}. Set CLIPLAB_{model_id.upper()}_MODEL_URL first.")

        self.download_status[model_id] = "downloading"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
                async with client.stream("GET", package.source_url) as response:
                    response.raise_for_status()
                    with destination.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            output.write(chunk)
            self.download_status[model_id] = "ready"
        except Exception:
            self.download_status[model_id] = "failed"
            if destination.exists():
                destination.unlink(missing_ok=True)
            raise
        return self.list_by_id(model_id)

    def list_by_id(self, model_id: str) -> ModelPackage:
        for package in self.list_packages():
            if package.id == model_id:
                return package
        raise ValueError(f"Unknown model package: {model_id}")
