import asyncio
import logging
from typing import Callable, Dict, List, Type
from core.event_schemas import BaseEvent

logger = logging.getLogger(__name__)

class EventBus:
    """
    Central Event Bus for Pub/Sub.
    Singleton pattern ensures all parts of the app use the same bus.
    """
    _instance = None
    _subscribers: Dict[str, List[Callable]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EventBus, cls).__new__(cls)
            cls._subscribers = {}
        return cls._instance

    @classmethod
    def subscribe(cls, event_type: str, handler: Callable):
        """Register a handler for a specific event type"""
        if event_type not in cls._subscribers:
            cls._subscribers[event_type] = []
        cls._subscribers[event_type].append(handler)
        logger.info(f"Subscribed {handler.__name__} to {event_type}")

    @classmethod
    async def publish(cls, event: BaseEvent):
        """Publish an event to all subscribers"""
        if event.type in cls._subscribers:
            handlers = cls._subscribers[event.type]
            logger.info(f"Adding event {event.type} to processing queue ({len(handlers)} handlers)")
            
            # Execute handlers asynchronously
            # We don't await them one by one to avoid blocking, 
            # we gather them to run concurrently
            tasks = [handler(event) for handler in handlers]
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.debug(f"No subscribers for {event.type}")

# Global Event Bus Instance
event_bus = EventBus()
