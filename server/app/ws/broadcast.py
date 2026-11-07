"""Bridge synchronous committed domain events to async WebSocket sends."""

import asyncio
import logging
from contextlib import suppress

from app.ws.connection_manager import manager
from app.ws.protocol import EnvelopeEnvelope

logger = logging.getLogger(__name__)


class BroadcastBus:
    def __init__(self) -> None:
        self._consumers: dict[
            asyncio.AbstractEventLoop,
            tuple[asyncio.Queue[EnvelopeEnvelope], asyncio.Task],
        ] = {}

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        if loop not in self._consumers:
            queue: asyncio.Queue[EnvelopeEnvelope] = asyncio.Queue()
            task = asyncio.create_task(self._consume(queue))
            self._consumers[loop] = (queue, task)

    async def stop(self) -> None:
        loop = asyncio.get_running_loop()
        consumer = self._consumers.pop(loop, None)
        if consumer is not None:
            _queue, task = consumer
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def enqueue(self, envelope: EnvelopeEnvelope) -> None:
        for loop, (queue, _task) in tuple(self._consumers.items()):
            if loop.is_running():
                loop.call_soon_threadsafe(queue.put_nowait, envelope)

    async def _consume(self, queue: asyncio.Queue[EnvelopeEnvelope]) -> None:
        while True:
            envelope = await queue.get()
            for device_pk in manager.connected_devices():
                await manager.send(device_pk, envelope)
            queue.task_done()


broadcast_bus = BroadcastBus()
