"""
HTTP server for Primus backend.

Exposes FastAPI endpoints consumed by the Wizard, Ledger, and Dashboard.
All business logic lives in backend/api/__init__.py — this module is
purely the HTTP transport layer.
"""

import json
import os
import time
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from backend.constants import BASE_DIR, CONFIG_PATH, VERSION
from backend.config import load_config
from backend.exceptions import (
    ConfigNotFoundError,
    ConfigInvalidError,
    ConfigVersionError,
    ValidationError,
    SecretNotFoundError,
)
from backend.validators import validate_config
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Lifespan: run startup/shutdown around the server process
# ─────────────────────────────────────────────────────────────────────────────

_startup_done: bool = False
_startup_error: Optional[str] = None
_startup_progress: List[Dict[str, Any]] = []
_server_start_time: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan: startup → yield → shutdown.

    Startup is designed to always succeed so the HTTP server can accept
    traffic immediately.  Optional modules (router, messaging) that are
    missing secrets enter WAITING_FOR_CONFIG state instead of raising.
    Only genuine fatal errors (corrupt database, etc.) cause startup to fail.
    """
    global _startup_done, _startup_error, _startup_progress

    from backend.startup import startup_async, shutdown_async
    from backend.api import start_messaging, start_jobs, start_desktop
    from backend.trigger import start_keepalive, stop_keepalive

    # Resolve the port so the keepalive pings the right local address.
    _port = int(os.getenv("PORT", "8000"))

    steps = [
        "config", "database", "memory", "tools",
        "jobs", "router", "messaging", "desktop",
    ]
    progress: List[Dict[str, Any]] = [
        {"step": s, "status": "pending"} for s in steps
    ]
    _startup_progress = progress

    def mark(step: str, ok: bool, detail: str = "") -> None:
        for p in progress:
            if p["step"] == step:
                p["status"] = "ok" if ok else "error"
                if detail:
                    p["detail"] = detail
                break

    try:
        config = await startup_async()

        # Reflect what startup_async actually completed
        from backend.diagnostics import get_diagnostics_manager
        sd = get_diagnostics_manager().get_startup_diagnostic()
        if sd:
            mark("config",    sd.config_loaded)
            mark("database",  sd.db_initialized)
            mark("memory",    sd.memory_initialized)
            mark("tools",     sd.tools_initialized)
            mark("jobs",      sd.jobs_initialized)
            mark("router",    sd.router_initialized)
            mark("messaging", sd.messaging_initialized)
            mark("desktop",   sd.desktop_initialized)
        else:
            for step in steps:
                mark(step, True)

        await start_messaging()
        await start_jobs()
        await start_desktop()

        _startup_done = True
        logger.info("HTTP server startup complete.")

        # Start the self-healing keepalive loop as a background task.
        # It pings /health every 14 min to prevent Render free-tier sleep,
        # and re-initializes the router / Telegram if they fall over.
        start_keepalive(_port)

    except Exception as exc:
        _startup_error = str(exc)
        logger.error(f"Startup failed: {exc}", exc_info=True)
        for p in progress:
            if p["status"] == "pending":
                p["status"] = "skipped"
        # Do NOT re-raise: let the server start so /health returns 200 and
        # the Wizard can POST /api/config/apply to recover.

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    stop_keepalive()
    try:
        from backend.startup import shutdown_async
        await shutdown_async()
    except Exception as exc:
        logger.error(f"Shutdown error: {exc}", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Primus Backend",
    version=str(VERSION),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response models
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    user_id: str = "default"
    conversation_id: str = "default"


class ConfigSubmitRequest(BaseModel):
    config: Dict[str, Any]


class SecretSetRequest(BaseModel):
    secret_ref: str
    secret_value: str


class ProviderSetRequest(BaseModel):
    provider: str


class ModelSetRequest(BaseModel):
    model: str


class AutoSetRequest(BaseModel):
    enabled: bool


class CompactRequest(BaseModel):
    conversation_id: str = "default"
    force: bool = False


class ContextMemorySetRequest(BaseModel):
    layer: str
    key: str
    value: str
    metadata: Optional[Dict[str, Any]] = None


class PersonaSetRequest(BaseModel):
    active: Optional[str] = None
    custom_text: Optional[str] = None


class SkillSetRequest(BaseModel):
    name: str
    instructions: str
    description: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _require_startup() -> None:
    """Raise 503 if the backend has not finished starting up."""
    if not _startup_done:
        detail = _startup_error or "Backend is still starting up."
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )


def _uptime_seconds() -> float:
    return time.time() - _server_start_time


# ─────────────────────────────────────────────────────────────────────────────
# PART 1 – Health & Status
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health() -> Dict[str, Any]:
    """
    Lightweight health check used by Render and load balancers.
    Always returns HTTP 200 while the process is alive.

    Overall status is HEALTHY even when optional modules are waiting for
    configuration — only critical infrastructure failures degrade it.
    Module-level states are exposed under the 'modules' key.
    """
    from backend.api import get_health_status, get_module_states

    try:
        result = get_health_status()
    except Exception:
        result = {"status": "unknown", "checks": []}

    try:
        modules = get_module_states()
    except Exception:
        modules = {}

    return {
        "status": result.get("status", "unknown"),
        "startup_done": _startup_done,
        "startup_error": _startup_error,
        "uptime_seconds": _uptime_seconds(),
        "version": VERSION,
        "modules": modules,
    }


@app.get("/api/status", tags=["status"])
async def api_status() -> Dict[str, Any]:
    """
    Full backend status for the Ledger dashboard.
    Returns provider, model, module states, health, metrics, uptime.
    """
    from backend.api import get_health_status, get_metrics, get_diagnostics
    from backend.config import load_config

    health_data = {}
    metrics_data = {}
    diag_data: Dict[str, Any] = {}
    provider_name = "unknown"
    model_name = "unknown"
    memory_status = "disabled"
    connected_platforms: List[str] = []
    tools_enabled: List[str] = []
    scheduler_status = "unknown"
    desktop_status = "unknown"

    try:
        health_data = get_health_status()
    except Exception:
        pass

    try:
        metrics_data = get_metrics()
    except Exception:
        pass

    try:
        diag_data = get_diagnostics()
    except Exception:
        pass

    # Read config for display values (config already loaded at startup)
    try:
        cfg = load_config()
        provider_name = cfg.provider.name
        model_name = cfg.provider.model
        memory_status = "enabled" if cfg.memory.enabled else "disabled"
        tools_enabled = [
            k for k, v in {
                "web_search": cfg.tools.web_search,
                "browser": cfg.tools.browser,
                "terminal": cfg.tools.terminal,
            }.items() if v
        ]
        auto_enabled = cfg.auto_enabled
        current_provider = cfg.current_provider
        providers_summary = [
            {
                "name": name,
                "default_model": pcfg.get("default_model"),
                "enabled": pcfg.get("enabled", False),
            }
            for name, pcfg in (cfg.providers or {}).items()
        ]
    except Exception:
        provider_name = "unknown"
        model_name = "unknown"
        auto_enabled = False
        current_provider = None
        providers_summary = []

    # Messaging platforms with enabled flag
    try:
        from backend.api import _messaging_platforms  # type: ignore
        connected_platforms = list(_messaging_platforms.keys())
    except Exception:
        pass

    # Scheduler / job manager state
    try:
        from backend.api import _scheduler, _job_manager  # type: ignore
        scheduler_status = "running" if (
            _scheduler and getattr(_scheduler, "_running", False)
        ) else "stopped"
    except Exception:
        pass

    # Desktop connector state
    try:
        from backend.api import _desktop_connector  # type: ignore
        if _desktop_connector:
            caps = _desktop_connector.capabilities
            desktop_status = "running" if getattr(
                _desktop_connector, "_running", False
            ) else "stopped"
        else:
            desktop_status = "disabled"
    except Exception:
        pass

    startup_diag = None
    if diag_data and diag_data.get("startup"):
        sd = diag_data["startup"]
        if sd:
            startup_diag = {
                "config_loaded": getattr(sd, "config_loaded", False),
                "db_initialized": getattr(sd, "db_initialized", False),
                "memory_initialized": getattr(sd, "memory_initialized", False),
                "tools_initialized": getattr(sd, "tools_initialized", False),
                "jobs_initialized": getattr(sd, "jobs_initialized", False),
                "router_initialized": getattr(sd, "router_initialized", False),
                "messaging_initialized": getattr(sd, "messaging_initialized", False),
                "desktop_initialized": getattr(sd, "desktop_initialized", False),
                "errors": getattr(sd, "errors", []),
            }

    # Module lifecycle states from registry
    module_states: Dict[str, str] = {}
    try:
        from backend.api import get_module_states
        module_states = get_module_states()
    except Exception:
        pass

    return {
        "startup_done": _startup_done,
        "startup_error": _startup_error,
        "startup_progress": _startup_progress,
        "startup_diagnostics": startup_diag,
        "uptime_seconds": _uptime_seconds(),
        "version": VERSION,
        "provider": provider_name,
        "model": model_name,
        "auto_enabled": auto_enabled,
        "current_provider": current_provider,
        "providers": providers_summary,
        "memory_status": memory_status,
        "connected_platforms": connected_platforms,
        "tools_enabled": tools_enabled,
        "scheduler_status": scheduler_status,
        "desktop_status": desktop_status,
        "modules": module_states,
        "health": health_data,
        "metrics": metrics_data,
    }


@app.get("/api/diagnostics", tags=["diagnostics"])
async def diagnostics() -> Dict[str, Any]:
    """Full startup diagnostics and system information."""
    from backend.api import get_diagnostics
    from backend.diagnostics import get_diagnostics_manager

    diag = get_diagnostics_manager()
    sys_info = {}
    try:
        sys_info = diag.get_system_info()
    except Exception:
        pass

    startup = diag.get_startup_diagnostic()
    startup_dict: Dict[str, Any] = {}
    if startup:
        startup_dict = {
            "timestamp": startup.timestamp,
            "version": startup.version,
            "config_loaded": startup.config_loaded,
            "db_initialized": startup.db_initialized,
            "memory_initialized": startup.memory_initialized,
            "tools_initialized": startup.tools_initialized,
            "jobs_initialized": startup.jobs_initialized,
            "router_initialized": startup.router_initialized,
            "messaging_initialized": startup.messaging_initialized,
            "desktop_initialized": startup.desktop_initialized,
            "errors": startup.errors,
        }

    return {
        "system": sys_info,
        "startup": startup_dict,
        "uptime_seconds": _uptime_seconds(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 – Configuration endpoints (Wizard integration)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/config/validate", tags=["config"])
async def validate_config_endpoint(payload: ConfigSubmitRequest) -> Dict[str, Any]:
    """
    Validate a config dict sent by the Wizard.
    Returns { valid: bool, errors: list[str] }.
    """
    errors: List[str] = []
    try:
        validate_config(payload.config)
    except ValidationError as exc:
        errors.append(str(exc))
    except Exception as exc:
        errors.append(f"Unexpected validation error: {exc}")

    return {"valid": len(errors) == 0, "errors": errors}


@app.post("/api/config/apply", tags=["config"])
async def apply_config(payload: ConfigSubmitRequest) -> Dict[str, Any]:
    """
    Write config.json from the Wizard and trigger a module re-initialisation.

    The Wizard calls this after the user completes the setup flow.
    Returns { success: bool, errors: list[str], progress: list }.
    """
    errors: List[str] = []

    # 1. Validate first
    try:
        validate_config(payload.config)
    except (ValidationError, Exception) as exc:
        return {"success": False, "errors": [str(exc)], "progress": []}

    # 2. Write config.json atomically
    try:
        tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload.config, fh, indent=2)
        tmp_path.replace(CONFIG_PATH)
    except Exception as exc:
        return {"success": False, "errors": [f"Failed to write config: {exc}"], "progress": []}

    # 3. Re-initialise modules with the new config
    progress: List[Dict[str, str]] = []
    try:
        from backend.api import (
            initialize_router, initialize_memory, initialize_tools,
            initialize_messaging, initialize_jobs, initialize_desktop,
            stop_messaging, start_messaging,
            get_module_states,
        )
        cfg = load_config()

        # Stop any existing messaging polling loops before re-initialising.
        # Without this, old Telegram tasks become zombies and the new ones
        # never start because initialize_messaging() only creates instances —
        # it does not call start() on them.
        try:
            await stop_messaging()
            logger.info("apply_config: stopped existing messaging platforms before re-init")
        except Exception as exc:
            logger.warning(f"apply_config: stop_messaging warning (non-fatal): {exc}")

        for name, fn, args in [
            ("memory",    initialize_memory,    (cfg,)),
            ("tools",     initialize_tools,     (cfg,)),
            ("jobs",      initialize_jobs,      (cfg,)),
            ("router",    initialize_router,    (cfg,)),
            ("messaging", initialize_messaging, (cfg,)),
            ("desktop",   initialize_desktop,   (cfg,)),
        ]:
            try:
                fn(*args)
                progress.append({"step": name, "status": "ok"})
            except Exception as exc:
                progress.append({"step": name, "status": "error", "detail": str(exc)})
                errors.append(f"{name}: {exc}")

        # Start polling loops for newly initialised messaging platforms.
        # This mirrors what the lifespan handler does at server startup.
        try:
            await start_messaging()
            logger.info("apply_config: messaging platforms started after re-init")
        except Exception as exc:
            logger.error(f"apply_config: start_messaging failed: {exc}", exc_info=True)
            errors.append(f"messaging start: {exc}")

        # Attach per-module lifecycle states so the Wizard can show them
        module_states = get_module_states()
        for p in progress:
            state = module_states.get(p["step"])
            if state:
                p["module_state"] = state

        global _startup_done
        _startup_done = True

    except Exception as exc:
        errors.append(f"Re-init failed: {exc}")

    return {
        "success": len(errors) == 0,
        "errors": errors,
        "progress": progress,
    }


@app.get("/api/config", tags=["config"])
async def get_config() -> Dict[str, Any]:
    """
    Return the current config.json including the _wizard_state snapshot.

    Secret values are never stored in config.json (they go to the keyring),
    so no stripping is required beyond removing any accidentally persisted
    api_key field in the provider block.
    """
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config.json not found")
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Strip any accidental secret value that should be in the keyring only
    if "provider" in data:
        data["provider"].pop("api_key", None)
    # Scrub any secret-looking keys from _wizard_state as a safety belt
    _SECRET_KEYS = {
        "apiKey", "tgToken", "dcToken", "waToken",
        "emailPass", "gchatJson", "smsAuthToken", "haToken",
    }
    if "_wizard_state" in data and isinstance(data["_wizard_state"], dict):
        for k in _SECRET_KEYS:
            data["_wizard_state"].pop(k, None)
    return data


@app.post("/api/secrets/set", tags=["secrets"])
async def set_secret_endpoint(payload: SecretSetRequest) -> Dict[str, Any]:
    """Persist a secret to the on-disk secrets store (.secrets.env)."""
    try:
        from backend.secrets import set_secret
        set_secret(payload.secret_ref, payload.secret_value)
        return {"success": True}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@app.get("/api/secrets/check/{secret_ref:path}", tags=["secrets"])
async def check_secret_endpoint(secret_ref: str) -> Dict[str, Any]:
    """
    Check whether a secret is stored — returns {exists: bool}.
    The secret VALUE is never returned.

    Used by the Wizard's Restore flow to determine whether an API key
    is already present so it can show "Key stored — no need to re-enter."
    """
    try:
        from backend.secrets import get_secret
        get_secret(secret_ref)
        return {"exists": True, "secret_ref": secret_ref}
    except SecretNotFoundError:
        return {"exists": False, "secret_ref": secret_ref}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@app.get("/api/secrets/stored", tags=["secrets"])
async def list_stored_secrets_endpoint() -> Dict[str, Any]:
    """
    Return the list of secret key names persisted in the secrets store.
    Values are never exposed. Used by diagnostics to verify persistence.
    """
    from backend.secrets import list_stored_secrets
    return {"stored_keys": list_stored_secrets()}


# ─────────────────────────────────────────────────────────────────────────────
# PART 2b – Multi-Provider + Multi-Model control (v1.3.0)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/providers", tags=["providers"])
async def list_providers_endpoint() -> Dict[str, Any]:
    """
    Return the full multi-provider snapshot: every provider with its
    enabled/configured flags, stored default model, available models, and
    whether it is the current provider.  Also reports Auto Mode state.
    """
    from backend.api import get_providers_info
    return get_providers_info()


@app.get("/api/models", tags=["providers"])
async def list_models_endpoint() -> Dict[str, Any]:
    """
    Return the model catalog: current provider + model, plus a per-provider
    map of default_model / available_models / configured flag.
    """
    from backend.api import get_models_info
    return get_models_info()


@app.post("/api/provider", tags=["providers"])
async def set_provider_endpoint(payload: ProviderSetRequest) -> Dict[str, Any]:
    """
    Permanently switch the active provider (persists after restart).

    Restores that provider's own stored default_model automatically.
    """
    from backend.api import set_provider
    try:
        info = set_provider(payload.provider)
        return {"success": True, **info}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@app.post("/api/model", tags=["providers"])
async def set_model_endpoint(payload: ModelSetRequest) -> Dict[str, Any]:
    """
    Change only the CURRENT provider's default model (persists after restart).

    Strict validation: an unknown model is rejected (no fuzzy match / silent
    switch) with an explicit list of available models.
    """
    from backend.api import set_model
    res = set_model(payload.model)
    if res.get("ok"):
        return {"success": True, **res}
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=res.get("error", "Invalid model"),
        headers={"X-Available-Models": ", ".join(res.get("available_models", []))},
    )


@app.post("/api/auto", tags=["providers"])
async def set_auto_endpoint(payload: AutoSetRequest) -> Dict[str, Any]:
    """
    Enable or disable Auto Mode (rule-based task routing). Persists after restart.
    """
    from backend.api import set_auto
    res = set_auto(payload.enabled)
    return {"success": True, **res}


# ─────────────────────────────────────────────────────────────────────────────
# PART 3 – Chat endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/chat", tags=["chat"])
async def chat_endpoint(payload: ChatRequest) -> Dict[str, Any]:
    """
    Send a message through the single shared runtime (Primus Core).

    ALL message handling — provider/model/persona/compact/skill commands,
    skill invocation, and normal chat — is delegated to ``handle_message`` in
    backend.api.  The Dashboard / REST API therefore behaves identically to
    Telegram and any future interface; this endpoint owns no AI logic.

    Commands supported by the runtime:
      /provider <name>     switch active provider (restores its model)
      /model <model>       change current provider's model (strict validation)
      /auto                toggle Auto Mode
      /persona <name>      switch global persona (default|developer|architect|
                            critic|devils-advocate|teacher|researcher|minimal|
                            explain|analyst|custom|<any custom prompt>)
      /compact             hard-compact the active session
      /skill-maker <n>::<i>  create a persistent, invocable skill
      /<skillname>         invoke a stored skill
    """
    _require_startup()

    from backend.api import handle_message

    user_content = payload.messages[-1]["content"] if payload.messages else ""

    try:
        result = await handle_message(
            user_content, payload.user_id, payload.conversation_id or "default"
        )
    except Exception as exc:
        logger.error(f"Chat error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PART 4b – Context Engine (v1.3.0)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/context", tags=["context"])
async def context_endpoint(
    conversation_id: str = "default",
) -> Dict[str, Any]:
    """
    Context budget + layered-memory snapshot.

    Returns max / current / remaining / percentage tokens, the prune
    threshold, per-layer entry counts, and the active-session message count.
    """
    _require_startup()
    from backend.api import get_context_info

    try:
        return await get_context_info(conversation_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@app.post("/api/compact", tags=["context"])
async def compact_endpoint(payload: CompactRequest) -> Dict[str, Any]:
    """
    Hard-compact the active session: summarise it, archive the summary into
    Compact Memory, and clear the live conversation.
    """
    _require_startup()
    from backend.api import compact_context

    try:
        return await compact_context(payload.conversation_id, payload.force)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@app.get("/api/context/memory", tags=["context"])
async def list_context_memory(
    layer: Optional[str] = None,
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """List entries in the layered memory (optionally filtered by layer/key)."""
    _require_startup()
    from backend.api import _context_engine
    from backend.context import ContextLayer, is_valid_layer

    if layer and not is_valid_layer(layer):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown layer {layer!r}. Valid: {[l.value for l in ContextLayer]}",
        )
    ctx_layer = ContextLayer(layer) if layer else None
    if key and ctx_layer is not None:
        entry = await _context_engine.store.get(ctx_layer, key)
        entries = [entry] if entry else []
    else:
        entries = await _context_engine.store.get_all(ctx_layer)
    return {
        "entries": [
            {
                "layer": layer or "all",
                "key": e["key"],
                "value": e["value"],
                "metadata": e["metadata"],
                "created_at": e.get("created_at"),
                "updated_at": e.get("updated_at"),
            }
            for e in entries
        ],
        "count": len(entries),
    }


@app.post("/api/context/memory", tags=["context"])
async def set_context_memory(payload: ContextMemorySetRequest) -> Dict[str, Any]:
    """Write an entry into one of the eight context layers."""
    _require_startup()
    from backend.api import _context_engine
    from backend.context import ContextLayer, is_valid_layer

    if not is_valid_layer(payload.layer):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown layer {payload.layer!r}. Valid: {[l.value for l in ContextLayer]}",
        )
    await _context_engine.set_fact(
        ContextLayer(payload.layer), payload.key, payload.value, payload.metadata
    )
    return {"ok": True, "layer": payload.layer, "key": payload.key}


@app.delete("/api/context/memory", tags=["context"])
async def delete_context_memory(
    layer: str,
    key: str,
) -> Dict[str, Any]:
    """Delete an entry from a context layer."""
    _require_startup()
    from backend.api import _context_engine
    from backend.context import ContextLayer, is_valid_layer

    if not is_valid_layer(layer):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown layer {layer!r}. Valid: {[l.value for l in ContextLayer]}",
        )
    removed = await _context_engine.delete_fact(ContextLayer(layer), key)
    return {"ok": True, "removed": removed, "layer": layer, "key": key}


# ─────────────────────────────────────────────────────────────────────────────
# PART 4c – Global Persona + Skills (read/manage; runtime owns the logic)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/personas", tags=["persona"])
async def list_personas_endpoint() -> Dict[str, Any]:
    """
    List the available personas and the currently active one (global).

    Returns the active preset name, the full preset list (with display names
    for the Dashboard selector), the five-field breakdown of the active persona
    (``active_detail``), and the current custom persona text (``custom_text``)
    so the Custom Persona editor can be pre-filled.
    """
    _require_startup()
    from backend.api import get_persona_manager

    mgr = get_persona_manager()
    info = mgr.list_personas()
    return {
        "active": info["active"],
        "presets": info["presets"],
        "preset_displays": info.get("preset_displays", {}),
        "custom_set": info["custom_set"],
        "active_detail": mgr.get_active_detail(),
        "custom_text": mgr.get_custom_text(),
    }


@app.post("/api/persona", tags=["persona"])
async def set_persona_endpoint(payload: PersonaSetRequest) -> Dict[str, Any]:
    """
    Switch the global active persona (affects every interface immediately).

    Body: {"active": "critic"}  or  {"custom_text": "You are ..."}  to set + activate.
    """
    _require_startup()
    from backend.api import get_persona_manager

    mgr = get_persona_manager()
    try:
        if payload.active is not None:
            mgr.set_active(payload.active)
        elif payload.custom_text is not None:
            mgr.set_custom(payload.custom_text)
        else:
            return {"ok": False, "error": "Provide 'active' or 'custom_text'."}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return {"ok": True, "active": mgr.get_active_name()}


@app.get("/api/skills", tags=["skills"])
async def list_skills_endpoint() -> Dict[str, Any]:
    """List all persistent skills (shared across every interface)."""
    _require_startup()
    from backend.api import get_skill_manager

    skills = await get_skill_manager().list_skills()
    return {"skills": skills, "count": len(skills)}


@app.post("/api/skill", tags=["skills"])
async def create_skill_endpoint(payload: SkillSetRequest) -> Dict[str, Any]:
    """Create (or overwrite) a persistent skill."""
    _require_startup()
    from backend.api import get_skill_manager

    try:
        skill = await get_skill_manager().create_skill(
            payload.name, payload.instructions, description=payload.description
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return {"ok": True, "skill": skill}


@app.delete("/api/skill", tags=["skills"])
async def delete_skill_endpoint(name: str) -> Dict[str, Any]:
    """Delete a persistent skill by name."""
    _require_startup()
    from backend.api import get_skill_manager

    removed = await get_skill_manager().delete_skill(name)
    return {"ok": True, "removed": removed, "name": name}


# ─────────────────────────────────────────────────────────────────────────────
# PART 4 – Ledger / Dashboard data endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/jobs", tags=["jobs"])
async def list_jobs(limit: int = 50, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Return all jobs, optionally filtered by user."""
    _require_startup()
    from backend.db import JobStore
    store = JobStore()
    jobs = await store.get_all(user_id=user_id, limit=limit)
    return {
        "jobs": [
            {
                "job_id": j.job_id,
                "name": j.name,
                "user_id": j.user_id,
                "status": j.status.value,
                "retry_count": j.retry_count,
                "result": j.result,
                "error": j.error,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in jobs
        ],
        "count": len(jobs),
    }


@app.get("/api/jobs/{job_id}", tags=["jobs"])
async def get_job(job_id: str) -> Dict[str, Any]:
    """Return a single job by ID."""
    _require_startup()
    from backend.db import JobStore
    store = JobStore()
    job = await store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return {
        "job_id": job.job_id,
        "name": job.name,
        "user_id": job.user_id,
        "status": job.status.value,
        "params": job.params,
        "retry_count": job.retry_count,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@app.get("/api/metrics", tags=["metrics"])
async def metrics_endpoint() -> Dict[str, Any]:
    """Return collected metrics."""
    _require_startup()
    from backend.api import get_metrics
    return get_metrics()


@app.get("/api/logs", tags=["logs"])
async def get_logs(stream: str = "errors", lines: int = 100) -> Dict[str, Any]:
    """
    Return recent log lines from the requested stream.
    Supported streams: errors, ai_requests, tool_calls, jobs, notifications.
    """
    _require_startup()
    from backend.constants import LOG_DIR, LOG_STREAMS

    if stream not in LOG_STREAMS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown log stream {stream!r}. Valid: {LOG_STREAMS}",
        )

    log_file = LOG_DIR / f"{stream}.log"
    if not log_file.exists():
        return {"stream": stream, "lines": []}

    try:
        with open(log_file, "r", encoding="utf-8") as fh:
            all_lines = fh.readlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        parsed = []
        for line in tail:
            line = line.strip()
            if line:
                try:
                    parsed.append(json.loads(line))
                except json.JSONDecodeError:
                    parsed.append({"message": line})
        return {"stream": stream, "lines": parsed}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to read log: {exc}"
        )


