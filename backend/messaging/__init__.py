"""
Messaging module for Primus.
"""

from backend.messaging.base import (
    BaseMessaging, IncomingMessage, OutgoingMessage
)
from backend.messaging.telegram import TelegramMessaging

MESSAGING_PLATFORMS = {
    "telegram": TelegramMessaging
}

__all__ = [
    "BaseMessaging",
    "IncomingMessage",
    "OutgoingMessage",
    "TelegramMessaging",
    "MESSAGING_PLATFORMS"
]
