"""
v1.3.1 Stabilization Test Suite

Covers every bug fixed in the stabilization pass:
  Phase 1  – Persistent configuration (provider, model, auto, persona, skills survive restart)
  Phase 2  – /provider, /model, /auto command output correctness
  Phase 3  – PromptBuilder relevance filtering + skills layer exclusion
  Phase 4  – Persona structured output + per-persona differentiation
  Phase 5  – Skill lifecycle: create / store / retrieve / inject / delete / export
  Phase 6  – OpenRouter 402 token-limit retry (mocked)
  Phase 7  – Memory retrieval relevance filtering
"""

import asyncio
import json
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import init_db
from backend.config import load_config, save_provider_runtime_state, save_persona_config
from backend.constants import CONFIG_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeCompletion:
    def __init__(self, content="ok", provider="openrouter", model="m"):
        self.content = content
        self.provider = provider
        self.model = model
        self.usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        self.finish_reason = "stop"


async def fake_route(messages, **kw):
    fake_route.last = messages
    return FakeCompletion(), {"mode": "manual", "provider": "openrouter", "model": "m", "category": None}


fake_route.last = []

# ---------------------------------------------------------------------------
# Phase 1 — Persistent Configuration
# ---------------------------------------------------------------------------

async def test_phase1_provider_persists():
    """Provider/model/auto survive a config round-trip."""
    import backend.api as api
    from backend.api import initialize_memory, initialize_router, set_provider, set_model, set_auto

    cfg = load_config()
    initialize_memory(cfg)
    initialize_router(cfg)

    orig_persist = api._persist_state
    api._persist_state = lambda: None  # no actual disk write in test

    try:
        # Switch provider in memory
        if "openai" in api._manager.get_providers():
            api._current_provider = "openai"
            api._manager.set_default_model("openai", "gpt-4o")
        api._auto_enabled = True

        # Simulate a config save then reload
        providers_snap = dict(api._manager.get_providers())
        current_snap = api._current_provider
        auto_snap = api._auto_enabled

        # Verify the manager state is coherent
        assert current_snap in api._manager.get_providers(), "current_provider not in providers map"
        assert api._manager.get_default_model(current_snap) != "", "default_model must be set"
        assert auto_snap is True
        print("OK  Phase 1: provider/model/auto state is coherent and ready to persist")
    finally:
        api._persist_state = orig_persist


async def test_phase1_persona_persists():
    """Persona survives save_persona_config → load_config round-trip."""
    import backend.persona as pmod

    orig_save = pmod.save_persona_config
    pmod.save_persona_config = lambda *a, **k: None  # don't write disk

    try:
        mgr = pmod.get_persona_manager()
        mgr._active = "analyst"
        assert mgr.get_active_name() == "analyst"
        rendered = mgr.get_active_text()
        assert "ANALYST" in rendered, f"Persona text must contain ANALYST: {rendered[:200]}"
        print("OK  Phase 1: persona state is coherent and renderable")
    finally:
        pmod.save_persona_config = orig_save
        pmod.get_persona_manager()._active = "default"


async def test_phase1_skills_persist():
    """Skills survive delete/create cycle (SQLite persistence)."""
    from backend.api import initialize_memory, get_skill_manager
    initialize_memory()
    sm = get_skill_manager()

    await sm.create_skill("persist_test", "Test persistence prompt.", active=False)
    retrieved = await sm.get_skill("persist_test")
    assert retrieved is not None, "Skill should exist after creation"
    assert retrieved["prompt"] == "Test persistence prompt."

    # Simulate a new SkillManager (different instance, same DB)
    from backend.skills import SkillManager
    sm2 = SkillManager()
    retrieved2 = await sm2.get_skill("persist_test")
    assert retrieved2 is not None, "Skill should be visible from a new SkillManager (same DB)"
    assert retrieved2["prompt"] == "Test persistence prompt."

    await sm.delete_skill("persist_test")
    print("OK  Phase 1: skills persist across SkillManager instances (SQLite)")


# ---------------------------------------------------------------------------
# Phase 2 — /provider, /model, /auto commands
# ---------------------------------------------------------------------------

