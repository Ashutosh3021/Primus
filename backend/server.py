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
    except Exception:
        pass

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
            get_module_states,
        )
        cfg = load_config()

        for name, fn, args in [
            ("memory",    initialize_memory,    ()),
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
    """Return the current config.json (secrets are never returned)."""
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config.json not found")
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Strip any accidental secret values from the response
    if "provider" in data and "secret_ref" in data["provider"]:
        data["provider"].pop("api_key", None)
    return data


@app.post("/api/secrets/set", tags=["secrets"])
async def set_secret_endpoint(payload: SecretSetRequest) -> Dict[str, Any]:
    """Store a secret in the OS keyring or .env fallback."""
    try:
        from backend.secrets import set_secret
        set_secret(payload.secret_ref, payload.secret_value)
        return {"success": True}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ─────────────────────────────────────────────────────────────────────────────
# PART 3 – Chat endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/chat", tags=["chat"])
async def chat_endpoint(payload: ChatRequest) -> Dict[str, Any]:
    """
    Send a message to the configured AI provider and return the response.
    Builds context from memory before forwarding to the provider.
    """
    _require_startup()

    from backend.api import chat, build_prompt, add_interaction
    from backend.providers.base import Message

    try:
        # Build context-aware prompt
        user_content = payload.messages[-1]["content"] if payload.messages else ""
        enriched_prompt = await build_prompt(
            payload.user_id, payload.conversation_id, user_content
        )

        messages = [Message(role="user", content=enriched_prompt)]
        completion = await chat(
            messages,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )

        # Persist the interaction
        await add_interaction(
            payload.user_id,
            payload.conversation_id,
            user_content,
            completion.content,
        )

        return {
            "content": completion.content,
            "model": completion.model,
            "provider": completion.provider,
            "usage": completion.usage,
            "finish_reason": completion.finish_reason,
        }

    except Exception as exc:
        logger.error(f"Chat error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


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
