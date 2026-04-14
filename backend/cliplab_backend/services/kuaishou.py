from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import httpx
import yaml
from lxml import html as lxml_html

from cliplab_backend.schemas import MediaSource


@dataclass
class KuaishouVideo:
    """快手视频信息"""
    video_id: str
    title: str
    author_id: str
    author_name: str
    duration: str  # HH:MM:SS 格式
    timestamp: int  # 毫秒时间戳
    cover_url: str
    download_url: str
    view_count: int = 0
    like_count: int = 0
    share_count: int = 0
    comment_count: int = 0


@dataclass
class KuaishouUser:
    """快手用户信息"""
    user_id: str
    user_name: str
    fan_count: int = 0
    follow_count: int = 0
    photo_count: int = 0


class KuaishouResolver:
    """快手视频解析器，参考 KS-Downloader 实现"""

    # URL 正则表达式
    URL_PATTERN = re.compile(r"https?://[^\s<>\"{}|\\^`\[\]]+")
    SHORT_URL_PATTERN = re.compile(r"https?://v\.kuaishou\.com/[^\s/\"<>\\^`{|}]+")
    PC_DETAIL_PATTERN = re.compile(r"https?://\S*kuaishou\.com/short-video/([^?\s]+)")
    USER_PROFILE_PATTERN = re.compile(r"https?://(?:www|live)\.kuaishou\.com/profile/([^?/\s]+)")
    FW_PHOTO_PATTERN = re.compile(r"https?://\S*kuaishou\.com/fw/photo/([^?\s]+)")
    REDIRECT_FW_PHOTO_PATTERN = re.compile(r"https?://\S*chenzhongtech\.(?:com|cn)/fw/photo/([^?\s]+)")

    # HTTP 头
    PC_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    API_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.kuaishou.com",
    }

    MOBILE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def extract_urls(text: str) -> list[str]:
        """从文本中提取所有快手 URL"""
        urls = KuaishouResolver.URL_PATTERN.findall(text)
        result = []
        for url in urls:
            if "kuaishou" in url.lower():
                result.append(url)
        return result

    @staticmethod
    def detect_url_type(url: str) -> Literal["short", "video", "user", "fw_photo", "unknown"]:
        """检测 URL 类型"""
        if KuaishouResolver.SHORT_URL_PATTERN.search(url):
            return "short"
        if KuaishouResolver.PC_DETAIL_PATTERN.search(url):
            return "video"
        if KuaishouResolver.USER_PROFILE_PATTERN.search(url):
            return "user"
        if KuaishouResolver.FW_PHOTO_PATTERN.search(url):
            return "fw_photo"
        return "unknown"

    def resolve_short_url(self, url: str, cookie: str = "") -> str:
        """解析短链接，获取真实视频 URL"""
        headers = self.PC_HEADERS | ({"Cookie": cookie} if cookie else {})
        response = self.client.get(url, headers=headers)
        response.raise_for_status()
        return str(response.url)

    def _extract_video_id_from_url(self, url: str, cookie: str = "") -> str | None:
        """从 URL 中提取视频 ID"""
        # PC 视频页: /short-video/{video_id}
        match = self.PC_DETAIL_PATTERN.search(url)
        if match:
            return match.group(1)

        # APP 分享链接: /fw/photo/{photo_id}
        match = self.FW_PHOTO_PATTERN.search(url)
        if match:
            return match.group(1)

        match = self.REDIRECT_FW_PHOTO_PATTERN.search(url)
        if match:
            return match.group(1)

        # 已经是短链接，重定向后解析
        if "v.kuaishou.com" in url:
            resolved = self.resolve_short_url(url, cookie)
            return self._extract_video_id_from_url(resolved, cookie)

        return None

    def _extract_user_id_from_url(self, url: str) -> str | None:
        """从 URL 中提取用户 ID"""
        match = self.USER_PROFILE_PATTERN.search(url)
        if match:
            return match.group(1)
        return None

    def fetch_web_page(self, url: str, cookie: str = "") -> str:
        """获取网页内容"""
        headers = self.PC_HEADERS | ({"Cookie": cookie} if cookie else {})
        response = self.client.get(url, headers=headers)
        response.raise_for_status()
        return response.text

    def parse_web_page(self, html: str, video_id: str) -> KuaishouVideo | None:
        """解析快手网页（移动版），提取视频信息"""
        try:
            # 移动版 HTML 包含直接的视频 CDN URL（kwaicdn.com）
            # 格式: https://...kwaicdn.com/.../xxx.mp4?pkey=...
            video_url_match = re.search(r'(https://[^\s"\'\\]*\.mp4\?pkey=[^\s"\'\\]+)', html)
            if not video_url_match:
                return None
            download_url = video_url_match.group(1)

            # 提取 caption（标题）
            caption_match = re.search(r'"caption"\s*:\s*"([^"]*)"', html)
            caption = ""
            if caption_match:
                caption = caption_match.group(1).replace("\\n", "\n").replace("\\/", "/").replace("\\u002F", "/")

            # 提取 duration（毫秒）
            duration_match = re.search(r'"duration"\s*:\s*(\d+)', html)
            duration = int(duration_match.group(1)) if duration_match else 0

            # 提取作者名称（可能在多个位置）
            author_name = ""
            author_name_match = re.search(r'"authorName"\s*:\s*"([^"]*)"', html)
            if author_name_match:
                author_name = author_name_match.group(1).replace("\\u002F", "/")
            else:
                # 尝试 userName
                user_name_match = re.search(r'"userName"\s*:\s*"([^"]*)"', html)
                if user_name_match:
                    author_name = user_name_match.group(1).replace("\\u002F", "/")

            return KuaishouVideo(
                video_id=video_id,
                title=caption,
                author_id="",
                author_name=author_name,
                duration=self._format_duration(duration),
                timestamp=0,
                cover_url="",
                download_url=download_url,
                view_count=0,
                like_count=0,
            )
        except (KeyError, TypeError, ValueError, AttributeError, re.error):
            return None

    def fetch_user_profile(self, user_id: str) -> KuaishouUser | None:
        """获取用户信息"""
        url = f"https://www.kuaishou.com/profile/{user_id}"
        try:
            html = self.fetch_web_page(url)
            return self.parse_user_profile(html, user_id)
        except Exception:
            return None

    def parse_user_profile(self, html: str, user_id: str) -> KuaishouUser | None:
        """解析用户主页"""
        tree = lxml_html.fromstring(html)

        scripts = tree.xpath("//script/text()")
        apollo_data = None
        for script in scripts:
            if "window.__APOLLO_STATE__" in script:
                text = script.replace("window.__APOLLO_STATE__=", "").strip()
                text = re.sub(r";\s*\(function\(\)\{var s;.*?parentNode\.removeChild\(s\);\}\(\)\);?\s*$", "", text)
                try:
                    apollo_data = yaml.safe_load(text)
                except yaml.YAMLError:
                    pass
                break

        if not apollo_data:
            return None

        try:
            default_client = apollo_data.get("defaultClient", {})

            # 查找用户信息
            user_key = f"VisionUserDetail:{user_id}"
            if user_key in default_client:
                user_data = default_client[user_key]
                return KuaishouUser(
                    user_id=user_id,
                    user_name=user_data.get("name", ""),
                    fan_count=user_data.get("fanCount", 0),
                    follow_count=user_data.get("followCount", 0),
                    photo_count=user_data.get("photoCount", 0),
                )
        except (KeyError, TypeError):
            pass

        return None

    def fetch_user_videos(self, user_id: str) -> list[KuaishouVideo]:
        """获取用户所有视频"""
        videos = []
        url = f"https://www.kuaishou.com/profile/{user_id}"

        try:
            html = self.fetch_web_page(url)
            videos = self.parse_user_videos(html, user_id)
        except Exception:
            pass

        return videos

    def parse_user_videos(self, html: str, user_id: str) -> list[KuaishouVideo]:
        """解析用户主页获取视频列表"""
        tree = lxml_html.fromstring(html)

        scripts = tree.xpath("//script/text()")
        apollo_data = None
        for script in scripts:
            if "window.__APOLLO_STATE__" in script:
                text = script.replace("window.__APOLLO_STATE__=", "").strip()
                text = re.sub(r";\s*\(function\(\)\{var s;.*?parentNode\.removeChild\(s\);\}\(\)\);?\s*$", "", text)
                try:
                    apollo_data = yaml.safe_load(text)
                except yaml.YAMLError:
                    pass
                break

        if not apollo_data:
            return []

        videos = []
        try:
            default_client = apollo_data.get("defaultClient", {})

            # 遍历所有 key 查找视频
            for key, value in default_client.items():
                if key.startswith("VisionVideoDetailPhoto:") and isinstance(value, dict):
                    detail = value
                    video_id = detail.get("id", "")

                    # 查找作者
                    author_id = ""
                    author_name = ""
                    for ak, av in default_client.items():
                        if "VisionVideoDetailAuthor:" in ak and isinstance(av, dict):
                            author_id = av.get("id", "")
                            author_name = av.get("name", "")
                            break

                    videos.append(KuaishouVideo(
                        video_id=video_id,
                        title=detail.get("caption", ""),
                        author_id=author_id,
                        author_name=author_name,
                        duration=self._format_duration(detail.get("duration", 0)),
                        timestamp=detail.get("timestamp", 0),
                        cover_url=detail.get("coverUrl", ""),
                        download_url=detail.get("photoUrl", ""),
                        view_count=detail.get("viewCount", 0),
                        like_count=detail.get("realLikeCount", 0),
                    ))
        except (KeyError, TypeError):
            pass

        return videos

    @staticmethod
    def _format_duration(duration_ms: int) -> str:
        """将毫秒转换为 HH:MM:SS 格式"""
        seconds = duration_ms // 1000
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def resolve_video(self, url: str, cookie: str = "") -> MediaSource | None:
        """解析视频 URL，返回 MediaSource"""
        video_id = self._extract_video_id_from_url(url, cookie)
        if not video_id:
            return None

        # 构建干净的 URL，不带查询参数
        full_url = f"https://www.kuaishou.com/short-video/{video_id}"

        try:
            # 使用移动端 headers 获取页面，移动版页面包含直接的视频 CDN URL
            headers = self.MOBILE_HEADERS | ({"Cookie": cookie} if cookie else {})
            response = self.client.get(full_url, headers=headers)
            response.raise_for_status()
            html = response.text

            video = self.parse_web_page(html, video_id)

            if not video:
                return None

            return MediaSource(
                platform="kuaishou",
                shareUrl=url,
                resolvedId=video.video_id,
                title=video.title or f"快手视频_{video.video_id}",
                author=video.author_name or "Unknown",
                duration=self._parse_duration(video.duration),
                coverUrl=video.cover_url,
                downloadUrl=video.download_url,
            )
        except Exception:
            return None

    def resolve_user(self, url: str) -> tuple[KuaishouUser | None, list[KuaishouVideo]]:
        """解析用户主页 URL，返回用户信息和视频列表"""
        user_id = self._extract_user_id_from_url(url)
        if not user_id:
            return None, []

        user = self.fetch_user_profile(user_id)
        videos = self.fetch_user_videos(user_id)

        return user, videos

    @staticmethod
    def _parse_duration(duration_str: str) -> float:
        """将 HH:MM:SS 格式转换为秒数"""
        try:
            parts = duration_str.split(":")
            if len(parts) == 3:
                h, m, s = map(int, parts)
                return h * 3600 + m * 60 + s
            elif len(parts) == 2:
                m, s = map(int, parts)
                return m * 60 + s
            return 0.0
        except (ValueError, TypeError):
            return 0.0


class KuaishouDownloader:
    """快手视频下载器"""

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=60.0, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def download(
        self,
        url: str,
        output_path: str,
        progress_callback: callable | None = None,
        cookie: str = "",
    ) -> str:
        """下载视频到指定路径"""
        from pathlib import Path

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "identity",  # 不压缩，方便下载
            "Referer": "https://www.kuaishou.com",
        }
        if cookie:
            headers["Cookie"] = cookie

        with self.client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0

            with open(output, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress = min(94, int(downloaded / total_size * 100))
                            progress_callback(progress)

        return str(output)
