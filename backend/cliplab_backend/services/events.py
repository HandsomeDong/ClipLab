from __future__ import annotations

import asyncio

from cliplab_backend.schemas import EventMessage, LogRecord, TaskRecord


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    async def publish_task(self, task: TaskRecord) -> None:
        message = EventMessage(type="task_update", task=task, log=None).model_dump_json()
        await self._broadcast(message)

    async def publish_heartbeat(self) -> None:
        message = EventMessage(type="heartbeat", task=None, log=None).model_dump_json()
        await self._broadcast(message)

    async def publish_log(self, log: LogRecord) -> None:
        message = EventMessage(type="log_update", task=None, log=log).model_dump_json()
        await self._broadcast(message)

    async def _broadcast(self, message: str) -> None:
        dead: list[asyncio.Queue[str]] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self._subscribers.discard(queue)

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=16)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)
