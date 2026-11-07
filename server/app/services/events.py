"""In-process domain events with commit-aware publication."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base type for committed domain events."""


@dataclass(frozen=True, slots=True)
class CacheUpdateEvent(DomainEvent):
    """Member cache snapshot that a future WebSocket bridge can distribute."""

    member_id: int
    uid_list: list[str]
    balance_snapshot: int
    offline_allowance: dict[int, int]
    card_status: str
    computed_at_utc: str


@dataclass(frozen=True, slots=True)
class CardStatusChangedEvent(DomainEvent):
    """A card status transition propagated to device caches."""

    uid: str
    status: str


@dataclass(frozen=True, slots=True)
class CatalogChangedEvent(DomainEvent):
    """A committed catalog version change."""

    version: int


@dataclass(frozen=True, slots=True)
class CacheInvalidateEvent(DomainEvent):
    """Invalidate one or more card UIDs in device-side caches."""

    uid_list: list[str] | None = None
    all: bool = False


class EventBus:
    """Simple in-process event dispatcher."""

    def __init__(self) -> None:
        self._subscribers: dict[type[DomainEvent], list[Callable[[DomainEvent], None]]] = {}

    def subscribe(
        self,
        event_type: type[DomainEvent],
        handler: Callable[[DomainEvent], None],
    ) -> Callable[[], None]:
        """Register a handler and return a function that unregisters it."""
        handlers = self._subscribers.setdefault(event_type, [])
        handlers.append(handler)

        def unsubscribe() -> None:
            if handler in handlers:
                handlers.remove(handler)

        return unsubscribe

    def publish(self, domain_event: DomainEvent) -> None:
        """Publish to handlers registered for the event's concrete type or bases."""
        for event_type, handlers in tuple(self._subscribers.items()):
            if isinstance(domain_event, event_type):
                for handler in tuple(handlers):
                    try:
                        handler(domain_event)
                    except Exception:
                        logger.exception(
                            "domain_event_handler_failed event=%s", type(domain_event).__name__
                        )


_bus = EventBus()


@event.listens_for(Session, "after_commit")
def _publish_pending_events(session: Session) -> None:
    """Publish queued events only after the outer database transaction commits."""
    pending = session.info.pop("mgt_pending_events", [])
    for domain_event in pending:
        _bus.publish(domain_event)


@event.listens_for(Session, "after_rollback")
def _discard_pending_events(session: Session) -> None:
    """Prevent rolled-back events from leaking into a later transaction on this session."""
    session.info.pop("mgt_pending_events", None)