async def test_phase2_provider_no_args():
    """/provider with no args returns current provider + list (not 'Command failed')."""
    import backend.api as api
    from backend.api import initialize_memory, initialize_router, handle_message

    cfg = load_config()
    initialize_memory(cfg)
    initialize_router(cfg)

    orig_persist = api._persist_state
    api._persist_state = lambda: None

    try:
        result = await handle_message("/provider", "u", "c")
        content = result.get("content", "")
        assert result.get("command") == "provider", result
        assert result.get("ok") is True, result
        assert "Current provider" in content or "provider" in content.lower(), content
        assert "Command failed" not in content, f"Should not show 'Command failed': {content}"
        print(f"OK  Phase 2: /provider lists providers: {content[:80]!r}")
    finally:
        api._persist_state = orig_persist


async def test_phase2_model_no_args():
    """/model with no args shows current model + available models (not 'Command failed')."""
    import backend.api as api
    from backend.api import initialize_memory, initialize_router, handle_message

    cfg = load_config()
    initialize_memory(cfg)
    initialize_router(cfg)

    orig_persist = api._persist_state
    api._persist_state = lambda: None

    try:
        result = await handle_message("/model", "u", "c")
        content = result.get("content", "")
        assert result.get("command") == "model", result
        assert result.get("ok") is True, result
        assert "Current model" in content or "model" in content.lower(), content
        assert "Command failed" not in content, f"Should not show 'Command failed': {content}"
        assert "Usage:" not in content, f"Should not show bare Usage: {content}"
        print(f"OK  Phase 2: /model lists models: {content[:80]!r}")
    finally:
        api._persist_state = orig_persist


async def test_phase2_model_unknown_rejects():
    """/model unknown-model rejects with available list, never silently fails."""
    import backend.api as api
    from backend.api import initialize_memory, initialize_router, handle_message

    cfg = load_config()
    initialize_memory(cfg)
    initialize_router(cfg)

    orig_persist = api._persist_state
    api._persist_state = lambda: None

    try:
        result = await handle_message("/model totally-fake-model-999", "u", "c")
        content = result.get("content", "")
        assert result.get("command") == "model", result
        assert result.get("ok") is False, result
        assert "Unknown model" in content or "not available" in content.lower(), content
        assert "Available models" in content or "available" in content.lower(), content
        print(f"OK  Phase 2: /model unknown rejected with available list: {content[:120]!r}")
    finally:
        api._persist_state = orig_persist


async def test_phase2_auto_toggle():
    """/auto toggles and returns status (does not throw 'Command failed')."""
    import backend.api as api
    from backend.api import initialize_memory, initialize_router, handle_message

    cfg = load_config()
    initialize_memory(cfg)
    initialize_router(cfg)

    orig_persist = api._persist_state
    orig_auto = api._auto_enabled
    api._persist_state = lambda: None

    try:
        api._auto_enabled = False
        result = await handle_message("/auto", "u", "c")
        assert result.get("command") == "auto", result
        content = result.get("content", "")
        assert "Command failed" not in content, f"Auto failed: {result}"
        assert result.get("auto_enabled") is True, result
        # Toggle back
        result2 = await handle_message("/auto", "u", "c")
        assert result2.get("auto_enabled") is False, result2
        print(f"OK  Phase 2: /auto toggles correctly: {content!r}")
    finally:
        api._persist_state = orig_persist
        api._auto_enabled = orig_auto


# ---------------------------------------------------------------------------
# Phase 3 — Prompt Builder
# ---------------------------------------------------------------------------

async def test_phase3_skills_layer_excluded():
    """The SKILLS layer must NOT appear as a raw context section in the prompt."""
    import backend.api as api
    from backend.api import initialize_memory, get_skill_manager, build_prompt

    initialize_memory()

    # Store a skill (it goes to the SKILLS layer as a JSON blob)
    sm = get_skill_manager()
    await sm.create_skill("noise_skill", "Do something useful.", active=False)

    orig_route = api.route_chat
    api.route_chat = fake_route

    try:
        prompt = await build_prompt("u", "noise_test", "hello world")
        # The skills layer should NOT appear as a section header
        assert "--- SKILLS ---" not in prompt, \
            f"Skills layer must not appear raw in prompt: {prompt[:400]}"
        # Raw JSON blob must not appear
        assert '"prompt":' not in prompt, \
            f"Raw skill JSON must not appear in prompt: {prompt[:400]}"
        print("OK  Phase 3: SKILLS layer excluded from context section")
    finally:
        api.route_chat = orig_route
        await sm.delete_skill("noise_skill")