@app.get("/api/memory", tags=["memory"])
async def list_memory(
    user_id: str = "default",
    layer: Optional[str] = None,
) -> Dict[str, Any]:
    """Return memory entries for a user."""
    _require_startup()
    from backend.api import get_all_memories
    from backend.db import MemoryLayer

    mem_layer = None
    if layer:
        try:
            mem_layer = MemoryLayer(layer)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown layer {layer!r}. Valid: {[l.value for l in MemoryLayer]}",
            )

    entries = await get_all_memories(user_id, mem_layer)
    return {
        "entries": [
            {
                "id": e.id,
                "user_id": e.user_id,
                "layer": e.layer.value,
                "key": e.key,
                "value": e.value,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "updated_at": e.updated_at.isoformat() if e.updated_at else None,
            }
            for e in entries
        ],
        "count": len(entries),
    }


@app.get("/api/notifications", tags=["notifications"])
async def list_notifications(
    user_id: str = "default",
    limit: int = 50,
) -> Dict[str, Any]:
    """Return recent notifications for a user."""
    _require_startup()
    import aiosqlite
    from backend.db import DB_PATH

    rows = []
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT notification_id, user_id, channel, title, content, sent_at, created_at "
                "FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
            async for row in cursor:
                rows.append({
                    "notification_id": row[0],
                    "user_id": row[1],
                    "channel": row[2],
                    "title": row[3],
                    "content": row[4],
                    "sent_at": row[5],
                    "created_at": row[6],
                })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"notifications": rows, "count": len(rows)}


