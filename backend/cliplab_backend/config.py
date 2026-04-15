from __future__ import annotations

import os
import shutil
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLIPLAB_", extra="ignore")

    app_name: str = "ClipLab Backend"
    host: str = "127.0.0.1"
    port: int = 8765
    backend_url: str = "http://127.0.0.1:8765"
    app_data: str = ""
    ffmpeg_path: str = "ffmpeg"
    default_output_subdir: str = "ClipLab"
    sttn_auto_model_url: str = ""
    lama_model_url: str = ""
    pid_file: str = ""

    @property
    def data_root(self) -> Path:
        if self.app_data:
            root = Path(self.app_data)
        else:
            root = Path(os.environ.get("CLIPLAB_APP_DATA", Path.cwd() / "app-data"))
        root.mkdir(parents=True, exist_ok=True)
        return root

    @property
    def database_path(self) -> Path:
        return self.data_root / "cliplab.sqlite3"

    @property
    def logs_dir(self) -> Path:
        path = self.data_root / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def models_dir(self) -> Path:
        path = self.data_root / "models"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def default_output_dir(self) -> Path:
        path = self.data_root / self.default_output_subdir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def pid_path(self) -> Path | None:
        if not self.pid_file:
            return None
        path = Path(self.pid_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def resolve_ffmpeg_path(self) -> str:
        if self.ffmpeg_path and self.ffmpeg_path != "ffmpeg":
            return self.ffmpeg_path

        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass

        system_ffmpeg = shutil.which(self.ffmpeg_path or "ffmpeg")
        return system_ffmpeg or self.ffmpeg_path or "ffmpeg"


settings = Settings()