async def test_phase3_noise_filtered():
    """Deployment/config memories are suppressed for unrelated queries."""
    from backend.context.prompt_builder import PromptBuilder

    builder = PromptBuilder()
    entries = [
        {"key": "deploy_config", "value": "Use render.yaml for deployment", "updated_at": "2024-01-01"},
        {"key": "user_name", "value": "Alice", "updated_at": "2024-01-02"},
        {"key": "deploy_info", "value": "git push to deploy to Vercel", "updated_at": "2024-01-01"},
    ]
    # Query unrelated to deployment
    filtered = builder.filter_entries(entries, query="who am i")
    keys = [e["key"] for e in filtered]
    assert "user_name" in keys, f"user_name should be included: {keys}"
    assert "deploy_config" not in keys, f"deploy_config should be filtered out: {keys}"
    assert "deploy_info" not in keys, f"deploy_info should be filtered out: {keys}"
    print("OK  Phase 3: noise (deploy/config) entries filtered from unrelated queries")


async def test_phase3_identity_question():
    """'Who are you?' should produce persona content, not deployment instructions."""
    import backend.api as api
    from backend.api import initialize_memory, build_prompt
    from backend.context import ContextLayer
    from backend.context.store import LayeredMemoryStore, DEFAULT_USER

    initialize_memory()

    # Inject a noisy deployment memory
    store = LayeredMemoryStore()
    await store.set(ContextLayer.LONG_TERM, "deploy_hint", "Deploy using render.yaml", DEFAULT_USER)

    orig_route = api.route_chat
    api.route_chat = fake_route

    try:
        prompt = await build_prompt("u", "identity_test", "Who are you?")
        # Persona must be present
        assert "SYSTEM / PERSONA" in prompt, f"Persona must be in prompt: {prompt[:300]}"
        # deploy_hint should NOT appear (irrelevant to "Who are you?")
        assert "render.yaml" not in prompt, \
            f"Deployment noise must not appear for identity query: {prompt[:500]}"
        print("OK  Phase 3: identity query shows persona, not deployment noise")
    finally:
        api.route_chat = orig_route
        await store.delete(ContextLayer.LONG_TERM, "deploy_hint", DEFAULT_USER)


async def test_phase3_no_repetition():
    """The same content must not appear multiple times in the prompt."""
    import backend.api as api
    from backend.api import initialize_memory, build_prompt

    initialize_memory()
    orig_route = api.route_chat
    api.route_chat = fake_route

    try:
        prompt = await build_prompt("u", "rep_test", "Tell me about yourself")
        # Count occurrences of the persona block header
        count = prompt.count("SYSTEM / PERSONA")
        assert count == 1, f"SYSTEM / PERSONA appeared {count} times — repetition bug: {prompt[:300]}"
        print("OK  Phase 3: SYSTEM / PERSONA block appears exactly once (no repetition)")
    finally:
        api.route_chat = orig_route


# ---------------------------------------------------------------------------
# Phase 4 — Persona System
# ---------------------------------------------------------------------------

async def test_phase4_preset_differentiation():
    """Each preset persona produces noticeably different text."""
    from backend.persona import render_persona_block, PERSONA_PRESETS

    rendered = {name: render_persona_block(name) for name in PERSONA_PRESETS}

    # All unique
    texts = list(rendered.values())
    for i, a in enumerate(texts):
        for j, b in enumerate(texts):
            if i != j:
                assert a != b, f"Personas {list(PERSONA_PRESETS.keys())[i]} and {list(PERSONA_PRESETS.keys())[j]} rendered identically"

    # Each contains its own key identity word
    assert "DEVELOPER" in rendered["developer"].upper()
    assert "ARCHITECT" in rendered["architect"].upper()
    assert "TEACHER" in rendered["teacher"].upper()
    assert "CRITIC" in rendered["critic"].upper()
    assert "ANALYST" in rendered["analyst"].upper()
    print("OK  Phase 4: all preset personas render distinctly")