@app.get("/api/cron", tags=["scheduler"])
async def list_cron_schedules() -> Dict[str, Any]:
    """Return all enabled cron schedules."""
    _require_startup()
    from backend.db import CronStore
    store = CronStore()
    schedules = await store.get_enabled()
    return {
        "schedules": [
            {
                "cron_id": s.cron_id,
                "name": s.name,
                "job_name": s.job_name,
                "cron_expr": s.cron_expr,
                "enabled": s.enabled,
                "last_run": s.last_run.isoformat() if s.last_run else None,
                "next_run": s.next_run.isoformat() if s.next_run else None,
            }
            for s in schedules
        ],
        "count": len(schedules),
    }


@app.get("/api/capabilities", tags=["capabilities"])
async def get_capabilities_endpoint() -> Dict[str, Any]:
    """Return current provider and desktop capabilities."""
    _require_startup()
    from backend.api import get_capabilities
    caps = get_capabilities()
    # Serialize dataclass fields safely
    result: Dict[str, Any] = {}
    if "provider" in caps:
        p = caps["provider"]
        result["provider"] = {
            "supports_vision": getattr(p, "supports_vision", False),
            "supports_streaming": getattr(p, "supports_streaming", False),
            "supports_function_calling": getattr(p, "supports_function_calling", False),
            "supports_audio": getattr(p, "supports_audio", False),
        }
    if "desktop" in caps:
        d = caps["desktop"]
        result["desktop"] = {
            "os": getattr(d, "os", "unknown"),
            "python_version": getattr(d, "python_version", "unknown"),
            "has_terminal": getattr(d, "has_terminal", False),
            "has_filesystem": getattr(d, "has_filesystem", False),
            "has_git": getattr(d, "has_git", False),
            "has_ollama": getattr(d, "has_ollama", False),
            "has_docker": getattr(d, "has_docker", False),
            "online": getattr(d, "online", False),
        }
    return result


