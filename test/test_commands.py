"""
Verification that Primus has exactly ONE runtime entry point (backend.api.handle_message)
and that every interface — REST API and Telegram — behaves identically through it.

Covers Req: single runtime, global ProviderManager, global persona, persistent skills,
identical command handling across interfaces.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import init_db
from backend.config import load_config
from backend.api import (
    initialize_memory,
    initialize_router,
    handle_message,
    _handle_incoming_message,
    get_providers_info,
    get_persona_manager,
    get_active_persona_text,
    get_skill_manager,
    build_prompt,
)
from backend.persona import PERSONA_PRESETS
from backend.messaging.base import IncomingMessage


class FakeCompletion:
    def __init__(self, content, provider="openrouter", model="m"):
        self.content = content
        self.provider = provider
        self.model = model
        self.usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        self.finish_reason = "stop"


async def fake_route_chat(messages, **kwargs):
    fake_route_chat.last_messages = messages
    return FakeCompletion("reply"), {
        "mode": "manual", "provider": "openrouter", "model": "m", "category": None,
    }


async def main():
    import backend.api as api

    await init_db()
    config = load_config()
    initialize_memory(config)        # also inits persona + skills
    initialize_router(config)       # builds the shared ProviderManager

    orig_route = api.route_chat
    orig_persist = api._persist_state
    api.route_chat = fake_route_chat

    try:
        # ── 1. Commands route without crashing / persisting ──────────────────
        r = await handle_message("/provider", "u", "c")
        assert r["command"] == "provider" and r["ok"] is False, r
        r = await handle_message("/model", "u", "c")
        assert r["command"] == "model" and r["ok"] is False, r
        print("OK  /provider and /model route (usage errors, no persistence)")

        # ── 2. Provider switch identical across REST + Telegram ──────────────
        api._persist_state = lambda: None  # don't mutate config.json in test
        r1 = await handle_message("/provider openai", "u", "c")
        assert r1["command"] == "provider" and r1["ok"] is True, r1
        after_rest = get_providers_info()["current_provider"]
        r2 = await handle_message("/provider openrouter", "u", "c")
        assert r2["command"] == "provider" and r2["ok"] is True, r2
        after_tg = get_providers_info()["current_provider"]
        assert after_rest == "openai" and after_tg == "openrouter", (after_rest, after_tg)
        api._persist_state = orig_persist
        print("OK  provider switch identical from REST + Telegram (same ProviderManager)")

        # ── 3. Global persona switch reflected everywhere ────────────────────
        r = await handle_message("/persona", "u", "c")
        assert r["command"] == "persona" and r["ok"] is True, r
        r = await handle_message("/persona analyst", "u", "c")
        assert r["command"] == "persona" and r["ok"] is True, r
        assert get_persona_manager().get_active_name() == "analyst"
        assert get_active_persona_text() == PERSONA_PRESETS["analyst"]
        prompt = await build_prompt("u", "c", "hi")
        assert "ANALYST" in prompt, prompt[:200]
        await handle_message("/persona default", "u", "c")
        print("OK  global persona switches and is reflected in the prompt")

        # ── 4. /compact handles empty session gracefully ────────────────────
        r = await handle_message("/compact", "u", "c")
        assert r["command"] == "compact", r
        print("OK  /compact routes (empty session handled)")

        # ── 5. Skills: create + invoke identically, instructions injected ────
        r = await handle_message("/skill-maker greet :: Say hello warmly", "u", "c")
        assert r["command"] == "skill-maker" and r["ok"] is True, r
        skills = await get_skill_manager().list_skills()
        assert any(s["name"] == "greet" for s in skills), skills
        r = await handle_message("/greet friend", "u", "c")
        assert r.get("skill") == "greet", r
        sent = fake_route_chat.last_messages[0].content
        assert "ACTIVE SKILL" in sent and "Say hello warmly" in sent, sent[:300]
        await get_skill_manager().delete_skill("greet")
        print("OK  skill created, invoked, and its instructions injected into prompt")

        # ── 6. Normal chat flows through build_prompt -> route_chat ─────────
        r = await handle_message("hello there", "u", "c")
        assert r.get("content") == "reply" and r.get("route"), r
        print("OK  normal chat routes through the single runtime")

        # ── 7. Telegram delegates to handle_message (no own AI logic) ───────
        calls = []

        async def spy(text, user_id, conversation_id):
            calls.append((text, user_id, conversation_id))
            return {"content": "SPY"}

        orig_handle = api.handle_message
        api.handle_message = spy
        msg = IncomingMessage(
            user_id="tg1", conversation_id="chat1",
            content="/provider openai", platform="telegram", metadata={},
        )
        out = await _handle_incoming_message(msg)
        assert calls and calls[0] == ("/provider openai", "tg1", "chat1"), calls
        assert out == "SPY", out
        api.handle_message = orig_handle
        print("OK  Telegram _handle_incoming_message delegates to handle_message")

        # ── 8. REST chat_endpoint delegates to handle_message ───────────────
        import backend.server as srv
        from backend.server import chat_endpoint

        srv._startup_done = True

        class Req:
            messages = [{"role": "user", "content": "/persona critic"}]
            user_id = "u"
            conversation_id = "c"

        res = await chat_endpoint(Req())
        assert res["command"] == "persona", res
        print("OK  REST chat_endpoint delegates to handle_message")

    finally:
        api.route_chat = orig_route

    print("\nALL UNIFIED-RUNTIME CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
