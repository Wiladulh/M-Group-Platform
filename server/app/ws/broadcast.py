"""Bridge synchronous committed domain events to async WebSocket sends."""

import asyncio
import logging
from contextlib import suppress

from app.ws.connection_manager import manager
from app.ws.protocol import EnvelopeEnvelope

logger = logging.getLogger(__name__)


class BroadcastBus:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[EnvelopeEnvelope] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._task is None:
            self._task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._loop = None

    def enqueue(self, envelope: EnvelopeEnvelope) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, envelope)

    async def _consume(self) -> None:
        while True:
            envelope = await self._queue.get()
            for device_pk in manager.connected_devices():
                await manager.send(device_pk, envelope)
            self._queue.task_done()


broadcast_bus = BroadcastBus()
