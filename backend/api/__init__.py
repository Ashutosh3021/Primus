"""
Internal API module for Primus backend.

Initialization functions follow the three-state module lifecycle:

  DISABLED              – module not enabled in config.
  WAITING_FOR_CONFIG    – enabled but required secret is missing.
  RUNNING               – enabled, secret present, fully initialised.

Only SecretNotFoundError transitions a module to WAITING_FOR_CONFIG.
Every other unexpected exception is still re-raised so it is visible in logs
and diagnostics.
"""

import json

from backend.config import Config, save_provider_runtime_state
from backend.providers.base import Message, ChatCompletion
from backend.providers.manager import ProviderManager
from backend.router import AIRouter
from backend.router.auto_router import AutoRouter, TASK_CATEGORIES
from backend.secrets import get_secret
from backend.exceptions import ConfigInvalidError, SecretNotFoundError
from backend.lifecycle import get_module_registry, ModuleState
from backend.logger import get_errors_logger
from backend.db import (
    init_db,
    MemoryStore,
    ConversationStore,
    MemoryEntry,
    ConversationMessage,
    MemoryLayer,
    Job,
    JobStore,
    CronSchedule,
    CronStore,
)
from backend.context import ContextEngine, ContextLayer, DEFAULT_USER
from backend.persona import (
    get_persona_manager,
    get_active_persona_text,
    initialize_persona,
    PERSONA_PRESETS,
)
from backend.skills import (
    SkillManager, get_skill_manager, initialize_skills, _normalise_name,
)
from backend.tools import ToolManager
from backend.messaging import BaseMessaging, IncomingMessage, MESSAGING_PLATFORMS
from backend.jobs import JobManager
from backend.context_engine import NotificationEngine, Scheduler
from backend.desktop import DesktopConnector, DesktopCapabilities
from backend.health import get_health_checker
from backend.metrics import get_metrics_registry
from backend.diagnostics import get_diagnostics_manager
from backend.recovery import get_recovery_manager

# Import desktop tools to register them
import backend.desktop.tools  # noqa: F401

logger = get_errors_logger(__name__)

# ── Singleton instances ───────────────────────────────────────────────────────
_router: AIRouter | None = None
_memory_store: MemoryStore | None = None
_conversation_store: ConversationStore | None = None
_context_engine: ContextEngine | None = None
_tool_manager: ToolManager | None = None
_messaging_platforms: dict = {}
_job_manager: JobManager | None = None
_notification_engine: NotificationEngine | None = None
_scheduler: Scheduler | None = None
_desktop_connector: DesktopConnector | None = None

# ── Multi-Provider + Multi-Model state (v1.3.0) ──
# The full provider map (name -> {enabled, secret_ref, default_model}).
_providers: dict = {}
# The currently-selected provider (used by /api/chat and messaging).
_current_provider: str | None = None
# Auto-routing flag.
_auto_enabled: bool = False
# Live authority over the provider map.
_manager: ProviderManager | None = None

_registry = get_module_registry()


# ── Router ───────────────────────────────────────────────────────────────────

def initialize_router(config: Config) -> None:
    """
    Initialise the AI router and the multi-provider state.

    Multi-provider state:
      * _providers / _current_provider / _auto_enabled are loaded from the
        config (which already migrated legacy configs into the map).
      * _manager is the live ProviderManager built from that map.

    Active router (for /api/chat & messaging when Auto Mode is off):
      secret present  → RUNNING
      secret missing  → WAITING_FOR_CONFIG (startup continues silently)
      other error     → WAITING_FOR_CONFIG + ERROR log (keyring I/O failure etc.)
    """
    global _router, _providers, _current_provider, _auto_enabled, _manager

    # ── Multi-provider map ──
    _providers = dict(config.providers or {})
    _current_provider = config.current_provider or (
        _providers and next(iter(_providers))
    )
    _auto_enabled = bool(config.auto_enabled)
    _manager = ProviderManager(_providers, get_secret)

    # ── Active router for the current provider ──
    if not _current_provider or _current_provider not in _manager.get_providers():
        _current_provider = _manager.get_providers() and next(
            iter(_manager.get_providers())
        )
    cur_cfg = _providers.get(_current_provider, {})
    try:
        api_key = get_secret(cur_cfg.get("secret_ref"))
        _router = AIRouter(_current_provider, api_key, cur_cfg.get("default_model"))
        _registry.set_running("router")
        logger.info(
            f"AI router initialised | provider={_current_provider} "
            f"model={cur_cfg.get('default_model')} | "
            f"auto_enabled={_auto_enabled} | "
            f"configured_providers={_manager.configured_providers()}"
        )
    except SecretNotFoundError:
        # Expected on first deploy or before Wizard is run — not an error.
        _router = None
        _registry.set_waiting("router", cur_cfg.get("secret_ref"))
        logger.info(
            f"AI router waiting for configuration | "
            f"secret_ref={cur_cfg.get('secret_ref')!r} not yet stored — "
            "run the Wizard to activate"
        )
    except ConfigInvalidError as exc:
        # Unknown provider name — this IS a real config error.
        _router = None
        _registry.set_waiting("router", cur_cfg.get("secret_ref"))
        logger.error(
            f"AI router config error | provider={_current_provider!r} | {exc}"
        )
    except Exception as exc:
        # Unexpected keyring / I/O failure — log as error but don't crash.
        _router = None
        _registry.set_waiting("router", cur_cfg.get("secret_ref"))
        logger.error(
            f"AI router failed to initialise (unexpected error) | "
            f"secret_ref={cur_cfg.get('secret_ref')!r} | {exc}",
            exc_info=True,
        )


# ── Memory ───────────────────────────────────────────────────────────────────

def initialize_memory(config: "Config | None" = None) -> None:
    """Initialise memory stores (no secrets required; always RUNNING)."""
    global _memory_store, _conversation_store, _context_engine
    _memory_store = MemoryStore()
    _conversation_store = ConversationStore()
    _context_engine = ContextEngine()
    # Apply Context Engine budget settings from config (if present).
    if config is not None and getattr(config, "context", None) is not None:
        _context_engine.set_max_tokens(int(config.context.max_tokens))
        _context_engine.set_prune_threshold(float(config.context.prune_threshold))
    # Global persona + skills live in the same core runtime as memory.
    initialize_persona(config)
    initialize_skills()
    _registry.set_running("memory")
    logger.info(
        "Context Engine initialised | "
        f"max_tokens={_context_engine.budget.max_tokens} "
        f"prune_threshold={_context_engine.budget.prune_threshold}"
    )


