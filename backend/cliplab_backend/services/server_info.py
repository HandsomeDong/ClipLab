from __future__ import annotations

import socket
from urllib.parse import urlparse

from cliplab_backend.config import settings
from cliplab_backend.schemas import ServerInfo


def discover_lan_ips() -> list[str]:
    candidates: set[str] = set()

    try:
        hostname_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        candidates.update(ip for ip in hostname_ips if not ip.startswith("127."))
    except OSError:
        pass

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        candidates.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass

    return sorted(candidates)


def build_server_info() -> ServerInfo:
    parsed = urlparse(settings.backend_url)
    port = parsed.port or settings.port
    local_api_url = settings.backend_url
    remote_submit_urls = [f"http://{ip}:{port}/api/tasks/download" for ip in discover_lan_ips()]
    remote_web_urls = [f"http://{ip}:{port}/remote" for ip in discover_lan_ips()]
    return ServerInfo(
        appName=settings.app_name,
        localApiUrl=local_api_url,
        remoteSubmitUrls=remote_submit_urls,
        remoteWebUrls=remote_web_urls,
    )
