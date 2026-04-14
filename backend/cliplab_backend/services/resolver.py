from __future__ import annotations

from typing import Callable

from cliplab_backend.schemas import MediaSource
from cliplab_backend.services.douyin import DouyinDownloader, DouyinResolver
from cliplab_backend.services.download_utils import build_output_path, extract_urls
from cliplab_backend.services.kuaishou import KuaishouDownloader, KuaishouResolver


def detect_platform(url: str) -> str:
    normalized = url.lower()
    if "douyin.com" in normalized or "iesdouyin.com" in normalized:
        return "douyin"
    if "kuaishou.com" in normalized or "chenzhongtech.com" in normalized:
        return "kuaishou"
    return "unknown"


def extract_share_url(text: str) -> str | None:
    urls = extract_urls(text)
    for url in urls:
        if detect_platform(url) != "unknown":
            return url
    return urls[0] if urls else None


class ResolverService:
    def __init__(self) -> None:
        self.douyin = DouyinResolver()
        self.douyin_downloader = DouyinDownloader()
        self.kuaishou = KuaishouResolver()
        self.kuaishou_downloader = KuaishouDownloader()

    def close(self) -> None:
        self.douyin.close()
        self.kuaishou.close()
        self.kuaishou_downloader.close()

    def can_handle(self, text: str) -> bool:
        extracted = extract_share_url(text)
        return bool(extracted and detect_platform(extracted) != "unknown")

    def resolve(self, text: str, douyin_cookie: str = "", kuaishou_cookie: str = "") -> MediaSource:
        extracted = extract_share_url(text)
        if not extracted:
            raise ValueError("未找到有效的视频链接。")

        platform = detect_platform(extracted)
        if platform == "douyin":
            media = self.douyin.resolve_video(extracted, douyin_cookie)
        elif platform == "kuaishou":
            media = self.kuaishou.resolve_video(extracted, kuaishou_cookie)
        else:
            raise ValueError("当前仅支持抖音和快手单视频分享链接。")

        if not media or not media.downloadUrl:
            raise ValueError(f"{platform} 视频解析失败，请检查链接或稍后重试。")
        return media

    def download(
        self,
        media: MediaSource,
        output_dir: str,
        progress_callback: Callable[[int], None],
        douyin_cookie: str = "",
        kuaishou_cookie: str = "",
    ) -> str:
        if not media.downloadUrl:
            raise ValueError("无法获取视频下载链接。")

        output_path = build_output_path(output_dir, media.title, f"{media.platform}_{media.resolvedId}")
        if media.platform == "douyin":
            result = self.douyin_downloader.download(media.downloadUrl, str(output_path), progress_callback, douyin_cookie)
        elif media.platform == "kuaishou":
            result = self.kuaishou_downloader.download(
                media.downloadUrl,
                str(output_path),
                progress_callback,
                kuaishou_cookie,
            )
        else:
            raise ValueError(f"平台 {media.platform} 暂未支持下载。")

        progress_callback(100)
        return result
