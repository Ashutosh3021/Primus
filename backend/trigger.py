"""
backend/trigger.py — Self-healing keepalive for Primus on Render free tier.

Render's free tier spins down a service after 15 minutes of inactivity.
This module runs a background asyncio task (inside the existing FastAPI
event loop) that:

  1. Pings the local /health endpoint every PING_INTERVAL seconds (840 s =
     14 min) so Render never sees 15 consecutive idle minutes.

  2. After every ping, inspects the ModuleRegistry directly and recovers
     any module that has fallen out of RUNNING state:
       - router not RUNNING  → re-initialize_router()
       - telegram not RUNNING (and not DISABLED) → stop + re-initialize + start

  3. Detects a wake-from-sleep event: if the wall-clock gap between two
     consecutive ticks is significantly larger than PING_INTERVAL, the
     process was suspended (Render cold-start or OS sleep).  On detection,
     an immediate full recovery cycle runs before the next scheduled ping.

  4. Verifies health after every recovery attempt and logs the result.

Design constraints
------------------
- Runs entirely inside the FastAPI process — no subprocess, no external cron,
  no threading.  Uses asyncio.create_task() inside the lifespan context.
- Uses only the existing initialize_* / start_messaging / stop_messaging
  surface from api/__init__.py.  No duplication of init logic.
- Never raises an unhandled exception — all errors are caught, logged, and
  the loop continues.
- Safe to run when config is missing (first-time deploy): the loop detects
  that config is absent and waits quietly without attempting recovery.
"""

import asyncio
import time
from typing import Optional

import httpx

from backend.logger import get_errors_logger
from backend.lifecycle import get_module_registry, ModuleState

logger = get_errors_logger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────
# 14 minutes — safely below Render's 15-minute inactivity threshold.
PING_INTERVAL: int = 14 * 60          # seconds between keepalive pings

# If the gap between two ticks exceeds this multiplier × PING_INTERVAL,
# we assume the process was suspended and run an immediate recovery.
SLEEP_DETECTION_MULTIPLIER: float = 1.5

# How long to wait after a failed recovery before retrying (seconds).
RECOVERY_RETRY_DELAY: int = 30

# HTTP timeout for the self-ping (local loopback, should be fast).
PING_TIMEOUT: float = 10.0

# ── State ─────────────────────────────────────────────────────────────────────
_task: Optional[asyncio.Task] = None
_started_at: float = time.monotonic()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uptime_seconds() -> float:
    return time.monotonic() - _started_at


