from __future__ import annotations

import uvicorn

from cliplab_backend.config import settings
from cliplab_backend.main import app


def main() -> None:
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        loop="asyncio",
        http="h11",
        lifespan="on",
        access_log=True,
    )


if __name__ == "__main__":
    main()