@app.get("/api/recovery", tags=["recovery"])
async def recovery_state() -> Dict[str, Any]:
    """Return circuit breaker and failure state."""
    _require_startup()
    from backend.api import get_recovery_state
    return get_recovery_state()


@app.get("/api/trigger/status", tags=["trigger"])
async def trigger_status() -> Dict[str, Any]:
    """
    Return the current state of the self-healing keepalive task.
    Useful for verifying that trigger.py is running on Render.
    """
    from backend.trigger import _task, PING_INTERVAL, _uptime_seconds
    task_alive = _task is not None and not _task.done()
    return {
        "keepalive_running": task_alive,
        "ping_interval_seconds": PING_INTERVAL,
        "process_uptime_seconds": round(_uptime_seconds(), 1),
        "task_cancelled": _task.cancelled() if _task and _task.done() else False,
    }


@app.get("/api/dashboard", tags=["dashboard"])
async def dashboard_metrics() -> Dict[str, Any]:
    """
    Single aggregated endpoint for the Dashboard metrics panel.

    Returns all counters the frontend needs in one HTTP call:
      - uptime_seconds
      - jobs: total, pending, running, completed, failed
      - ai: calls_total, calls_success, calls_error, tokens_total
      - telegram: messages_received, replies_sent
      - errors: count from error log file
      - memory_mb: resident set size of this process
      - modules: lifecycle states
    """
    import os, psutil  # psutil is an optional dep; fall back gracefully

    from backend.metrics import get_metrics_registry
    from backend.db import JobStore, DB_PATH
    from backend.constants import LOG_DIR

    reg = get_metrics_registry()

    # ── Job counts (from SQLite — persistent) ────────────────────────────────
    job_counts: Dict[str, int] = {}
    try:
        store = JobStore()
        job_counts = await store.get_counts_by_status()
    except Exception:
        pass

    jobs_total = sum(job_counts.values())

    # ── AI + Telegram metrics (in-memory counters) ────────────────────────────
    ai_calls_total   = reg.get_counter("ai.calls_total")
    ai_calls_success = reg.get_counter("ai.calls_success")
    ai_calls_error   = reg.get_counter("ai.calls_error")
    tokens_total     = reg.get_counter("ai.tokens_total")
    tg_received      = reg.get_counter("telegram.messages_received")
    tg_sent          = reg.get_counter("telegram.replies_sent")

    # ── Error count (from log file — persistent across restarts) ─────────────
    error_count = 0
    try:
        error_log = LOG_DIR / "errors.log"
        if error_log.exists():
            with open(error_log, "r", encoding="utf-8", errors="replace") as fh:
                error_count = sum(1 for line in fh if line.strip())
    except Exception:
        pass

    # ── Memory usage (RSS in MB) ──────────────────────────────────────────────
    memory_mb = 0.0
    try:
        proc = psutil.Process(os.getpid())
        memory_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
    except Exception:
        try:
            # Fallback: read /proc/self/status on Linux
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        memory_mb = round(int(line.split()[1]) / 1024, 1)
                        break
        except Exception:
            pass

    # ── Module states ─────────────────────────────────────────────────────────
    module_states: Dict[str, str] = {}
    try:
        from backend.api import get_module_states
        module_states = get_module_states()
    except Exception:
        pass

    return {
        "uptime_seconds": round(_uptime_seconds(), 1),
        "jobs": {
            "total":     jobs_total,
            "pending":   job_counts.get("pending",   0),
            "running":   job_counts.get("running",   0),
            "completed": job_counts.get("completed", 0),
            "failed":    job_counts.get("failed",    0),
        },
        "ai": {
            "calls_total":   ai_calls_total,
            "calls_success": ai_calls_success,
            "calls_error":   ai_calls_error,
            "tokens_total":  tokens_total,
        },
        "telegram": {
            "messages_received": tg_received,
            "replies_sent":      tg_sent,
        },
        "errors": error_count,
        "memory_mb": memory_mb,
        "modules": module_states,
    }