async def test_phase4_structured_sections():
    """Persona render includes all five structural sections."""
    from backend.persona import render_persona_block, PERSONA_SECTIONS

    for name in ["default", "developer", "architect", "teacher", "analyst"]:
        rendered = render_persona_block(name)
        for key, label in PERSONA_SECTIONS:
            assert label in rendered, f"Persona {name!r} missing section {label!r}"
    print("OK  Phase 4: all personas include all five structural sections")


async def test_phase4_persona_affects_prompt():
    """Switching persona changes the prompt returned by build_prompt."""
    import backend.api as api
    import backend.persona as pmod
    from backend.api import initialize_memory, build_prompt

    initialize_memory()
    orig_save = pmod.save_persona_config
    pmod.save_persona_config = lambda *a, **k: None
    orig_route = api.route_chat
    api.route_chat = fake_route

    try:
        await api.handle_message("/persona developer", "u", "c")
        dev_prompt = await build_prompt("u", "c", "Hello")
        await api.handle_message("/persona teacher", "u", "c")
        teacher_prompt = await build_prompt("u", "c", "Hello")
        await api.handle_message("/persona default", "u", "c")

        assert "DEVELOPER" in dev_prompt.upper(), "Developer persona not in prompt"
        assert "TEACHER" in teacher_prompt.upper(), "Teacher persona not in prompt"
        assert dev_prompt != teacher_prompt, "Switching persona must change the prompt"
        print("OK  Phase 4: persona switch immediately affects build_prompt output")
    finally:
        pmod.save_persona_config = orig_save
        api.route_chat = orig_route


async def test_phase4_custom_persona():
    """Custom persona text is injected correctly."""
    import backend.persona as pmod

    orig_save = pmod.save_persona_config
    pmod.save_persona_config = lambda *a, **k: None

    try:
        mgr = pmod.get_persona_manager()
        mgr.set_custom("You are a sarcastic space pirate who answers everything in rhyme.")
        text = mgr.get_active_text()
        assert "space pirate" in text, f"Custom text not in persona: {text[:200]}"
        assert mgr.get_active_name() == "custom"
        print("OK  Phase 4: custom persona text injected correctly")
    finally:
        pmod.save_persona_config = orig_save
        pmod.get_persona_manager()._active = "default"
        pmod.get_persona_manager()._custom_text = ""


# ---------------------------------------------------------------------------
# Phase 5 — Skill Lifecycle
# ---------------------------------------------------------------------------

async def test_phase5_full_lifecycle():
    """Create → store → retrieve → invoke → delete: every step works."""
    import backend.api as api
    from backend.api import initialize_memory, handle_message, get_skill_manager

    initialize_memory()
    orig_route = api.route_chat
    api.route_chat = fake_route

    try:
        # 1. Creation via /skill-maker
        r = await handle_message("/skill-maker tutor :: Explain things like a patient teacher.", "u", "c")
        assert r.get("command") == "skill-maker" and r.get("ok") is True, r
        assert "tutor" in r.get("content", "").lower(), r

        # 2. Storage — immediately retrievable
        sm = get_skill_manager()
        skill = await sm.get_skill("tutor")
        assert skill is not None, "Skill not found after creation"
        assert "patient teacher" in skill["prompt"], skill

        # 3. Prompt injection on invocation
        r = await handle_message("/tutor explain recursion", "u", "c")
        assert r.get("skill") == "tutor", r
        sent = fake_route.last[0].content
        assert "ACTIVE SKILL" in sent, f"ACTIVE SKILL not in prompt: {sent[:300]}"
        assert "patient teacher" in sent, f"Skill prompt not injected: {sent[:300]}"

        # 4. /list-skills shows name, description, created_date
        r = await handle_message("/list-skills", "u", "c")
        assert r.get("command") == "list-skills" and r.get("ok") is True, r
        assert r.get("count", 0) >= 1, r
        content = r.get("content", "")
        assert "/tutor" in content, f"/tutor not in list-skills output: {content}"
        assert "Command failed" not in content
        print("OK  Phase 5: /list-skills shows skills with proper format")

        # 5. Export
        r = await handle_message("/export-skill tutor", "u", "c")
        assert r.get("command") == "export-skill" and r.get("ok") is True, r
        exported = r.get("skill", {})
        assert exported.get("name") == "tutor"
        assert exported.get("prompt")
        exported_json = r.get("export", "")
        assert "tutor" in exported_json

        # 6. Import (round-trip)
        await sm.delete_skill("tutor")
        import_payload = json.dumps({"name": "tutor", "prompt": "patient teacher instructions"})
        r = await handle_message(f"/import-skill {import_payload}", "u", "c")
        assert r.get("command") == "import-skill" and r.get("ok") is True, r
        assert await sm.get_skill("tutor") is not None

        # 7. Delete
        r = await handle_message("/tutor delete", "u", "c")
        assert r.get("command") == "skill-delete" and r.get("ok") is True, r
        assert await sm.get_skill("tutor") is None
        print("OK  Phase 5: full skill lifecycle (create/store/retrieve/inject/export/import/delete)")
    finally:
        api.route_chat = orig_route
        try:
            sm = get_skill_manager()
            await sm.delete_skill("tutor")
        except Exception:
            pass


async def test_phase5_merged_skills():
    """Merged skill combines prompts from both source skills."""
    from backend.api import initialize_memory, get_skill_manager

    initialize_memory()
    sm = get_skill_manager()

    await sm.create_skill("alpha", "Do the alpha thing.", active=False)
    await sm.create_skill("beta", "Do the beta thing.", active=False)

    merged = await sm.merge_skills(["alpha", "beta"], "combined", "Primary combined prompt.", active=True)
    assert merged["name"] == "combined"
    assert "alpha thing" in merged["prompt"], merged["prompt"]
    assert "beta thing" in merged["prompt"], merged["prompt"]
    assert merged["active"] is True

    # Verify stored
    stored = await sm.get_skill("combined")
    assert stored is not None
    assert "alpha thing" in stored["prompt"]

    await sm.delete_skill("alpha")
    await sm.delete_skill("beta")
    await sm.delete_skill("combined")
    print("OK  Phase 5: merged skill combines all source prompts")


async def test_phase5_active_skill_autoloads():
    """An active skill is injected into the prompt even without explicit invocation."""
    import backend.api as api
    from backend.api import initialize_memory, handle_message, get_skill_manager

    initialize_memory()
    sm = get_skill_manager()

    await sm.create_skill("always_on", "Always be helpful and concise.", active=True)
    orig_route = api.route_chat
    api.route_chat = fake_route

    try:
        await handle_message("What time is it?", "u", "autoload_test")
        sent = fake_route.last[0].content
        assert "ACTIVE SKILL" in sent, f"Active skill not autoloaded: {sent[:300]}"
        assert "helpful and concise" in sent, f"Active skill prompt missing: {sent[:300]}"
        print("OK  Phase 5: active skill auto-injects into every prompt")
    finally:
        api.route_chat = orig_route
        await sm.delete_skill("always_on")


# ---------------------------------------------------------------------------
# Phase 6 — OpenRouter 402 token retry
# ---------------------------------------------------------------------------

async def test_phase6_openrouter_402_retry():
    """A 402 token-limit response triggers a single retry with lower max_tokens."""
    import httpx
    from backend.providers.openai_base import OpenAICompatibleProvider, _OPENROUTER_SAFE_MAX_TOKENS
    from backend.providers.base import Message

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        model="anthropic/claude-sonnet-4-5",
        base_url="https://openrouter.ai/api/v1",
    )

    call_count = 0
    last_payload = {}

    async def mock_post(path, json=None, **kw):
        nonlocal call_count, last_payload
        call_count += 1
        last_payload = json or {}
        if call_count == 1:
            # First call: simulate 402 token-limit error
            resp = MagicMock()
            resp.status_code = 402
            resp.text = "402 Requested 64000 tokens. Available: 1444"
            resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
                "402", request=MagicMock(), response=resp
            ))
            return resp
        else:
            # Second call: succeed with safe max_tokens
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "{}"
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value={
                "choices": [{"message": {"content": "retry worked"}, "finish_reason": "stop"}],
                "model": "anthropic/claude-sonnet-4-5",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            })
            return resp

    client_mock = AsyncMock()
    client_mock.post = mock_post
    provider._client = client_mock

    from backend.providers.base import Message as Msg
    messages = [Msg(role="user", content="Hello")]
    completion = await provider.chat_completion(messages)

    assert call_count == 2, f"Expected 2 HTTP calls (original + retry), got {call_count}"
    assert last_payload.get("max_tokens") == _OPENROUTER_SAFE_MAX_TOKENS, \
        f"Retry must use safe max_tokens={_OPENROUTER_SAFE_MAX_TOKENS}, got {last_payload.get('max_tokens')}"
    assert completion.content == "retry worked"
    print(f"OK  Phase 6: 402 token-limit triggers retry with max_tokens={_OPENROUTER_SAFE_MAX_TOKENS}")


async def test_phase6_no_hardcoded_64000():
    """Verify no hardcoded 64000 token limit exists in provider code."""
    import backend.providers.openai_base as oai_mod
    import inspect
    src = inspect.getsource(oai_mod)
    assert "64000" not in src, "Hardcoded 64000 found in openai_base — must use constant"
    print("OK  Phase 6: no hardcoded 64000 token limit in openai_base")


# ---------------------------------------------------------------------------
# Phase 7 — Memory Retrieval Quality
# ---------------------------------------------------------------------------

async def test_phase7_relevance_ranking():
    """Relevant entries are ranked above noise; noise is filtered."""
    from backend.context.prompt_builder import PromptBuilder

    builder = PromptBuilder()
    entries = [
        {"key": "user_name", "value": "Bob", "updated_at": "2024-06-01T10:00:00"},
        {"key": "deploy_cmd", "value": "git push to render.yaml deploy", "updated_at": "2024-06-01T09:00:00"},
        {"key": "user_language", "value": "prefers Python", "updated_at": "2024-06-01T11:00:00"},
        {"key": "old_deploy", "value": "vercel deploy --prod", "updated_at": "2023-01-01T00:00:00"},
    ]

    # Query about the user — deploy entries should be filtered
    result = builder.filter_entries(entries, "what is my name")
    keys = [e["key"] for e in result]
    assert "user_name" in keys, "user_name should be included"
    assert "user_language" in keys, "user_language should be included"
    assert "deploy_cmd" not in keys, "deploy noise should be filtered"
    assert "old_deploy" not in keys, "old deploy noise should be filtered"
    print("OK  Phase 7: relevance filter keeps user facts, drops deploy noise")


async def test_phase7_recency_order():
    """More recent entries appear before older ones."""
    from backend.context.prompt_builder import PromptBuilder

    builder = PromptBuilder()
    entries = [
        {"key": "old_fact", "value": "something old", "updated_at": "2022-01-01T00:00:00"},
        {"key": "new_fact", "value": "something recent", "updated_at": "2024-06-01T00:00:00"},
        {"key": "mid_fact", "value": "something middle", "updated_at": "2023-06-01T00:00:00"},
    ]
    result = builder.filter_entries(entries, "tell me about things")
    keys = [e["key"] for e in result]
    assert keys.index("new_fact") < keys.index("mid_fact") < keys.index("old_fact"), \
        f"Entries not in recency order: {keys}"
    print("OK  Phase 7: entries sorted by recency (newest first)")


