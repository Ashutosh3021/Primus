"""
Base messaging interface for Primus.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Callable
from dataclasses import dataclass


@dataclass
class IncomingMessage:
    """Represents an incoming message from any platform."""
    user_id: str
    conversation_id: str
    content: str
    platform: str
    metadata: dict


@dataclass
class OutgoingMessage:
    """Represents an outgoing message to any platform."""
    user_id: str
    conversation_id: str
    content: str
    metadata: dict = None


class BaseMessaging(ABC):
    """Base class for messaging platforms."""

    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", False)
        self.allowed_users: List[str] = config.get("allowed_users", [])
        self.message_handler: Optional[Callable[[IncomingMessage], str]] = None

    def set_message_handler(self, handler: Callable[[IncomingMessage], str]):
        """Set handler for incoming messages."""
        self.message_handler = handler

    def is_user_allowed(self, user_id: str) -> bool:
        """Check if user is allowed."""
        if not self.allowed_users:
            return True
        return user_id in self.allowed_users

    @abstractmethod
    async def start(self):
        """Start listening for messages."""
        pass

    @abstractmethod
    async def stop(self):
        """Stop listening for messages."""
        pass

    @abstractmethod
    async def send_message(self, msg: OutgoingMessage):
        """Send a message through the platform."""
        pass