@app.post("/api/git-learning/scan", tags=["git-learning"])
async def git_learning_scan(payload: dict = None) -> Dict[str, Any]:
    """
    Scan a local git repository and extract a structured summary.
    Optionally saves the summary into the user's Project memory.

    Request body (all optional):
        { "repo_path": ".", "user_id": "default", "save_to_memory": true }
    """
    _require_startup()
    body = payload or {}
    repo_path = body.get("repo_path", ".")
    user_id = body.get("user_id", "default")
    save = body.get("save_to_memory", True)

    try:
        import importlib
        git_learning_mod = importlib.import_module("backend.git-learning")
        GitLearner = git_learning_mod.GitLearner
        from backend.db import MemoryStore

        learner = GitLearner(repo_path)
        summary = await learner.learn()

        if save and not summary.error:
            store = MemoryStore()
            await learner.save_to_memory(store, user_id=user_id)

        return {
            "name": summary.name,
            "path": summary.path,
            "purpose": summary.purpose,
            "languages": summary.languages,
            "frameworks": summary.frameworks,
            "architecture": summary.architecture,
            "branch": summary.branch,
            "open_tasks": summary.open_tasks,
            "recent_commits": summary.recent_commits,
            "summary_text": summary.as_text(),
            "saved_to_memory": save and not summary.error,
            "error": summary.error,
        }
    except Exception as exc:
        logger.error(f"Git learning scan error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/git-learning/jobs", tags=["git-learning"])
