
"""
Internal API module for Primus backend.
"""

from backend.config import Config
from backend.providers.base import Message, ChatCompletion
from backend.router import AIRouter
from backend.secrets import get_secret
from backend.exceptions import ConfigInvalidError
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
    CronStore
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
import backend.desktop.tools

logger = get_errors_logger(__name__)

# Singleton instances
_router = None
_memory_store = None
_conversation_store = None
_context_engine = None
_tool_manager = None
_messaging_platforms = {}
_job_manager = None
_notification_engine = None
_scheduler = None
_desktop_connector = None


def initialize_router(config):
    """Initialize the AI router with the given config."""
    global _router
    try:
        api_key = get_secret(config.provider.secret_ref)
        _router = AIRouter(config.provider.name, api_key, config.provider.model)
        logger.info("AI router initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize AI router: {e}", exc_info=True)
        raise


def initialize_memory():
    """Initialize memory stores."""
    global _memory_store, _conversation_store, _context_engine
    _memory_store = MemoryStore()
    _conversation_store = ConversationStore()
    _context_engine = ContextEngine()
    logger.info("Memory system initialized")


def initialize_tools(config):
    """Initialize tool manager."""
    global _tool_manager
    _tool_manager = ToolManager({
        "web_search": config.tools.web_search,
        "browser": config.tools.browser,
        "terminal": config.tools.terminal,
        "filesystem": config.tools.terminal,
        "python": config.tools.terminal,
        "git": config.tools.terminal,
        "ollama": config.tools.terminal,
        "docker": config.tools.terminal
    })
    logger.info("Tool system initialized")


def initialize_messaging(config):
    """Initialize messaging platforms."""
    global _messaging_platforms
    for name, cls in MESSAGING_PLATFORMS.items():
        platform_config = getattr(config.messaging, name, {})
        if platform_config.get("enabled", False):
            try:
                # Load secret token if using secret ref
                if "secret_ref" in platform_config:
                    token = get_secret(platform_config["secret_ref"])
                    platform_config["bot_token"] = token

                platform = cls(platform_config)
                _messaging_platforms[name] = platform
                logger.info(f"Initialized messaging platform: {name}")

                # Set handler
                platform.set_message_handler(_handle_incoming_message)
            except Exception as e:
                logger.error(f"Failed to initialize {name}: {e}", exc_info=True)


def initialize_jobs(config):
    """Initialize job manager, notification engine, scheduler."""
    global _job_manager, _notification_engine, _scheduler
    _job_manager = JobManager()
    _notification_engine = NotificationEngine({})
    _scheduler = Scheduler(_job_manager, _notification_engine)
    logger.info("Job system initialized")


def initialize_desktop(config):
    """Initialize desktop connector."""
    global _desktop_connector
    desktop_config = getattr(config, "desktop", {})
    _desktop_connector = DesktopConnector(desktop_config)
    logger.info("Desktop system initialized")


async def _handle_incoming_message(msg):
    """Handle an incoming message from any platform."""
    try:
        # Build prompt with context
        prompt = await build_prompt(msg.user_id, msg.conversation_id, msg.content)

        # Get chat completion
        messages = [Message(role="user", content=prompt)]
        completion = await chat(messages)

        # Save interaction
        await add_interaction(msg.user_id, msg.conversation_id, msg.content, completion.content)

        return completion.content

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        return f"Sorry, something went wrong: {str(e)}"


async def chat(
    messages,
    temperature=0.7,
    max_tokens=None,
    **kwargs
):
    """Internal API method for sending chat messages."""
    if _router is None:
        raise ConfigInvalidError("AI router not initialized. Call initialize_router first.")

    return await _router.chat(messages, temperature, max_tokens, **kwargs)


async def chat_stream(
    messages,
    temperature=0.7,
    max_tokens=None,
    **kwargs
):
    """Internal API method for streaming chat messages."""
    if _router is None:
        raise ConfigInvalidError("AI router not initialized. Call initialize_router first.")

    async for chunk in _router.chat_stream(messages, temperature, max_tokens, **kwargs):
        yield chunk


def get_capabilities():
    """Get the capabilities of the current provider and desktop."""
    caps = {}
    if _router:
        caps["provider"] = _router.get_capabilities()
    if _desktop_connector:
        caps["desktop"] = _desktop_connector.capabilities
    return caps


async def add_memory(entry):
    """Add a memory entry."""
    if _memory_store is None:
        raise ConfigInvalidError("Memory not initialized. Call initialize_memory first.")
    return await _memory_store.add(entry)


async def get_memory(user_id, layer, key):
    """Get a memory entry."""
    if _memory_store is None:
        raise ConfigInvalidError("Memory not initialized. Call initialize_memory first.")
    return await _memory_store.get(user_id, layer, key)


async def get_all_memories(user_id, layer=None):
    """Get all memories."""
    if _memory_store is None:
        raise ConfigInvalidError("Memory not initialized. Call initialize_memory first.")
    return await _memory_store.get_all(user_id, layer)


async def delete_memory(user_id, layer, key):
    """Delete a memory entry."""
    if _memory_store is None:
        raise ConfigInvalidError("Memory not initialized. Call initialize_memory first.")
    return await _memory_store.delete(user_id, layer, key)


async def build_prompt(user_id, conversation_id, query):
    """Build a prompt using context engine."""
    if _context_engine is None:
        raise ConfigInvalidError("Context engine not initialized. Call initialize_memory first.")
    return await _context_engine.build_prompt(user_id, conversation_id, query)


async def add_interaction(user_id, conversation_id, user_message, assistant_response):
    """Add an interaction to conversation history."""
    if _context_engine is None:
        raise ConfigInvalidError("Context engine not initialized. Call initialize_memory first.")
    await _context_engine.add_interaction(user_id, conversation_id, user_message, assistant_response)


async def start_messaging():
    """Start all enabled messaging platforms."""
    for name, platform in _messaging_platforms.items():
        try:
            await platform.start()
        except Exception as e:
            logger.error(f"Failed to start {name}: {e}", exc_info=True)


async def stop_messaging():
    """Stop all enabled messaging platforms."""
    for name, platform in _messaging_platforms.items():
        try:
            await platform.stop()
        except Exception as e:
            logger.error(f"Failed to stop {name}: {e}", exc_info=True)


async def start_jobs():
    """Start job manager and scheduler."""
    if _job_manager and _scheduler:
        await _job_manager.start()
        await _scheduler.start()


async def stop_jobs():
    """Stop job manager and scheduler."""
    if _job_manager and _scheduler:
        await _job_manager.stop()
        await _scheduler.stop()


async def start_desktop():
    """Start desktop connector."""
    if _desktop_connector:
        await _desktop_connector.start()


async def stop_desktop():
    """Stop desktop connector."""
    if _desktop_connector:
        await _desktop_connector.stop()


async def submit_job(job):
    """Submit a job."""
    if _job_manager is None:
        raise ConfigInvalidError("Job manager not initialized")
    return await _job_manager.submit(job)


def get_health_status():
    """Get current health status."""
    return get_health_checker().run_all_checks()


def get_metrics():
    """Get current metrics."""
    return get_metrics_registry().get_metrics()


def get_diagnostics():
    """Get current diagnostics."""
    diag = get_diagnostics_manager()
    return {
        "startup": diag.get_startup_diagnostic(),
        "uptime": diag.get_uptime()
    }


def get_recovery_state():
    """Get current recovery state."""
    return get_recovery_manager().get_recovery_state()


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
    "get_recovery_state"
]

