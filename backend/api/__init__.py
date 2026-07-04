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

from backend.config import Config
from backend.providers.base import Message, ChatCompletion
from backend.router import AIRouter
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
from backend.memory import ContextEngine
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

_registry = get_module_registry()


# ── Router ───────────────────────────────────────────────────────────────────

def initialize_router(config: Config) -> None:
    """
    Initialise the AI router.

    Transitions:
      secret present  → RUNNING
      secret missing  → WAITING_FOR_CONFIG (startup continues)
      other error     → re-raised (unexpected, must surface)
    """
    global _router
    try:
        api_key = get_secret(config.provider.secret_ref)
        _router = AIRouter(config.provider.name, api_key, config.provider.model)
        _registry.set_running("router")
        logger.info("AI router initialised successfully")
    except SecretNotFoundError as exc:
        _router = None
        _registry.set_waiting("router", config.provider.secret_ref)
        logger.warning(
            f"[WARNING] AI Router | Waiting for configuration | "
            f"Missing secret: {config.provider.secret_ref}"
        )
    except Exception:
        raise


# ── Memory ───────────────────────────────────────────────────────────────────

def initialize_memory() -> None:
    """Initialise memory stores (no secrets required; always RUNNING)."""
    global _memory_store, _conversation_store, _context_engine
    _memory_store = MemoryStore()
    _conversation_store = ConversationStore()
    _context_engine = ContextEngine()
    _registry.set_running("memory")
    logger.info("Memory system initialised")


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
      not enabled          → DISABLED
      enabled, no secret   → WAITING_FOR_CONFIG
      enabled, secret ok   → RUNNING
    """
    global _messaging_platforms
    _messaging_platforms = {}

    for name, cls in MESSAGING_PLATFORMS.items():
        platform_config: dict = dict(getattr(config.messaging, name, {}) or {})

        if not platform_config.get("enabled", False):
            _registry.set_disabled(name)
            continue

        secret_ref: str | None = platform_config.get("secret_ref")
        if secret_ref:
            try:
                token = get_secret(secret_ref)
                platform_config["bot_token"] = token
            except SecretNotFoundError:
                _registry.set_waiting(name, secret_ref)
                logger.warning(
                    f"[WARNING] {name.capitalize()} Messaging | "
                    f"Waiting for configuration | Missing secret: {secret_ref}"
                )
                continue
            except Exception:
                raise

        try:
            platform = cls(platform_config)
            platform.set_message_handler(_handle_incoming_message)
            _messaging_platforms[name] = platform
            _registry.set_running(name)
            logger.info(f"Initialised messaging platform: {name}")
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
    """Handle an incoming message from any platform."""
    try:
        prompt = await build_prompt(msg.user_id, msg.conversation_id, msg.content)
        messages = [Message(role="user", content=prompt)]
        completion = await chat(messages)
        await add_interaction(
            msg.user_id, msg.conversation_id, msg.content, completion.content
        )
        return completion.content
    except Exception as exc:
        logger.error(f"Error handling message: {exc}", exc_info=True)
        return f"Sorry, something went wrong: {str(exc)}"


# ── Chat ─────────────────────────────────────────────────────────────────────

async def chat(messages, temperature=0.7, max_tokens=None, **kwargs):
    """Send a chat request through the active router."""
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
    return await _router.chat(messages, temperature, max_tokens, **kwargs)


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


async def build_prompt(user_id, conversation_id, query):
    if _context_engine is None:
        raise ConfigInvalidError("Context engine not initialised.")
    return await _context_engine.build_prompt(user_id, conversation_id, query)


async def add_interaction(user_id, conversation_id, user_message, assistant_response):
    if _context_engine is None:
        raise ConfigInvalidError("Context engine not initialised.")
    await _context_engine.add_interaction(
        user_id, conversation_id, user_message, assistant_response
    )


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
    "get_capabilities",
    "add_memory",
    "get_memory",
    "get_all_memories",
    "delete_memory",
    "build_prompt",
    "add_interaction",
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
