from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import httpx

from cliplab_backend.schemas import MediaSource


@dataclass
class DouyinVideo:
    aweme_id: str
    title: str
    author: str
    duration_ms: int
    cover_url: str
    play_url: str


class DouyinResolver:
    SHORT_URL_PATTERN = re.compile(r"https?://v\.douyin\.com/[^\s/\"<>\\^`{|}]+")
    SHARE_URL_PATTERN = re.compile(r"https?://www\.iesdouyin\.com/share/video/(\d+)")
    DETAIL_URL_PATTERN = re.compile(r"https?://www\.douyin\.com/(?:video|note|slides)/(\d+)")
    ROUTER_DATA_PATTERN = re.compile(r"window\._ROUTER_DATA\s*=\s*(\{.+?\})\s*</script>", re.DOTALL)
    MOBILE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
        ),
        "Referer": "https://www.douyin.com/",
    }

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def resolve_video(self, url: str, cookie: str = "") -> MediaSource | None:
        aweme_id = self._extract_aweme_id(url)
        if not aweme_id:
            return None

        video = self._fetch_share_page_video(aweme_id, cookie)
        if not video:
            return None

        return MediaSource(
            platform="douyin",
            shareUrl=url,
            resolvedId=video.aweme_id,
            title=video.title or f"抖音视频_{video.aweme_id}",
            author=video.author or "Unknown",
            duration=video.duration_ms / 1000,
            coverUrl=video.cover_url,
            downloadUrl=video.play_url,
        )

    def _extract_aweme_id(self, url: str) -> str | None:
        for pattern in (self.SHARE_URL_PATTERN, self.DETAIL_URL_PATTERN):
            match = pattern.search(url)
            if match:
                return match.group(1)

        if self.SHORT_URL_PATTERN.search(url):
            response = self.client.get(url, headers={"User-Agent": self.MOBILE_HEADERS["User-Agent"]})
            for response_url in [*(str(item.url) for item in response.history), str(response.url)]:
                for pattern in (self.SHARE_URL_PATTERN, self.DETAIL_URL_PATTERN):
                    match = pattern.search(response_url)
                    if match:
                        return match.group(1)
        return None

    def _fetch_share_page_video(self, aweme_id: str, cookie: str = "") -> DouyinVideo | None:
        request = urllib.request.Request(
            f"https://www.iesdouyin.com/share/video/{aweme_id}/",
            headers={
                **self.MOBILE_HEADERS,
                **({"Cookie": cookie} if cookie else {}),
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="ignore")

        match = self.ROUTER_DATA_PATTERN.search(html)
        if not match:
            return None

        loader_data = json.loads(match.group(1)).get("loaderData", {})
        page_data = loader_data.get("video_(id)/page", {})
        items = ((page_data.get("videoInfoRes") or {}).get("item_list") or [])
        if not items:
            return None

        item = items[0]
        author = item.get("author") or {}
        video = item.get("video") or {}
        cover = video.get("cover") or {}
        play_addr = video.get("play_addr") or {}
        uri = play_addr.get("uri", "")
        play_url = self._build_no_watermark_url(play_addr, uri)

        return DouyinVideo(
            aweme_id=item.get("aweme_id", aweme_id),
            title=item.get("desc", ""),
            author=author.get("nickname", ""),
            duration_ms=int(video.get("duration", 0) or 0),
            cover_url=(cover.get("url_list") or [""])[0],
            play_url=play_url,
        )

    @staticmethod
    def _build_no_watermark_url(play_addr: dict, uri: str) -> str:
        urls = play_addr.get("url_list") or []
        if urls:
            return urls[0].replace("/playwm/", "/play/")
        if uri:
            return f"https://aweme.snssdk.com/aweme/v1/play/?line=0&ratio=720p&video_id={uri}"
        return ""


class DouyinDownloader:
    REFERER = "https://www.iesdouyin.com/"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    )

    def download(self, url: str, output_path: str, progress_callback: callable | None = None, cookie: str = "") -> str:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "curl",
            "-L",
            "--fail",
            "--silent",
            "--show-error",
            "-A",
            self.USER_AGENT,
            "-e",
            self.REFERER,
            "-o",
            str(output),
        ]
        if cookie:
            command.extend(["-H", f"Cookie: {cookie}"])
        command.append(url)

        if progress_callback:
            progress_callback(20)
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise ValueError(completed.stderr.strip() or "抖音视频下载失败。")
        if progress_callback:
            progress_callback(98)
        return str(output)
