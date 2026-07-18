"""
Curated model catalog for every supported Primus provider.

Used for:
  * validating a user-selected model (requirement: NO fuzzy matching —
    an unknown model must be rejected with a clear "available models" list)
  * populating the Wizard's per-provider model selector
  * providing sensible defaults per provider
  * rule-based auto routing (see backend/router/auto_router.py)

The catalog is intentionally a *static allow-list*.  We never guess or
silently substitute a model — if it is not in this list (and the provider is
not Ollama) the selection is rejected.
"""

from typing import Dict, List

# Known model IDs per provider.  These are real, currently-served model IDs.
MODEL_CATALOG: Dict[str, List[str]] = {
    "openrouter": [
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-opus-4-5",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "google/gemini-2.5-flash",
        "google/gemini-2.5-pro",
        "deepseek/deepseek-r1",
        "moonshotai/kimi-k2",
        "meta-llama/llama-3.3-70b-instruct",
        "qwen/qwen-2.5-72b-instruct",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "o3",
        "o4-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
    ],
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-1.5-pro",
    ],
    "anthropic": [
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-3-5-sonnet",
        "claude-3-5-haiku",
    ],
    "moonshot": [
        "kimi-k2",
        "moonshot-v1-8k",
        "moonshot-v1-32k",
    ],
    "glm": [
        "glm-4",
        "glm-4-flash",
        "glm-4-plus",
    ],
    "groq": [
        "llama-3.3-70b-versatile",
        "gemma2-9b-it",
        "llama-3.1-8b-instant",
        "moonshotai/kimi-k2-instruct",
    ],
    # Ollama runs locally — the set of available models is whatever the user
    # has pulled.  We therefore cannot enumerate them; is_model_available()
    # treats Ollama as "any model allowed" (the user is responsible for having
    # it installed locally).  The list is empty so the UI shows a free-text box.
    "ollama": [],
}

# Sensible default model per provider (used when a provider has no stored
# default_model yet, and as the first auto-routing candidate).
DEFAULT_MODEL_BY_PROVIDER: Dict[str, str] = {
    "openrouter": "anthropic/claude-sonnet-4-5",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-5",
    "moonshot": "kimi-k2",
    "glm": "glm-4",
    "groq": "llama-3.3-70b-versatile",
    "ollama": "llama3.2",
}


def get_model_catalog(provider: str) -> List[str]:
    """Return the known model list for a provider (empty for Ollama)."""
    return list(MODEL_CATALOG.get(provider, []))


def get_default_model(provider: str) -> str:
    """Return the sensible default model for a provider."""
    return DEFAULT_MODEL_BY_PROVIDER.get(provider, "")


def is_model_available(provider: str, model: str) -> bool:
    """
    Return True if `model` is a valid choice for `provider`.

    Ollama is special: any model string is accepted because we cannot know
    which local models the user has pulled.  Every other provider must match
    an entry in MODEL_CATALOG exactly — no fuzzy matching, ever.
    """
    if not model:
        return False
    if provider == "ollama":
        return True
    return model in MODEL_CATALOG.get(provider, [])