async def _ping_health(port: int) -> bool:
    """
    GET http://127.0.0.1:{port}/health and return True if the response
    contains {"startup_done": true}.  Returns False on any error.
    """
    url = f"http://127.0.0.1:{port}/health"
    try:
        async with httpx.AsyncClient(timeout=PING_TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                startup_done = data.get("startup_done", False)
                modules = data.get("modules", {})
                logger.info(
                    f"[TRIGGER] Ping OK | startup_done={startup_done} | "
                    f"uptime={_uptime_seconds():.0f}s | modules={modules}"
                )
                return bool(startup_done)
            else:
                logger.warning(
                    f"[TRIGGER] Ping returned HTTP {resp.status_code}"
                )
                return False
    except Exception as exc:
        logger.warning(f"[TRIGGER] Ping failed: {exc}")
        return False


def _config_available() -> bool:
    """Return True if config.json exists and can be loaded."""
    try:
        from backend.config import load_config
        load_config()
        return True
    except Exception:
        return False


async def _recover_router() -> bool:
    """
    Re-initialize the AI router if it is not RUNNING.
    Returns True if the router is RUNNING after the attempt.
    """
    registry = get_module_registry()
    state = registry.get_state("router")

    if state == ModuleState.RUNNING:
        return True

    if state == ModuleState.DISABLED:
        # Router was explicitly disabled — do not touch it.
        return False

    logger.info(
        f"[TRIGGER] Router state={state} — attempting re-initialization"
    )
    try:
        from backend.config import load_config
        from backend.api import initialize_router
        cfg = load_config()
        initialize_router(cfg)
        new_state = registry.get_state("router")
        if new_state == ModuleState.RUNNING:
            logger.info("[TRIGGER] Router re-initialized successfully → RUNNING")
            return True
        else:
            logger.warning(
                f"[TRIGGER] Router still not RUNNING after re-init "
                f"(state={new_state})"
            )
            return False
    except Exception as exc:
        logger.error(f"[TRIGGER] Router recovery failed: {exc}", exc_info=True)
        return False


async def _recover_messaging() -> bool:
    """
    For each messaging platform that is not RUNNING and not DISABLED:
      1. Stop the existing (possibly dead) platform instance.
      2. Re-initialize.
      3. Start polling.

    Returns True if all previously-enabled platforms are RUNNING.
    """
    registry = get_module_registry()

    # Identify which platforms need recovery.
    # We only look at platforms that have an entry in the registry —
    # platforms that have never been initialized have no registry entry.
    from backend.messaging import MESSAGING_PLATFORMS
    needs_recovery = []
    for name in MESSAGING_PLATFORMS:
        state = registry.get_state(name)
        if state is None:
            # Never initialized — skip; startup or /api/config/apply handles it.
            continue
        if state == ModuleState.DISABLED:
            continue
        if state != ModuleState.RUNNING:
            needs_recovery.append(name)
        else:
            # RUNNING — but verify the poll task is actually alive.
            try:
                from backend.api import _messaging_platforms  # type: ignore
                platform = _messaging_platforms.get(name)
                if platform is not None:
                    poll_task = getattr(platform, "_poll_task", None)
                    if poll_task is not None and poll_task.done():
                        # Task finished unexpectedly — treat as needs recovery.
                        logger.warning(
                            f"[TRIGGER] {name} poll task is done unexpectedly "
                            f"(cancelled={poll_task.cancelled()}) — recovering"
                        )
                        needs_recovery.append(name)
            except Exception:
                pass

    if not needs_recovery:
        return True

    logger.info(f"[TRIGGER] Messaging recovery needed for: {needs_recovery}")

    try:
        from backend.config import load_config
        from backend.api import (
            stop_messaging,
            initialize_messaging,
            start_messaging,
        )
        cfg = load_config()

        # Stop existing platforms (cancels zombie tasks).
        try:
            await stop_messaging()
        except Exception as exc:
            logger.warning(f"[TRIGGER] stop_messaging warning: {exc}")

        # Re-initialize all messaging (not just the broken ones — the
        # function rebuilds _messaging_platforms from scratch each time).
        initialize_messaging(cfg)

        # Start polling for the newly initialized platforms.
        await start_messaging()

        # Verify.
        all_running = True
        for name in needs_recovery:
            new_state = registry.get_state(name)
            if new_state == ModuleState.RUNNING:
                logger.info(f"[TRIGGER] {name} recovered → RUNNING")
            else:
                logger.warning(
                    f"[TRIGGER] {name} still not RUNNING after recovery "
                    f"(state={new_state})"
                )
                all_running = False

        return all_running

    except Exception as exc:
        logger.error(
            f"[TRIGGER] Messaging recovery failed: {exc}", exc_info=True
        )
        return False


async def _run_recovery_cycle() -> None:
    """
    Run a full recovery cycle: router + messaging.
    Called after sleep detection or after a failed health ping.
    """
    logger.info("[TRIGGER] Starting recovery cycle")

    if not _config_available():
        logger.info(
            "[TRIGGER] config.json not present — skipping recovery "
            "(complete the Wizard first)"
        )
        return

    router_ok = await _recover_router()
    messaging_ok = await _recover_messaging()

    if router_ok and messaging_ok:
        logger.info("[TRIGGER] Recovery cycle complete — all modules RUNNING")
    else:
        logger.warning(
            f"[TRIGGER] Recovery cycle partial — "
            f"router_ok={router_ok} messaging_ok={messaging_ok}"
        )


async def _keepalive_loop(port: int) -> None:
    """
    Main keepalive loop.

    Ticks every PING_INTERVAL seconds.  Each tick:
      1. Pings /health on the local port.
      2. If startup is done, checks module states and recovers as needed.
      3. Detects sleep/wake events via monotonic clock drift.
    """
    logger.info(
        f"[TRIGGER] Keepalive loop started | "
        f"ping_interval={PING_INTERVAL}s | port={port}"
    )

    last_tick = time.monotonic()

    while True:
        try:
            # ── Sleep / wait ─────────────────────────────────────────────────
            await asyncio.sleep(PING_INTERVAL)

            now = time.monotonic()
            elapsed = now - last_tick
            last_tick = now

            # ── Sleep detection ──────────────────────────────────────────────
            # If the gap is more than 1.5× expected, the process was suspended.
            sleep_threshold = PING_INTERVAL * SLEEP_DETECTION_MULTIPLIER
            if elapsed > sleep_threshold:
                logger.warning(
                    f"[TRIGGER] SLEEP DETECTED — elapsed={elapsed:.0f}s "
                    f"expected≤{sleep_threshold:.0f}s — "
                    f"running immediate recovery before next ping"
                )
                await _run_recovery_cycle()

            # ── Keepalive ping ───────────────────────────────────────────────
            alive = await _ping_health(port)

            if not alive:
                # Backend didn't respond or startup isn't done yet.
                # Wait a short interval and try recovery if config exists.
                logger.warning(
                    "[TRIGGER] Health ping failed or startup not done — "
                    f"waiting {RECOVERY_RETRY_DELAY}s then recovering"
                )
                await asyncio.sleep(RECOVERY_RETRY_DELAY)
                await _run_recovery_cycle()
                continue

            # ── Module state check ────────────────────────────────────────────
            # Only run if config is available; otherwise modules are
            # legitimately in WAITING_FOR_CONFIG and recovery would be a no-op.
            if _config_available():
                registry = get_module_registry()
                router_state = registry.get_state("router")
                needs_recovery = (
                    router_state is not None
                    and router_state != ModuleState.RUNNING
                    and router_state != ModuleState.DISABLED
                )

                if not needs_recovery:
                    # Check messaging poll tasks too.
                    try:
                        from backend.api import _messaging_platforms  # type: ignore
                        for name, platform in _messaging_platforms.items():
                            poll_task = getattr(platform, "_poll_task", None)
                            if poll_task is not None and poll_task.done():
                                needs_recovery = True
                                logger.warning(
                                    f"[TRIGGER] {name} poll task is done — "
                                    "triggering recovery"
                                )
                                break
                    except Exception:
                        pass

                if needs_recovery:
                    logger.info(
                        "[TRIGGER] Module recovery needed after ping check"
                    )
                    await _run_recovery_cycle()
                else:
                    logger.info(
                        "[TRIGGER] All modules healthy — no recovery needed"
                    )

        except asyncio.CancelledError:
            logger.info("[TRIGGER] Keepalive loop cancelled — shutting down")
            break
        except Exception as exc:
            # Never let the loop die silently.
            logger.error(
                f"[TRIGGER] Unexpected error in keepalive loop: {exc}",
                exc_info=True,
            )
            # Back off before retrying so we don't spam logs on repeated errors.
            await asyncio.sleep(60)


# ── Public API ────────────────────────────────────────────────────────────────

def start_keepalive(port: int) -> asyncio.Task:
    """
    Launch the keepalive loop as a background asyncio Task.

    Must be called from within a running event loop (e.g. inside the
    FastAPI lifespan context after startup_async() completes).

    Args:
        port: The port the FastAPI server is listening on.
              Passed to the health ping so it always hits the right process.

    Returns:
        The asyncio.Task — the lifespan handler stores it so it can be
        cancelled on shutdown.
    """
    global _task, _started_at
    _started_at = time.monotonic()
    _task = asyncio.create_task(_keepalive_loop(port))

    def _on_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            logger.error(
                f"[TRIGGER] Keepalive task terminated: {t.exception()!r}"
            )

    _task.add_done_callback(_on_done)
    logger.info(f"[TRIGGER] Keepalive task created | task={_task!r}")
    return _task


def stop_keepalive() -> None:
    """Cancel the keepalive task during server shutdown."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        logger.info("[TRIGGER] Keepalive task cancelled")
    _task = None
