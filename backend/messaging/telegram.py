"""
Telegram messaging integration for Primus.
"""

from typing import Dict, Optional
import httpx
import asyncio

from backend.messaging.base import BaseMessaging, IncomingMessage, OutgoingMessage
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


class TelegramMessaging(BaseMessaging):
    """Telegram messaging implementation."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.bot_token = config.get("bot_token", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._last_update_id = 0
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None

    async def _get_updates(self) -> list:
        """Get new updates from Telegram."""
        params = {
            "offset": self._last_update_id + 1,
            "limit": 100,
            "timeout": 30
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f"{self.base_url}/getUpdates", params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("ok"):
                return data.get("result", [])
            return []

    async def _process_update(self, update: dict):
        """Process a single update."""
        if "message" not in update:
            return

        message = update["message"]
        chat_id = str(message["chat"]["id"])
        user_id = str(message["from"]["id"])
        text = message.get("text", "")

        if not text:
            return

        if not self.is_user_allowed(user_id):
            logger.info(f"Blocked message from unauthorized user: {user_id}")
            return

        self._last_update_id = update["update_id"]

        incoming = IncomingMessage(
            user_id=user_id,
            conversation_id=chat_id,
            content=text,
            platform="telegram",
            metadata={"chat": message["chat"]}
        )

        if self.message_handler:
            try:
                response_content = await self.message_handler(incoming)
                await self.send_message(OutgoingMessage(
                    user_id=user_id,
                    conversation_id=chat_id,
                    content=response_content
                ))
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

    async def _poll(self):
        """Long polling loop for updates."""
        self._running = True
        logger.info("Telegram polling started")
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._process_update(update)
            except Exception as e:
                logger.error(f"Polling error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def start(self):
        """Start polling for messages."""
        if not self.enabled:
            logger.info("Telegram messaging not enabled")
            return

        if not self.bot_token:
            logger.error("Telegram bot token not configured")
            return

        self._poll_task = asyncio.create_task(self._poll())

    async def stop(self):
        """Stop polling for messages."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("Telegram polling stopped")

    async def send_message(self, msg: OutgoingMessage):
        """Send a message to Telegram."""
        if not self.enabled:
            return

        async with httpx.AsyncClient(timeout=30) as client:
            params = {
                "chat_id": msg.conversation_id,
                "text": msg.content,
                "parse_mode": "Markdown"
            }
            try:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    params=params
                )
                response.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to send Telegram message: {e}", exc_info=True)