async def git_learning_jobs() -> Dict[str, Any]:
    """Return all git_learning jobs from the job store."""
    _require_startup()
    from backend.db import JobStore
    store = JobStore()
    jobs = await store.get_all()
    gl_jobs = [j for j in jobs if j.name == "git_learning"]
    return {
        "jobs": [
            {
                "job_id": j.job_id,
                "status": j.status.value,
                "params": j.params,
                "result": j.result,
                "error": j.error,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in gl_jobs
        ],
        "count": len(gl_jobs),
    }


@app.post("/api/automation/run", tags=["automation"])
async def automation_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute an automation workflow using enabled desktop tools.

    Request body — either a named built-in or an inline workflow::

        { "workflow": "git_status" }                     # built-in by name
        { "workflow": { "name": "x", "steps": [...] } }  # inline definition

    Each step::

        { "tool": "terminal", "params": { "command": "ls" }, "description": "list files" }

    Supports ``{step_N}`` template variables in params (0-based step index).
    """
    _require_startup()

    from backend.desktop.automation import AutomationEngine, get_builtin_workflow
    from backend.api import _tool_manager  # type: ignore

    if _tool_manager is None:
        raise HTTPException(status_code=503, detail="Tool manager not initialised")

    workflow_input = payload.get("workflow")
    if workflow_input is None:
        raise HTTPException(status_code=400, detail="'workflow' field required")

    try:
        if isinstance(workflow_input, str):
            workflow = get_builtin_workflow(workflow_input)
            if workflow is None:
                from backend.desktop.automation import BUILTIN_WORKFLOWS
                raise HTTPException(
                    status_code=404,
                    detail=f"Unknown built-in workflow {workflow_input!r}. "
                           f"Available: {list(BUILTIN_WORKFLOWS.keys())}",
                )
        else:
            workflow = AutomationEngine.from_dict(workflow_input)

        engine = AutomationEngine(_tool_manager)
        result = await engine.run(workflow)

        return {
            "name": result.name,
            "success": result.success,
            "stopped_at": result.stopped_at,
            "total_duration_ms": result.total_duration_ms,
            "summary": result.as_text(),
            "steps": [
                {
                    "step_index": s.step_index,
                    "tool": s.tool,
                    "success": s.success,
                    "content": s.content,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                }
                for s in result.steps
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Automation run error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/automation/workflows", tags=["automation"])
async def automation_list_workflows() -> Dict[str, Any]:
    """Return all available built-in automation workflows."""
    from backend.desktop.automation import BUILTIN_WORKFLOWS, AutomationEngine
    return {
        "workflows": [
            {
                "name": name,
                "description": raw.get("description", ""),
                "step_count": len(raw.get("steps", [])),
                "stop_on_failure": raw.get("stop_on_failure", True),
                "steps": [
                    {"tool": s["tool"], "description": s.get("description", "")}
                    for s in raw.get("steps", [])
                ],
            }
            for name, raw in BUILTIN_WORKFLOWS.items()
        ],
        "count": len(BUILTIN_WORKFLOWS),
    }


# ─────────────────────────────────────────────────────────────────────────────
# PART 5 – Error handlers
# ─────────────────────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )
