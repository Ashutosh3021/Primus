"""
Application startup sequence for Primus backend.

Core modules (database, memory, tools, jobs, desktop) must succeed or the
process exits with an error — they have no optional secrets.

Optional modules (router, messaging) catch SecretNotFoundError inside their
own initialize_* functions (see backend/api/__init__.py) and enter
WAITING_FOR_CONFIG state.  Startup therefore always completes successfully
even when no secrets have been stored yet (first-time user).
"""

import asyncio

from backend.config import Config, load_config
from backend.api import (
    initialize_router,
    initialize_memory,
    initialize_tools,
    initialize_messaging,
    initialize_jobs,
    initialize_desktop,
    start_messaging,
    stop_messaging,
    start_jobs,
    stop_jobs,
    start_desktop,
    stop_desktop,
)
from backend.db import init_db
from backend.logger import get_errors_logger
from backend.diagnostics import get_diagnostics_manager
from backend.metrics import get_metrics_registry
from backend.health import get_health_checker
from backend.recovery import get_recovery_manager
from backend.exceptions import ConfigNotFoundError

logger = get_errors_logger(__name__)
_running = False


async def startup_async() -> Config:
    """
    Full async startup sequence.

    Raises only for genuinely fatal errors (missing config file, corrupt DB,
    etc.).  Missing optional secrets do NOT raise — the affected module enters
    WAITING_FOR_CONFIG and startup continues.
    """
    global _running

    logger.info("Starting Primus backend…")

    diag = get_diagnostics_manager()
    diag.start_diagnostics()

    # ── Config ────────────────────────────────────────────────────────────────
    # A missing config.json on a first-time deploy is non-fatal: we proceed
    # with no config so the Wizard can POST /api/config/apply later.
    logger.info("Loading configuration…")
    config: Config | None = None
    try:
        config = load_config()
        diag.mark_config_loaded()
        logger.info(f"Configuration loaded. Version: {config.version}")
    except ConfigNotFoundError:
        logger.warning(
            "[WARNING] config.json not found — server starting without "
            "configuration. Complete the Wizard to activate modules."
        )
    except Exception as exc:
        logger.error(f"Failed to load configuration: {exc}", exc_info=True)
        raise

    # ── Database ──────────────────────────────────────────────────────────────
    logger.info("Initialising database…")
    await init_db()
    diag.mark_db_initialized()

    # ── Memory ────────────────────────────────────────────────────────────────
    logger.info("Initialising memory system…")
    initialize_memory()
    diag.mark_memory_initialized()

    # ── Tools ─────────────────────────────────────────────────────────────────
    if config is not None:
        logger.info("Initialising tool system…")
        initialize_tools(config)
        diag.mark_tools_initialized()

    # ── Jobs ──────────────────────────────────────────────────────────────────
    if config is not None:
        logger.info("Initialising job system…")
        initialize_jobs(config)
        diag.mark_jobs_initialized()

    # ── AI Router ─────────────────────────────────────────────────────────────
    # initialize_router catches SecretNotFoundError internally and sets
    # WAITING_FOR_CONFIG — it never raises for a missing secret.
    if config is not None:
        logger.info("Initialising AI router…")
        initialize_router(config)
        diag.mark_router_initialized()

    # ── Messaging ─────────────────────────────────────────────────────────────
    # Same contract: each platform silently degrades to WAITING_FOR_CONFIG
    # when its secret is absent.
    if config is not None:
        logger.info("Initialising messaging…")
        initialize_messaging(config)
        diag.mark_messaging_initialized()

    # ── Desktop ───────────────────────────────────────────────────────────────
    if config is not None:
        logger.info("Initialising desktop agent…")
        initialize_desktop(config)
        diag.mark_desktop_initialized()

    _running = True
    logger.info("Primus backend startup complete.")
    return config


async def run_forever(config: Config) -> None:
    """Run forever after startup, handling signals."""
    global _running
    await start_messaging()
    await start_jobs()
    await start_desktop()
    while _running:
        await asyncio.sleep(1)


def startup() -> Config:
    """Synchronous wrapper around startup_async."""
    return asyncio.run(startup_async())


async def shutdown_async() -> None:
    """Async shutdown sequence."""
    global _running
    logger.info("Shutting down Primus backend…")
    _running = False
    await stop_desktop()
    await stop_messaging()
    await stop_jobs()
    logger.info("Primus backend shutdown complete.")


def shutdown() -> None:
    """Synchronous wrapper around shutdown_async."""
    asyncio.run(shutdown_async())
