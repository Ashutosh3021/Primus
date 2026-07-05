"""
Telegram messaging integration for Primus.

Every stage of the pipeline is instrumented with a unique log tag so that
Render logs show exactly where execution stops after a single incoming message:

  [TG_INIT]     – object construction and token validation
  [TG_START]    – polling loop startup
  [TG_POLL]     – each getUpdates call and raw API response
  [TG_UPDATE]   – raw update object received from Telegram
  [TG_PARSE]    – fields extracted from the update
  [TG_AI]       – hand-off to and return from the AI router
  [TG_REPLY]    – sendMessage request and Telegram API response
  [TG_ERROR]    – every caught exception with full traceback
"""

from typing import Optional
import httpx
import asyncio

from backend.messaging.base import BaseMessaging, IncomingMessage, OutgoingMessage
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


class TelegramMessaging(BaseMessaging):
    """Telegram messaging implementation."""

    # ------------------------------------------------------------------ init

    def __init__(self, config: dict):
        super().__init__(config)
        self.bot_token = config.get("bot_token", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._last_update_id = 0
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None

        # Mask token for safe logging (show last 6 chars only)
        token_hint = (
            f"…{self.bot_token[-6:]}" if len(self.bot_token) >= 6
            else "<empty>"
        )
        logger.info(
            f"[TG_INIT] TelegramMessaging constructed | "
            f"enabled={self.enabled} | "
            f"token_hint={token_hint} | "
            f"allowed_users={self.allowed_users or 'all'}"
        )

        if not self.bot_token:
            logger.error(
                "[TG_INIT] bot_token is EMPTY — "
                "Telegram will not work. "
                "Check secret_ref in config and that the secret is stored."
            )

    # ------------------------------------------------------------------ polling

    async def _get_updates(self) -> list:
        """Call Telegram getUpdates and return the result list."""
        params = {
            "offset": self._last_update_id + 1,
            "limit": 100,
            "timeout": 30,
        }
        logger.info(
            f"[TG_POLL] getUpdates request | offset={params['offset']}"
        )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(
                    f"{self.base_url}/getUpdates", params=params
                )
                logger.info(
                    f"[TG_POLL] getUpdates response | "
                    f"status={response.status_code} | "
                    f"body_preview={response.text[:200]}"
                )
                response.raise_for_status()
                data = response.json()
                if data.get("ok"):
                    updates = data.get("result", [])
                    if updates:
                        logger.info(
                            f"[TG_POLL] Received {len(updates)} update(s)"
                        )
                    return updates
                else:
                    logger.warning(
                        f"[TG_POLL] Telegram returned ok=false | "
                        f"description={data.get('description', 'no description')}"
                    )
                    return []
        except httpx.HTTPStatusError as exc:
            logger.exception(
                f"[TG_ERROR] getUpdates HTTP error | "
                f"status={exc.response.status_code} | "
                f"body={exc.response.text[:300]}"
            )
            raise
        except Exception:
            logger.exception("[TG_ERROR] getUpdates unexpected error")
            raise

    async def _process_update(self, update: dict):
        """Process a single update object end-to-end."""
        update_id = update.get("update_id", "?")
        logger.info(
            f"[TG_UPDATE] Processing update_id={update_id} | "
            f"keys={list(update.keys())}"
        )

        if "message" not in update:
            logger.info(
                f"[TG_UPDATE] update_id={update_id} has no 'message' key — skipping "
                f"(type may be edited_message, callback_query, etc.)"
            )
            return

        message = update["message"]
        chat_id = str(message["chat"]["id"])
        user_id = str(message["from"]["id"])
        text = message.get("text", "")

        logger.info(
            f"[TG_PARSE] update_id={update_id} | "
            f"chat_id={chat_id} | "
            f"user_id={user_id} | "
            f"text_len={len(text)} | "
            f"text_preview={text[:80]!r}"
        )

        if not text:
            logger.info(
                f"[TG_PARSE] update_id={update_id} — message has no text "
                "(may be a photo, sticker, or service message) — skipping"
            )
            # Still advance the offset so this update is not re-fetched.
            self._last_update_id = update_id
            return

        if not self.is_user_allowed(user_id):
            logger.warning(
                f"[TG_PARSE] update_id={update_id} — "
                f"user_id={user_id} is NOT in allowed_users list — blocked"
            )
            # Advance offset even for blocked users so this update is not
            # re-fetched on the next getUpdates call. Without this, a single
            # message from an unknown user stalls the polling loop forever.
            self._last_update_id = update_id
            return

        self._last_update_id = update_id
        logger.info(
            f"[TG_PARSE] update_id={update_id} — "
            f"user allowed, advancing last_update_id to {update_id}"
        )

        incoming = IncomingMessage(
            user_id=user_id,
            conversation_id=chat_id,
            content=text,
            platform="telegram",
            metadata={"chat": message["chat"]},
        )

        if self.message_handler is None:
            logger.error(
                f"[TG_ERROR] update_id={update_id} — "
                "message_handler is None. "
                "initialize_messaging() was not called or handler was not set."
            )
            return

        logger.info(
            f"[TG_AI] update_id={update_id} — "
            f"calling message_handler for user_id={user_id}"
        )
        try:
            response_content = await self.message_handler(incoming)
            logger.info(
                f"[TG_AI] update_id={update_id} — "
                f"handler returned | "
                f"reply_len={len(response_content)} | "
                f"reply_preview={response_content[:120]!r}"
            )
        except Exception:
            logger.exception(
                f"[TG_ERROR] update_id={update_id} — "
                "message_handler raised an exception"
            )
            return

        logger.info(
            f"[TG_REPLY] update_id={update_id} — "
            f"sending reply to chat_id={chat_id}"
        )
        await self.send_message(
            OutgoingMessage(
                user_id=user_id,
                conversation_id=chat_id,
                content=response_content,
            )
        )

    async def _poll(self):
        """Long-polling loop."""
        self._running = True
        logger.info(
            "[TG_START] Telegram long-polling loop entered — "
            "waiting for updates…"
        )
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._process_update(update)
            except Exception:
                logger.exception(
                    "[TG_ERROR] Unhandled exception in polling loop — "
                    "sleeping 5 s before retry"
                )
                await asyncio.sleep(5)

    # ------------------------------------------------------------------ start / stop

    async def start(self):
        """Start polling for messages."""
        logger.info(
            f"[TG_START] start() called | "
            f"enabled={self.enabled} | "
            f"token_present={bool(self.bot_token)}"
        )

        if not self.enabled:
            logger.warning(
                "[TG_START] Telegram is NOT enabled in config — "
                "polling will not start. "
                "Set messaging.telegram.enabled=true in config.json."
            )
            return

        if not self.bot_token:
            logger.error(
                "[TG_START] bot_token is empty — cannot start polling. "
                "Store the secret via POST /api/secrets/set and "
                "re-apply config via POST /api/config/apply."
            )
            return

        logger.info("[TG_START] Spawning polling task…")
        self._poll_task = asyncio.create_task(self._poll())

        # Log any unexpected task failure so it is visible in Render logs.
        def _on_poll_done(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error(
                    f"[TG_ERROR] Polling task terminated unexpectedly: "
                    f"{task.exception()!r}"
                )

        self._poll_task.add_done_callback(_on_poll_done)
        logger.info(
            f"[TG_START] Polling task created | task={self._poll_task!r}"
        )

    async def stop(self):
        """Stop polling for messages."""
        logger.info("[TG_START] stop() called — cancelling polling task")
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("[TG_START] Telegram polling stopped")

    # ------------------------------------------------------------------ send

    async def send_message(self, msg: OutgoingMessage):
        """Send a message to Telegram and log the full API response."""
        if not self.enabled:
            logger.warning(
                "[TG_REPLY] send_message called but Telegram is not enabled — "
                "message NOT sent"
            )
            return

        params = {
            "chat_id": msg.conversation_id,
            "text": msg.content,
            # No parse_mode — AI responses are free-form text and may contain
            # characters that Telegram's Markdown parser rejects (underscores,
            # asterisks, backticks, brackets).  Sending as plain text is always
            # safe.  If rich formatting is needed in future, switch to
            # parse_mode="MarkdownV2" with a proper escaping helper.
        }
        logger.info(
            f"[TG_REPLY] sendMessage request | "
            f"chat_id={msg.conversation_id} | "
            f"text_len={len(msg.content)} | "
            f"text_preview={msg.content[:80]!r}"
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage", params=params
                )
                logger.info(
                    f"[TG_REPLY] sendMessage response | "
                    f"status={response.status_code} | "
                    f"body={response.text[:400]}"
                )
                response.raise_for_status()
                logger.info(
                    f"[TG_REPLY] Message delivered successfully to "
                    f"chat_id={msg.conversation_id}"
                )
        except httpx.HTTPStatusError as exc:
            logger.exception(
                f"[TG_ERROR] sendMessage HTTP error | "
                f"status={exc.response.status_code} | "
                f"body={exc.response.text[:300]}"
            )
        except Exception:
            logger.exception(
                f"[TG_ERROR] sendMessage unexpected error | "
                f"chat_id={msg.conversation_id}"
            )