# ── Tools ────────────────────────────────────────────────────────────────────

def initialize_tools(config: Config) -> None:
    """Initialise tool manager (no secrets required; always RUNNING)."""
    global _tool_manager
    _tool_manager = ToolManager({
        "web_search": config.tools.web_search,
        "browser": config.tools.browser,
        "terminal": config.tools.terminal,
        "filesystem": config.tools.terminal,
        "python": config.tools.terminal,
        "git": config.tools.terminal,
        "ollama": config.tools.terminal,
        "docker": config.tools.terminal,
    })
    _registry.set_running("tools")
    logger.info("Tool system initialised")


# ── Messaging ────────────────────────────────────────────────────────────────

def initialize_messaging(config: Config) -> None:
    """
    Initialise every configured messaging platform.

    Each platform is evaluated independently:
      not enabled          → DISABLED  (silent — no log noise)
      enabled, no secret   → WAITING_FOR_CONFIG  (info log)
      enabled, secret ok   → RUNNING
    """
    global _messaging_platforms
    _messaging_platforms = {}

    logger.info(
        f"[TG_INIT] initialize_messaging | "
        f"platforms_in_registry={list(MESSAGING_PLATFORMS.keys())}"
    )

    for name, cls in MESSAGING_PLATFORMS.items():
        platform_config: dict = dict(getattr(config.messaging, name, {}) or {})

        if not platform_config.get("enabled", False):
            _registry.set_disabled(name)
            # Disabled platforms are the normal case — log at DEBUG level only
            logger.info(f"[TG_INIT] {name} → DISABLED (not enabled in config)")
            continue

        logger.info(
            f"[TG_INIT] Evaluating platform={name} | "
            f"has_secret_ref={'secret_ref' in platform_config}"
        )

        secret_ref: str | None = platform_config.get("secret_ref")
        if secret_ref:
            try:
                token = get_secret(secret_ref)
                platform_config["bot_token"] = token
                logger.info(
                    f"[TG_INIT] {name} — secret resolved | "
                    f"secret_ref={secret_ref}"
                )
            except SecretNotFoundError:
                _registry.set_waiting(name, secret_ref)
                logger.info(
                    f"[TG_INIT] {name} → WAITING_FOR_CONFIG | "
                    f"secret_ref={secret_ref!r} not yet stored"
                )
                continue
            except Exception as exc:
                # Unexpected keyring / I/O failure.
                _registry.set_waiting(name, secret_ref)
                logger.error(
                    f"[TG_INIT] {name} → WAITING_FOR_CONFIG | "
                    f"Unexpected error reading secret {secret_ref!r}: {exc}",
                    exc_info=True,
                )
                continue
        else:
            logger.info(
                f"[TG_INIT] {name} — no secret_ref, "
                "using bot_token directly from platform_config"
            )

        try:
            platform = cls(platform_config)
            platform.set_message_handler(_handle_incoming_message)
            _messaging_platforms[name] = platform
            _registry.set_running(name)
            logger.info(f"[TG_INIT] {name} → RUNNING")
        except Exception:
            raise


# ── Jobs ─────────────────────────────────────────────────────────────────────

def initialize_jobs(config: Config) -> None:
    """Initialise job manager, notification engine, scheduler (no secrets)."""
    global _job_manager, _notification_engine, _scheduler
    _job_manager = JobManager()
    _notification_engine = NotificationEngine({})
    _scheduler = Scheduler(_job_manager, _notification_engine)
    _registry.set_running("scheduler")
    logger.info("Job system initialised")


# ── Desktop ──────────────────────────────────────────────────────────────────

def initialize_desktop(config: Config) -> None:
    """Initialise desktop connector (no secrets required)."""
    global _desktop_connector
    desktop_cfg = getattr(config, "desktop", {})
    if not getattr(desktop_cfg, "enabled", True):
        _registry.set_disabled("desktop")
        return
    _desktop_connector = DesktopConnector(desktop_cfg)
    _registry.set_running("desktop")
    logger.info("Desktop system initialised")


# ── Internal message handler ──────────────────────────────────────────────────

async def _handle_incoming_message(msg: IncomingMessage) -> str:
    """
    Bridge between any messaging platform and the SINGLE shared runtime.

    Every message — command, skill invocation, or plain chat — is routed
    through ``handle_message`` so Telegram (and any future platform) behaves
    identically to the REST API and Dashboard.  This module owns no AI logic
    of its own; it only forwards to the core dispatcher and returns the text.
    """
    _metrics = get_metrics_registry()
    _metrics.increment("telegram.messages_received", {"platform": msg.platform})

    logger.info(
        f"[TG_AI] _handle_incoming_message | "
        f"platform={msg.platform} | "
        f"user_id={msg.user_id} | "
        f"conversation_id={msg.conversation_id} | "
        f"content_len={len(msg.content)} | "
        f"content_preview={msg.content[:80]!r}"
    )

    try:
        result = await handle_message(msg.content, msg.user_id, msg.conversation_id)
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        if isinstance(result, dict) and result.get("command"):
            # Commands (provider/model/persona/compact/skill-maker) are replies too.
            _metrics.increment("telegram.replies_sent", {"platform": msg.platform})
        elif result.get("error"):
            _metrics.increment("ai.calls_error", {"platform": msg.platform})
        else:
            _metrics.increment("telegram.replies_sent", {"platform": msg.platform})
        logger.info(
            f"[TG_AI] handle_message returned | "
            f"command={result.get('command') if isinstance(result, dict) else None} | "
            f"reply_len={len(content)}"
        )
        return content
    except Exception as exc:
        _metrics.increment("ai.calls_error", {"platform": msg.platform})
        logger.exception(
            f"[TG_ERROR] _handle_incoming_message failed | "
            f"platform={msg.platform} | "
            f"user_id={msg.user_id} | "
            f"error={exc}"
        )
        return f"Sorry, something went wrong: {str(exc)}"


# ── Chat ─────────────────────────────────────────────────────────────────────

async def chat(messages, temperature=0.7, max_tokens=None, auto=None, **kwargs):
    """
    Send a chat request through the active router (or Auto Mode).

    `auto=None` respects the persisted `_auto_enabled` flag; pass True/False to
    override for a single call.
    """
    completion, _info = await route_chat(
        messages, temperature=temperature, max_tokens=max_tokens, auto=auto, **kwargs
    )
    return completion


async def chat_stream(messages, temperature=0.7, max_tokens=None, **kwargs):
    """Stream a chat request through the active router."""
    if _router is None:
        state = _registry.get_state("router")
        if state == ModuleState.WAITING_FOR_CONFIG:
            missing = _registry.get_missing_secret("router")
            raise ConfigInvalidError(
                f"AI router is waiting for configuration. "
                f"Missing secret: {missing}"
            )
        raise ConfigInvalidError(
            "AI router not initialised. Complete the Wizard first."
        )
    async for chunk in _router.chat_stream(messages, temperature, max_tokens, **kwargs):
        yield chunk


# ─────────────────────────────────────────────────────────────────────────────
# PART X – Multi-Provider + Multi-Model control (v1.3.0)
# ─────────────────────────────────────────────────────────────────────────────

def _persist_state() -> None:
    """Write the current multi-provider state to config.json (atomic)."""
    if _manager is None:
        return
    save_provider_runtime_state(
        _manager.get_providers(),
        _current_provider,
        _auto_enabled,
    )


def set_provider(name: str) -> dict:
    """
    Permanently switch the active provider (command: /provider <name>).

    Restores that provider's own stored default_model automatically.  Persists
    to config.json so the choice survives restart.  Re-initialises the active
    router for the new provider/model.
    """
    global _current_provider, _router
    name = (name or "").strip().lower()
    if _manager is None:
        raise ConfigInvalidError("Provider manager not initialised.")
    if name not in _manager.get_providers():
        raise ConfigInvalidError(
            f"Unknown provider: {name}. "
            f"Available providers: {list(_manager.get_providers().keys())}"
        )

    # Activate the provider and restore its stored default model.
    _current_provider = name
    _manager.set_enabled(name, True)  # selecting a provider implies intent to use it

    cur_cfg = _manager.get_provider_config(name)
    model = cur_cfg.get("default_model") or _manager.get_default_model(name)
    _manager.set_default_model(name, model)

    # Re-initialise the active router for the new selection.
    try:
        api_key = get_secret(cur_cfg.get("secret_ref"))
        _router = AIRouter(name, api_key, model)
        _registry.set_running("router")
    except SecretNotFoundError:
        _router = None
        _registry.set_waiting("router", cur_cfg.get("secret_ref"))
    except ConfigInvalidError:
        _router = None
        _registry.set_waiting("router", cur_cfg.get("secret_ref"))

    _persist_state()
    logger.info(f"Active provider switched → {name} (model={model})")
    return {
        "provider": name,
        "model": model,
        "auto_enabled": _auto_enabled,
        "configured": _manager.is_configured(name),
    }


def set_model(model: str) -> dict:
    """
    Change only the CURRENT provider's default model (command: /model <model>).

    Validation is strict: if the model is NOT in the provider's known catalog
    we DO NOT guess, fuzzy-match, or silently switch.  We return an explicit
    error listing the available models instead.
    """
    global _router
    model = (model or "").strip()
    if _manager is None or not _current_provider:
        return {"ok": False, "error": "No provider selected."}
    name = _current_provider

    if not _manager.is_model_available(name, model):
        available = _manager.available_models(name)
        return {
            "ok": False,
            "provider": name,
            "error": f"Model not available for provider {name}",
            "available_models": available,
        }

    # Apply + persist.
    _manager.set_default_model(name, model)
    cur_cfg = _manager.get_provider_config(name)
    try:
        api_key = get_secret(cur_cfg.get("secret_ref"))
        _router = AIRouter(name, api_key, model)
        _registry.set_running("router")
    except Exception:
        _router = None
    _persist_state()
    logger.info(f"Model changed → {name} :: {model}")
    return {
        "ok": True,
        "provider": name,
        "model": model,
        "auto_enabled": _auto_enabled,
    }


def set_auto(enabled: bool) -> dict:
    """
    Enable/disable Auto Mode (command: /auto toggles).

    Persists to config.json so the flag survives restart.
    """
    global _auto_enabled
    _auto_enabled = bool(enabled)
    _persist_state()
    logger.info(f"Auto Mode → {_auto_enabled}")
    return {
        "auto_enabled": _auto_enabled,
        "provider": _current_provider,
        "model": _manager.get_default_model(_current_provider) if _manager else None,
    }


def handle_command(text: str) -> tuple[bool, dict]:
    """
    Parse a chat message for slash commands.

    Returns (matched, response_dict).  When matched is True, the caller should
    NOT forward the message to the AI — it was a command.

    Supported:
      /provider <name>   switch active provider (restores its model)
      /model <model>     change current provider's model (strict validation)
      /auto              toggle Auto Mode
    """
    if _manager is None:
        return (False, {})
    t = (text or "").strip()

    if t.startswith("/provider"):
        parts = t.split()
        if len(parts) < 2:
            return (True, {
                "command": "provider",
                "ok": False,
                "error": "Usage: /provider <name>",
                "available_providers": list(_manager.get_providers().keys()),
                "configured_providers": _manager.configured_providers(),
            })
        try:
            info = set_provider(parts[1])
            return (True, {"command": "provider", "ok": True, **info})
        except Exception as exc:
            return (True, {
                "command": "provider",
                "ok": False,
                "error": str(exc),
                "available_providers": list(_manager.get_providers().keys()),
            })

    if t.startswith("/model"):
        parts = t.split()
        if len(parts) < 2:
            return (True, {
                "command": "model",
                "ok": False,
                "error": "Usage: /model <model>",
                "available_models": _manager.available_models(_current_provider),
            })
        res = set_model(parts[1])
        res["command"] = "model"
        return (True, res)

    if t == "/auto":
        res = set_auto(not _auto_enabled)
        res["command"] = "auto"
        return (True, res)

    return (False, {})


def get_providers_info() -> dict:
    """
    Snapshot of every provider for the UI / GET /api/providers.

    Each entry reports whether it is enabled, configured (secret present),
    its stored default_model, its available models, and whether it is current.
    """
    if _manager is None:
        return {
            "current_provider": None,
            "auto_enabled": False,
            "providers": [],
        }
    providers = []
    for name in _manager.get_providers():
        cfg = _manager.get_provider_config(name) or {}
        providers.append({
            "name": name,
            "enabled": _manager.is_enabled(name),
            "configured": _manager.is_configured(name),
            "default_model": cfg.get("default_model") or _manager.get_default_model(name),
            "available_models": _manager.available_models(name),
            "is_current": name == _current_provider,
        })
    return {
        "current_provider": _current_provider,
        "auto_enabled": _auto_enabled,
        "providers": providers,
    }


def get_models_info() -> dict:
    """
    Model listing for GET /api/models.

    Returns the current provider + model, plus a per-provider map of
    default_model / available_models / configured flag.
    """
    if _manager is None:
        return {"current_provider": None, "current_model": None, "providers": {}}
    per_provider = {}
    for name in _manager.get_providers():
        cfg = _manager.get_provider_config(name) or {}
        per_provider[name] = {
            "default_model": cfg.get("default_model") or _manager.get_default_model(name),
            "available_models": _manager.available_models(name),
            "configured": _manager.is_configured(name),
        }
    return {
        "current_provider": _current_provider,
        "current_model": _manager.get_default_model(_current_provider),
        "providers": per_provider,
    }


async def route_chat(
    messages,
    temperature: float = 0.7,
    max_tokens=None,
    auto: bool | None = None,
    **kwargs,
) -> tuple[ChatCompletion, dict]:
    """
    Route a chat request, honouring Auto Mode.

    Returns (completion, route_info) where route_info describes how the
    request was routed (mode, provider, model, category).

      * auto=True  → classify + select across configured providers (with
                     automatic fallback).  If nothing is configured for the
                     classified category, falls back to the active router.
      * auto=False → use the active router (current provider + model).
    """
    use_auto = _auto_enabled if auto is None else bool(auto)

    if use_auto and _manager is not None:
        auto_router = AutoRouter(_manager, _current_provider)
        completion, info = await auto_router.route(
            messages, temperature=temperature, max_tokens=max_tokens, **kwargs
        )
        if completion is not None:
            return completion, info
        # No configured candidate → fall through to active router below.

    if _router is None:
        state = _registry.get_state("router")
        if state == ModuleState.WAITING_FOR_CONFIG:
            missing = _registry.get_missing_secret("router")
            raise ConfigInvalidError(
                f"AI router is waiting for configuration. "
                f"Missing secret: {missing}"
            )
        raise ConfigInvalidError(
            "AI router not initialised. Complete the Wizard first."
        )

    completion = await _router.chat(messages, temperature, max_tokens, **kwargs)
    return completion, {
        "mode": "manual",
        "category": None,
        "provider": _router.provider_name,
        "model": _router.provider.model,
    }


# ── Capabilities ──────────────────────────────────────────────────────────────

def get_capabilities() -> dict:
    """Return provider and desktop capabilities."""
    caps = {}
    if _router:
        caps["provider"] = _router.get_capabilities()
    if _desktop_connector:
        caps["desktop"] = _desktop_connector.capabilities
    return caps


# ── Memory helpers ────────────────────────────────────────────────────────────

async def add_memory(entry):
    if _memory_store is None:
        raise ConfigInvalidError("Memory not initialised.")
    return await _memory_store.add(entry)


async def get_memory(user_id, layer, key):
    if _memory_store is None:
        raise ConfigInvalidError("Memory not initialised.")
    return await _memory_store.get(user_id, layer, key)


async def get_all_memories(user_id, layer=None):
    if _memory_store is None:
        raise ConfigInvalidError("Memory not initialised.")
    return await _memory_store.get_all(user_id, layer)


async def delete_memory(user_id, layer, key):
    if _memory_store is None:
        raise ConfigInvalidError("Memory not initialised.")
    return await _memory_store.delete(user_id, layer, key)


async def build_prompt(user_id, conversation_id, query, skill_instructions=None):
    if _context_engine is None:
        raise ConfigInvalidError("Context engine not initialised.")
    return await _context_engine.build_prompt(
        user_id, conversation_id, query, skill_instructions=skill_instructions
    )


async def add_interaction(user_id, conversation_id, user_message, assistant_response):
    if _context_engine is None:
        raise ConfigInvalidError("Context engine not initialised.")
    await _context_engine.add_interaction(
        user_id, conversation_id, user_message, assistant_response
    )


# ── Context Engine (v1.3.0) ────────────────────────────────────────────────────

async def get_context_info(conversation_id: str = "default") -> dict:
    """
    Snapshot of the Context Engine budget + layer counts for GET /api/context.

    Returns max / current / remaining / percentage tokens, the prune
    threshold, per-layer entry counts, and the active-session message count.
    """
    if _context_engine is None:
        raise ConfigInvalidError("Context engine not initialised.")
    budget = await _context_engine.get_budget(conversation_id)
    layers = await _context_engine.count_by_layer()
    session_n = await _context_engine.active_session_count(conversation_id)
    info = budget.to_dict()
    info.update({
        "layers": layers,
        "active_session_messages": session_n,
        "conversation_id": conversation_id,
        "auto_pruned": _context_engine.last_pruned(conversation_id),
        "shared_memory": True,
    })
    return info


def handle_context_command(text: str) -> tuple[bool, dict]:
    """
    Parse chat messages for Context Engine slash commands.

    Returns (matched, response_dict).  When matched is True the caller should
    NOT forward the message to the AI — it was a command.

    Supported:
      /compact   hard-compact the active session into Compact Memory
    """
    if _context_engine is None:
        return (False, {})
    t = (text or "").strip()
    if t == "/compact":
        return (True, {"command": "compact"})
    return (False, {})


async def compact_context(conversation_id: str = "default", force: bool = False) -> dict:
    """
    Hard-compact the active session for `conversation_id`.

    Gathers the live conversation, summarises it (via the active provider when
    available, otherwise a deterministic extractive fallback), archives the
    summary into Compact Memory, updates the rolling Conversation Summary, and
    clears the active session.  Returns the summary plus a fresh budget snapshot.
    """
    if _context_engine is None:
        raise ConfigInvalidError("Context engine not initialised.")

    msgs = await _context_engine.get_active_session(conversation_id)
    if not msgs:
        info = await get_context_info(conversation_id)
        info.update({"ok": True, "compacted": False, "message": "Active session is empty."})
        return info

    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)
    summary = await _summarize_transcript(transcript)
    await _context_engine.apply_compaction(conversation_id, summary)

    info = await get_context_info(conversation_id)
    info.update({
        "ok": True,
        "compacted": True,
        "summary": summary,
        "archived_entries": await _context_engine.count_by_layer(),
    })
    return info


async def _summarize_transcript(transcript: str) -> str:
    """Summarise a transcript, using the LLM when possible, else fallback."""
    prompt = (
        "Summarise the following conversation. Preserve ALL key facts, user "
        "preferences, decisions, and open tasks. Be concise and factual. "
        "Do not invent information.\n\n" + transcript
    )
    try:
        completion, _info = await route_chat([Message(role="user", content=prompt)])
        if completion and getattr(completion, "content", None):
            return completion.content.strip()
    except Exception as exc:
        logger.warning(f"LLM compaction unavailable ({exc}); using extractive fallback")
    return _extractive_summary(transcript)


def _extractive_summary(transcript: str) -> str:
    """Deterministic fallback summary (no LLM required)."""
    lines = [ln for ln in transcript.splitlines() if ln.strip()]
    user_turns = [ln for ln in lines if ln.lower().startswith("user:")]
    assistant_turns = [ln for ln in lines if ln.lower().startswith("assistant:")]
    parts = [f"Conversation with {len(user_turns)} user turn(s)."]
    if user_turns:
        parts.append("User requests / topics:")
        for turn in user_turns[:25]:
            parts.append("  - " + turn[len("user:"):].strip()[:300])
    if assistant_turns:
        parts.append(
            f"Assistant provided {len(assistant_turns)} response(s); "
            "key points preserved in Compact Memory."
        )
    parts.append("[Summary generated by deterministic fallback — no LLM available.]")
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# PART Xb – Unified command + message dispatcher (the ONE runtime entry)
# ─────────────────────────────────────────────────────────────────────────────
#
# Every interface — Telegram, the Web Dashboard, the REST API, and any future
# client — funnels messages through `handle_message`.  This guarantees a single
# AI runtime: command parsing, persona switching, skill execution, prompt
# building, provider routing, and memory updates all live HERE, never in an
# interface.  No interface may own business logic.

def _command_content(cmd: dict) -> str:
    """Human-readable reply text for a multi-provider command result."""
    if not cmd.get("ok"):
        return cmd.get("error") or "Command failed."
    c = cmd.get("command")
    if c == "auto":
        return f"Auto {'enabled' if cmd.get('auto_enabled') else 'disabled'}"
    if c == "provider":
        return f"{c} OK → {cmd.get('provider')}" + (
            f" :: {cmd.get('model')}" if cmd.get("model") else ""
        )
    if c == "model":
        return f"{c} OK → {cmd.get('provider')} :: {cmd.get('model')}"
    return cmd.get("error") or "OK"


def _command_response(cmd: dict) -> dict:
    cmd = dict(cmd)
    cmd.setdefault("content", _command_content(cmd))
    return cmd


def _compact_response(info: dict) -> dict:
    """Shape a compact_context() result for any interface."""
    return {
        "command": "compact",
        "ok": info.get("ok"),
        "compacted": info.get("compacted"),
        "summary": info.get("summary"),
        "message": info.get("message"),
        "content": info.get("summary") or info.get("message") or "Compacted.",
        "context": {
            "max_tokens": info.get("max_tokens"),
            "current_tokens": info.get("current_tokens"),
            "remaining": info.get("remaining"),
            "percentage": info.get("percentage"),
        },
        "route": {"mode": "context", "provider": None, "model": None},
    }


def handle_persona_command(text: str) -> tuple[bool, dict]:
    """
    Parse and execute persona commands.

      /persona                  list presets + show active persona
      /persona <name>           switch active persona (a built-in preset)
      /persona custom <text>    set a custom persona and activate it (legacy form)
      /persona <custom prompt>  any non-preset text becomes the custom persona

    Returns (matched, response_dict).  When matched, the caller must NOT treat
    the message as a normal chat.
    """
    t = (text or "").strip()
    if not t.startswith("/persona"):
        return (False, {})
    parts = t.split(None, 1)
    mgr = get_persona_manager()

    if len(parts) < 2:
        info = mgr.list_personas()
        return (True, {
            "command": "persona",
            "ok": True,
            "active": info["active"],
            "presets": info["presets"],
            "custom_set": info["custom_set"],
            "content": (
                f"Active persona: {info['active']}. "
                f"Available: {', '.join(info['presets'])}"
            ),
        })

    arg = parts[1].strip()

    # Legacy form: "/persona custom <text>".
    if arg.lower().startswith("custom"):
        custom_text = arg[len("custom"):].strip()
        if not custom_text:
            return (True, {
                "command": "persona", "ok": False,
                "error": "Usage: /persona custom <your persona text>",
            })
        try:
            mgr.set_custom(custom_text)
        except Exception as exc:
            return (True, {"command": "persona", "ok": False, "error": str(exc)})
        preview = custom_text[:80] + ("…" if len(custom_text) > 80 else "")
        return (True, {
            "command": "persona", "ok": True, "active": "custom",
            "content": f"Persona set to custom: {preview}",
        })

    # Known preset → switch to it.
    if arg in PERSONA_PRESETS:
        try:
            mgr.set_active(arg)
        except Exception as exc:
            return (True, {
                "command": "persona", "ok": False, "error": str(exc),
                "presets": mgr.list_personas()["presets"],
            })
        return (True, {
            "command": "persona", "ok": True,
            "active": mgr.get_active_name(),
            "content": f"Persona switched → {mgr.get_active_name()}",
        })

    # Anything else → treat the whole remainder as a custom persona prompt.
    try:
        mgr.set_custom(arg)
    except Exception as exc:
        return (True, {"command": "persona", "ok": False, "error": str(exc)})
    preview = arg[:80] + ("…" if len(arg) > 80 else "")
    return (True, {
        "command": "persona", "ok": True, "active": "custom",
        "content": f"Persona set to custom: {preview}",
    })


# In-progress skill-maker wizard sessions, keyed by (user_id, conversation_id).
_skill_maker_sessions = {}


async def handle_skill_maker_command(
    text: str, user_id: str, conversation_id: str
) -> tuple[bool, dict]:
    """
    Parse and execute the skill-maker command.

      /skill-maker                         → start the conversational wizard
      /skill-maker <name> :: <prompt>     → one-shot create (legacy shortcut)
      /skill-maker <name> <prompt>        → one-shot create (single-token name)

    The conversational wizard walks the user through:
        name → prompt → merge? (Yes/No) → [targets] → save / merge + default.

    Returns (matched, response_dict).  When a wizard is started, the session is
    recorded so the next message is routed to ``handle_skill_maker_step``.
    """
    t = (text or "").strip()
    if not t.startswith("/skill-maker"):
        return (False, {})
    parts = t.split(None, 1)
    if len(parts) < 2:
        # Start the conversational wizard.
        _skill_maker_sessions[(user_id, conversation_id)] = {"state": "name"}
        return (True, {
            "command": "skill-maker", "ok": True, "wizard": True, "state": "name",
            "content": (
                "Skill Name? (reply with the skill's name, e.g. 'XYZ'. "
                "Send /cancel to abort.)"
            ),
        })
    body = parts[1].strip()
    if body.lower() == "cancel":
        _skill_maker_sessions.pop((user_id, conversation_id), None)
        return (True, {
            "command": "skill-maker", "ok": True, "wizard": False,
            "content": "Skill creation cancelled.",
        })
    # One-shot form (legacy shortcut) — create immediately.
    if "::" in body:
        name, instructions = body.split("::", 1)
        name, instructions = name.strip(), instructions.strip()
    else:
        idx = body.find(" ")
        if idx > 0:
            name, instructions = body[:idx].strip(), body[idx + 1:].strip()
        else:
            name, instructions = body.strip(), ""
    if not name:
        return (True, {
            "command": "skill-maker", "ok": False, "error": "Skill name required.",
        })
    try:
        sm = get_skill_manager()
        skill = await sm.create_skill(name, instructions, description=name)
    except Exception as exc:
        return (True, {"command": "skill-maker", "ok": False, "error": str(exc)})
    return (True, {
        "command": "skill-maker", "ok": True, "skill": skill,
        "content": f"Skill '/{skill['name']}' created. Invoke with /{skill['name']}.",
    })


async def handle_skill_maker_step(
    text: str, user_id: str, conversation_id: str
) -> dict:
    """Advance an in-progress skill-maker wizard based on the current state."""
    key = (user_id, conversation_id)
    sess = _skill_maker_sessions.get(key)
    if sess is None:
        return await handle_skill_maker_command(text, user_id, conversation_id)

    t = (text or "").strip()
    if t.lower() == "/cancel":
        _skill_maker_sessions.pop(key, None)
        return {"command": "skill-maker", "ok": True, "wizard": False,
                "content": "Skill creation cancelled."}

    state = sess.get("state")

    if state == "name":
        try:
            _normalise_name(t)
        except ValueError as exc:
            return {"command": "skill-maker", "ok": False, "wizard": True,
                    "state": "name", "content": f"{exc} Try again."}
        sess["name"] = t
        sess["state"] = "prompt"
        return {"command": "skill-maker", "ok": True, "wizard": True,
                "state": "prompt", "content": "Describe the skill."}

    if state == "prompt":
        sess["prompt"] = t
        sess["state"] = "merge"
        return {"command": "skill-maker", "ok": True, "wizard": True,
                "state": "merge",
                "content": "Merge with another skill? Reply 'Yes' or 'No'."}

    if state == "merge":
        if t.lower().startswith("y"):
            sess["state"] = "merge_targets"
            return {"command": "skill-maker", "ok": True, "wizard": True,
                    "state": "merge_targets",
                    "content": "Which skills? (comma-separated names, e.g. foo, bar)"}
        return await _finalize_skill(sess, key, merge_names=[])

    if state == "merge_targets":
        names = [n.strip() for n in t.split(",") if n.strip()]
        return await _finalize_skill(sess, key, merge_names=names)

    # Unknown state → reset.
    _skill_maker_sessions.pop(key, None)
    return {"command": "skill-maker", "ok": False,
            "content": "Skill wizard reset. Send /skill-maker to start again."}


async def _finalize_skill(sess: dict, key: tuple, merge_names: list) -> dict:
    """Create (and optionally merge) the skill, then close the wizard."""
    name = sess.get("name")
    prompt = sess.get("prompt", "")
    sm = get_skill_manager()
    _skill_maker_sessions.pop(key, None)
    try:
        if merge_names:
            skill = await sm.merge_skills(merge_names, name, prompt, active=True)
            content = (
                f"Merged '/{name}' with {', '.join(merge_names)} and set as "
                f"default (active). Invoke with /{name}."
            )
        else:
            skill = await sm.create_skill(name, prompt, active=False)
            content = f"Skill '/{name}' created. Invoke with /{name}."
    except Exception as exc:
        return {"command": "skill-maker", "ok": False, "error": str(exc)}
    return {"command": "skill-maker", "ok": True, "wizard": False,
            "skill": skill, "content": content}


async def handle_skill_management_command(text: str) -> tuple[bool, dict]:
    """
    Handle the skill *management* commands (non-invocation):

      /list-skills            list every stored skill
      /export-skill <name>    return the skill as JSON
      /import-skill <json>    create a skill from pasted JSON
      /<name> delete          delete a skill permanently

    Returns (matched, response_dict).  When not a management command, returns
    (False, {}).  Skill *invocation* (``/<name>``) is handled separately by
    ``match_skill_invocation``.
    """
    t = (text or "").strip()
    if not t.startswith("/"):
        return (False, {})

    if t == "/list-skills":
        return (True, {"command": "list-skills", "ok": True, "handled": True})

    sm = get_skill_manager()

    if t.startswith("/export-skill"):
        name = t[len("/export-skill"):].strip().lstrip("/")
        if not name:
            return (True, {"command": "export-skill", "ok": False,
                           "error": "Usage: /export-skill <name>"})
        try:
            skill = await sm.export_skill(name)
        except Exception as exc:
            return (True, {"command": "export-skill", "ok": False, "error": str(exc)})
        return (True, {
            "command": "export-skill", "ok": True, "name": name, "skill": skill,
            "export": json.dumps(skill, indent=2, ensure_ascii=False),
        })

    if t.startswith("/import-skill"):
        raw = t[len("/import-skill"):].strip()
        if not raw:
            return (True, {"command": "import-skill", "ok": False,
                           "error": "Usage: /import-skill <json>"})
        try:
            data = json.loads(raw)
        except Exception as exc:
            return (True, {"command": "import-skill", "ok": False,
                           "error": f"Invalid JSON: {exc}"})
        try:
            skill = await sm.import_skill(data)
        except Exception as exc:
            return (True, {"command": "import-skill", "ok": False, "error": str(exc)})
        return (True, {
            "command": "import-skill", "ok": True, "skill": skill,
            "content": f"Skill '/{skill['name']}' imported. Invoke with /{skill['name']}.",
        })

    # "/<name> delete" — must be checked before generic invocation.
    parts = t[1:].split(None, 1)
    if len(parts) == 2 and parts[1].strip().lower() == "delete":
        name = parts[0].strip()
        if await sm.get_skill(name) is None:
            return (True, {"command": "skill-delete", "ok": False,
                           "error": f"Skill not found: {name!r}"})
        removed = await sm.delete_skill(name)
        return (True, {
            "command": "skill-delete", "ok": bool(removed), "name": name,
            "content": f"Skill '/{name}' deleted permanently." if removed
            else f"Skill '/{name}' was not found.",
        })

    return (False, {})


async def match_skill_invocation(text: str):
    """Return the skill dict if `text` invokes an existing skill, else None."""
    sm = get_skill_manager()
    return await sm.match(text)


async def _combine_skill_prompts(invoked_name: str | None = None) -> str | None:
    """
    Build the combined skill-instructions block.

    Includes every *active* skill (so the Prompt Builder loads active skills
    automatically) plus, when invoking a specific skill, that skill's own
    prompt (skipping it if it is already active to avoid duplication).
    """
    sm = get_skill_manager()
    active = await sm.list_active()
    parts: list = []
    for s in active:
        if invoked_name and s.get("name") == invoked_name:
            continue
        p = (s.get("prompt") or "").strip()
        if p:
            parts.append(p)
    if invoked_name:
        sk = await sm.get_skill(invoked_name)
        if sk:
            p = (sk.get("prompt") or "").strip()
            if p:
                parts.append(p)
    return "\n\n".join(parts) if parts else None


async def run_chat(text: str, user_id: str, conversation_id: str) -> dict:
    """Normal chat path: build prompt → route → persist. Raises on failure."""
    _metrics = get_metrics_registry()
    # Active skills are loaded automatically by the Prompt Builder.
    skill_instructions = await _combine_skill_prompts()
    enriched_prompt = await build_prompt(
        user_id, conversation_id, text, skill_instructions=skill_instructions
    )
    messages = [Message(role="user", content=enriched_prompt)]

    import time as _time
    _t0 = _time.monotonic()
    completion, route_info = await route_chat(
        messages, temperature=0.7, max_tokens=None
    )
    _latency_ms = int((_time.monotonic() - _t0) * 1000)

    _provider = completion.provider or "unknown"
    _metrics.increment("ai.calls_total", {"provider": _provider})
    _metrics.increment("ai.calls_success", {"provider": _provider})
    _metrics.gauge("ai.last_latency_ms", _latency_ms)

    _usage = completion.usage or {}
    _input_tokens = _usage.get("prompt_tokens", _usage.get("input_tokens", 0)) or 0
    _output_tokens = _usage.get("completion_tokens", _usage.get("output_tokens", 0)) or 0
    _total_tokens = _usage.get("total_tokens", _input_tokens + _output_tokens) or 0
    if _total_tokens:
        _metrics.increment("ai.tokens_total", {"provider": _provider}, _total_tokens)
        _metrics.increment("ai.tokens_input", {"provider": _provider}, _input_tokens)
        _metrics.increment("ai.tokens_output", {"provider": _provider}, _output_tokens)

    await add_interaction(user_id, conversation_id, text, completion.content)
    return {
        "content": completion.content,
        "model": completion.model,
        "provider": completion.provider,
        "usage": completion.usage,
        "finish_reason": completion.finish_reason,
        "route": route_info,
    }


async def run_skill(skill: dict, text: str, user_id: str, conversation_id: str) -> dict:
    """Skill-invocation path: inject skill instructions, then route + persist."""
    _metrics = get_metrics_registry()
    # Active skills + the invoked skill's own prompt (de-duplicated).
    skill_instructions = await _combine_skill_prompts(skill.get("name"))
    enriched_prompt = await build_prompt(
        user_id, conversation_id, text, skill_instructions=skill_instructions
    )
    messages = [Message(role="user", content=enriched_prompt)]

    import time as _time
    _t0 = _time.monotonic()
    completion, route_info = await route_chat(
        messages, temperature=0.7, max_tokens=None
    )
    _latency_ms = int((_time.monotonic() - _t0) * 1000)

    _provider = completion.provider or "unknown"
    _metrics.increment("ai.calls_total", {"provider": _provider})
    _metrics.increment("ai.calls_success", {"provider": _provider})
    _metrics.gauge("ai.last_latency_ms", _latency_ms)

    _usage = completion.usage or {}
    _input_tokens = _usage.get("prompt_tokens", _usage.get("input_tokens", 0)) or 0
    _output_tokens = _usage.get("completion_tokens", _usage.get("output_tokens", 0)) or 0
    _total_tokens = _usage.get("total_tokens", _input_tokens + _output_tokens) or 0
    if _total_tokens:
        _metrics.increment("ai.tokens_total", {"provider": _provider}, _total_tokens)
        _metrics.increment("ai.tokens_input", {"provider": _provider}, _input_tokens)
        _metrics.increment("ai.tokens_output", {"provider": _provider}, _output_tokens)

    await add_interaction(user_id, conversation_id, text, completion.content)
    route_info = dict(route_info or {})
    route_info["mode"] = "skill"
    route_info["skill"] = skill.get("name")
    return {
        "content": completion.content,
        "model": completion.model,
        "provider": completion.provider,
        "usage": completion.usage,
        "finish_reason": completion.finish_reason,
        "skill": skill.get("name"),
        "route": route_info,
    }


async def handle_message(text: str, user_id: str, conversation_id: str) -> dict:
    """
    THE single runtime entry point for every interface.

    Resolution order (all live in core, never in an interface):
      1. multi-provider command      (/provider, /model, /auto)
      2. persona command             (/persona)
      3. context command             (/compact)
      4. skill-maker wizard step     (raw input while a /skill-maker is in progress)
      5. skill-maker command         (/skill-maker)
      6. skill management command    (/list-skills, /export-skill, /import-skill, /<name> delete)
      7. skill invocation            (/<name> where <name> is a stored skill)
      8. normal chat                 (build prompt → route → persist)

    Returns a dict that any interface can render: always contains ``content``;
    command results also carry ``command``/``ok``; chat/skill results carry
    ``model``/``provider``/``usage``/``route``.
    """
    # 1. Multi-provider commands.
    matched, cmd = handle_command(text)
    if matched:
        return _command_response(cmd)

    # 2. Persona command.
    matched, cmd = handle_persona_command(text)
    if matched:
        return cmd

    # 3. Context command (compact).
    cmatched, ccmd = handle_context_command(text)
    if cmatched and ccmd.get("command") == "compact":
        info = await compact_context(conversation_id)
        return _compact_response(info)

    # 4. In-progress skill-maker wizard (route raw input to the wizard).
    if (user_id, conversation_id) in _skill_maker_sessions:
        return await handle_skill_maker_step(text, user_id, conversation_id)

    # 5. Skill-maker command (/skill-maker … — may start a wizard).
    matched, cmd = await handle_skill_maker_command(text, user_id, conversation_id)
    if matched:
        return cmd

    # 6. Skill management commands (list / export / import / delete).
    matched, cmd = await handle_skill_management_command(text)
    if matched:
        if cmd.get("command") == "list-skills":
            skills = await get_skill_manager().list_skills()
            cmd["skills"] = skills
            cmd["count"] = len(skills)
        return cmd

    # 7. Skill invocation (any stored skill via /<name>).
    skill = await match_skill_invocation(text)
    if skill:
        return await run_skill(skill, text, user_id, conversation_id)

    # 8. Normal chat.
    return await run_chat(text, user_id, conversation_id)


# ── Lifecycle start / stop ────────────────────────────────────────────────────

async def start_messaging() -> None:
    for name, platform in _messaging_platforms.items():
        try:
            await platform.start()
        except Exception as exc:
            logger.error(f"Failed to start {name}: {exc}", exc_info=True)


async def stop_messaging() -> None:
    for name, platform in _messaging_platforms.items():
        try:
            await platform.stop()
        except Exception as exc:
            logger.error(f"Failed to stop {name}: {exc}", exc_info=True)


async def start_jobs() -> None:
    if _job_manager and _scheduler:
        await _job_manager.start()
        await _scheduler.start()


async def stop_jobs() -> None:
    if _job_manager and _scheduler:
        await _job_manager.stop()
        await _scheduler.stop()


async def start_desktop() -> None:
    if _desktop_connector:
        await _desktop_connector.start()


async def stop_desktop() -> None:
    if _desktop_connector:
        await _desktop_connector.stop()


async def submit_job(job):
    if _job_manager is None:
        raise ConfigInvalidError("Job manager not initialised.")
    return await _job_manager.submit(job)


# ── Observability helpers ─────────────────────────────────────────────────────

def get_health_status() -> dict:
    return get_health_checker().run_all_checks()


def get_metrics() -> dict:
    return get_metrics_registry().get_metrics()


def get_diagnostics() -> dict:
    diag = get_diagnostics_manager()
    return {
        "startup": diag.get_startup_diagnostic(),
        "uptime": diag.get_uptime(),
    }


def get_recovery_state() -> dict:
    return get_recovery_manager().get_recovery_state()


def get_module_states() -> dict:
    """Return a plain-dict snapshot of every module's lifecycle state."""
    return get_module_registry().snapshot()


# ── Public surface ────────────────────────────────────────────────────────────

__all__ = [
    "initialize_router",
    "initialize_memory",
    "initialize_tools",
    "initialize_messaging",
    "initialize_jobs",
    "initialize_desktop",
    "chat",
    "chat_stream",
    "route_chat",
    "handle_command",
    "set_provider",
    "set_model",
    "set_auto",
    "get_providers_info",
    "get_models_info",
    "get_capabilities",
    "add_memory",
    "get_memory",
    "get_all_memories",
    "delete_memory",
    "build_prompt",
    "add_interaction",
    "get_context_info",
    "handle_context_command",
    "compact_context",
    "initialize_persona",
    "initialize_skills",
    "get_persona_manager",
    "get_active_persona_text",
    "get_skill_manager",
    "handle_persona_command",
    "handle_skill_maker_command",
    "handle_skill_maker_step",
    "handle_skill_management_command",
    "_skill_maker_sessions",
    "match_skill_invocation",
    "handle_message",
    "start_messaging",
    "stop_messaging",
    "start_jobs",
    "stop_jobs",
    "start_desktop",
    "stop_desktop",
    "submit_job",
    "get_health_status",
    "get_metrics",
    "get_diagnostics",
    "get_recovery_state",
    "get_module_states",
]
