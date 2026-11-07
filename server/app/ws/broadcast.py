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
            tuple[asyncio.Queue[tuple[EnvelopeEnvelope, int | None]], asyncio.Task],
        ] = {}

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        if loop not in self._consumers:
            queue: asyncio.Queue[tuple[EnvelopeEnvelope, int | None]] = asyncio.Queue()
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

    def enqueue(self, envelope: EnvelopeEnvelope, target_device_id_pk: int | None = None) -> None:
        if not self._consumers:
            return
        loop = next(reversed(self._consumers))
        queue, _task = self._consumers[loop]
        if loop.is_running():
            loop.call_soon_threadsafe(queue.put_nowait, (envelope, target_device_id_pk))

    async def _consume(self, queue: asyncio.Queue[tuple[EnvelopeEnvelope, int | None]]) -> None:
        while True:
            envelope, target_device_id_pk = await queue.get()
            device_ids = (
                (target_device_id_pk,)
                if target_device_id_pk is not None
                else manager.connected_devices()
            )
            for device_pk in device_ids:
                await manager.send(device_pk, envelope)
            queue.task_done()


broadcast_bus = BroadcastBus()