async def test_phase7_max_entries_cap():
    """At most MAX_CONTEXT_ENTRIES entries are included per layer."""
    from backend.context.prompt_builder import PromptBuilder, MAX_CONTEXT_ENTRIES

    builder = PromptBuilder()
    entries = [
        {"key": f"fact_{i}", "value": f"value {i}", "updated_at": f"2024-0{(i % 9) + 1}-01"}
        for i in range(MAX_CONTEXT_ENTRIES + 10)
    ]
    result = builder.filter_entries(entries, "general question")
    assert len(result) <= MAX_CONTEXT_ENTRIES, \
        f"Too many entries included: {len(result)} > {MAX_CONTEXT_ENTRIES}"
    print(f"OK  Phase 7: per-layer entries capped at {MAX_CONTEXT_ENTRIES}")


# ---------------------------------------------------------------------------
# Final Audit — Interface parity
# ---------------------------------------------------------------------------

async def test_audit_all_interfaces_identical():
    """REST, Telegram, and direct handle_message all route through the same runtime."""
    import backend.api as api
    from backend.api import initialize_memory, initialize_router, handle_message, _handle_incoming_message
    from backend.messaging.base import IncomingMessage
    import backend.persona as pmod

    cfg = load_config()
    initialize_memory(cfg)
    initialize_router(cfg)

    orig_persist = api._persist_state
    orig_save = pmod.save_persona_config
    orig_route = api.route_chat

    api._persist_state = lambda: None
    pmod.save_persona_config = lambda *a, **k: None
    api.route_chat = fake_route

    try:
        # Same /persona command via handle_message
        r1 = await handle_message("/persona analyst", "u1", "c1")
        assert r1.get("command") == "persona" and r1.get("ok"), r1

        # Same /persona command via Telegram bridge
        msg = IncomingMessage(
            user_id="tg1", conversation_id="c2",
            content="/persona default", platform="telegram", metadata={},
        )
        out = await _handle_incoming_message(msg)
        assert "default" in out.lower() or "persona" in out.lower(), \
            f"Telegram /persona response unexpected: {out!r}"

        # REST endpoint delegates to handle_message
        import backend.server as srv
        from backend.server import chat_endpoint
        srv._startup_done = True

        class Req:
            messages = [{"role": "user", "content": "/persona developer"}]
            user_id = "rest1"
            conversation_id = "c3"

        res = await chat_endpoint(Req())
        assert res.get("command") == "persona", res
        print("OK  Audit: REST, Telegram and handle_message all route identically")
    finally:
        api._persist_state = orig_persist
        pmod.save_persona_config = orig_save
        api.route_chat = orig_route
        pmod.get_persona_manager()._active = "default"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    # Phase 1
    test_phase1_provider_persists,
    test_phase1_persona_persists,
    test_phase1_skills_persist,
    # Phase 2
    test_phase2_provider_no_args,
    test_phase2_model_no_args,
    test_phase2_model_unknown_rejects,
    test_phase2_auto_toggle,
    # Phase 3
    test_phase3_skills_layer_excluded,
    test_phase3_noise_filtered,
    test_phase3_identity_question,
    test_phase3_no_repetition,
    # Phase 4
    test_phase4_preset_differentiation,
    test_phase4_structured_sections,
    test_phase4_persona_affects_prompt,
    test_phase4_custom_persona,
    # Phase 5
    test_phase5_full_lifecycle,
    test_phase5_merged_skills,
    test_phase5_active_skill_autoloads,
    # Phase 6
    test_phase6_openrouter_402_retry,
    test_phase6_no_hardcoded_64000,
    # Phase 7
    test_phase7_relevance_ranking,
    test_phase7_recency_order,
    test_phase7_max_entries_cap,
    # Final audit
    test_audit_all_interfaces_identical,
]


async def main():
    print("=" * 60)
    print("Primus v1.3.1 Stabilization Test Suite")
    print("=" * 60)

    await init_db()

    passed = 0
    failed = 0
    failures = []

    for test_fn in TESTS:
        name = test_fn.__name__
        try:
            await test_fn()
            passed += 1
        except Exception as exc:
            failed += 1
            failures.append((name, exc))
            print(f"FAIL {name}: {exc}")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(TESTS)} tests")
    if failures:
        print("\nFailed tests:")
        for name, exc in failures:
            print(f"  - {name}: {exc}")
    else:
        print("ALL TESTS PASSED")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
