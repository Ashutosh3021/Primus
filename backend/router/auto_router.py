"""
Rule-Based Auto Routing for Primus.

When Auto Mode is enabled, every chat prompt is:

  1. CLASSIFIED into one of nine task categories from keyword heuristics.
  2. Mapped to an ordered list of (provider, model) candidates.
  3. ROUTED to the first candidate whose provider is configured & whose model
     is available.  If the preferred provider is unavailable, the next
     candidate in the chain is tried — automatic fallback (A → B → C).

No ML, no external calls: classification is deterministic keyword scoring, so
the behaviour is predictable and testable.
"""

from typing import Dict, List, Optional, Tuple

from backend.providers.base import ChatCompletion, Message
from backend.providers.manager import ProviderManager
from backend.logger import get_ai_requests_logger

logger = get_ai_requests_logger(__name__)


# The nine supported task categories (requirement 6).
TASK_CATEGORIES = [
    "coding",
    "reasoning",
    "writing",
    "summarization",
    "translation",
    "vision",
    "long_context",
    "speed",
    "balanced",
]

# Keyword heuristics per category.  Order = evaluation priority (most specific
# first).  A prompt is scored per category; the highest-scoring category wins.
_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "vision": [
        "image", "picture", "photo", "screenshot", "describe this image",
        "what's in this", "ocr", "visual", "diagram", "chart", "extract text from",
    ],
    "translation": [
        "translate", "translation", "in french", "in spanish", "in german",
        "in japanese", "in chinese", "traduce", "übersetze", "翻訳", "翻译",
        "to english", "convert to", "language",
    ],
    "coding": [
        "code", "function", "bug", "debug", "python", "javascript", "typescript",
        "implement", "refactor", "regex", "api", "compile", "script", "sql",
        "github", "class ", "syntax", "algorithm", "dockerfile", "terminal command",
    ],
    "reasoning": [
        "why", "explain the logic", "step by step", "prove", "math problem",
        "puzzle", "logic", "theorem", "deduce", "reason about", "complex",
    ],
    "summarization": [
        "summarize", "summary", "tldr", "key points", "condense", "abstract",
        "bullet points", "overview of", "recap",
    ],
    "long_context": [
        "long document", "entire file", "large text", "whole book", "many pages",
        "lengthy", "full transcript", "entire conversation", "paste the whole",
    ],
    "speed": [
        "quick", "fast", "quickly", "just tell me", "short answer", "briefly",
        "one word", "in a sentence", "asap", "rapid",
    ],
    "writing": [
        "write", "essay", "blog", "email", "poem", "story", "article", "draft",
        "letter", "rewrite", "paraphrase", "copywrite", "caption", "tweet",
        "speech",
    ],
}

# Fallback preference chains per category: ordered (provider, model) pairs.
# Selection walks the chain and picks the first configured & available entry.
_ROUTING_TABLE: Dict[str, List[Tuple[str, str]]] = {
    "coding": [
        ("openrouter", "anthropic/claude-sonnet-4-5"),
        ("anthropic", "claude-sonnet-4-5"),
        ("openai", "gpt-4o"),
        ("gemini", "gemini-2.5-pro"),
    ],
    "reasoning": [
        ("anthropic", "claude-opus-4-5"),
        ("openrouter", "anthropic/claude-opus-4-5"),
        ("openai", "o3"),
        ("gemini", "gemini-2.5-pro"),
    ],
    "writing": [
        ("openai", "gpt-4o"),
        ("anthropic", "claude-sonnet-4-5"),
        ("openrouter", "anthropic/claude-sonnet-4-5"),
        ("gemini", "gemini-2.5-flash"),
    ],
    "summarization": [
        ("gemini", "gemini-2.5-flash"),
        ("openai", "gpt-4o-mini"),
        ("openrouter", "anthropic/claude-sonnet-4-5"),
        ("groq", "llama-3.3-70b-versatile"),
    ],
    "translation": [
        ("gemini", "gemini-2.5-flash"),
        ("openai", "gpt-4o"),
        ("openrouter", "anthropic/claude-sonnet-4-5"),
        ("glm", "glm-4"),
    ],
    "vision": [
        ("openai", "gpt-4o"),
        ("gemini", "gemini-2.5-flash"),
        ("anthropic", "claude-sonnet-4-5"),
        ("openrouter", "openai/gpt-4o"),
    ],
    "long_context": [
        ("gemini", "gemini-2.5-pro"),
        ("openrouter", "anthropic/claude-opus-4-5"),
        ("anthropic", "claude-opus-4-5"),
        ("gemini", "gemini-1.5-pro"),
    ],
    "speed": [
        ("groq", "llama-3.3-70b-versatile"),
        ("openai", "gpt-4o-mini"),
        ("gemini", "gemini-2.5-flash"),
        ("moonshot", "kimi-k2"),
    ],
    # Balanced: respect the user's currently-selected provider/model first,
    # then fall back through the general-purpose providers.
    "balanced": [
        ("__current__", "__current__"),
        ("openrouter", "anthropic/claude-sonnet-4-5"),
        ("anthropic", "claude-sonnet-4-5"),
        ("openai", "gpt-4o"),
        ("gemini", "gemini-2.5-flash"),
    ],
}


class AutoRouter:
    """Classifies prompts and routes them across configured providers."""

    def __init__(self, manager: ProviderManager, current_provider: Optional[str] = None):
        self._manager = manager
        self._current_provider = current_provider

    # ── Classification ───────────────────────────────────────────────────────

    def classify(self, prompt: str) -> str:
        """
        Score the prompt against each category's keyword list and return the
        highest-scoring category.  Ties resolve to the most-specific category
        (the order in _CATEGORY_KEYWORDS).  Defaults to 'balanced'.
        """
        text = (prompt or "").lower()
        if not text.strip():
            return "balanced"

        best_category = "balanced"
        best_score = 0
        # Iterate in priority order so the first category to reach the top
        # score wins ties.
        for category in _CATEGORY_KEYWORDS:
            score = sum(1 for kw in _CATEGORY_KEYWORDS[category] if kw in text)
            if score > best_score:
                best_score = score
                best_category = category

        return best_category

    # ── Selection (with fallback chain) ──────────────────────────────────────

    def select(self, category: str) -> Optional[Tuple[str, str]]:
        """
        Return the first (provider, model) candidate for `category` that is
        configured and whose model is available.  Returns None if nothing
        matches (caller should fall back to the current provider router).
        """
        chain = _ROUTING_TABLE.get(category, _ROUTING_TABLE["balanced"])

        for provider, model in chain:
            if provider == "__current__":
                provider = self._current_provider
                model = None  # use the provider's stored default_model
            if not provider:
                continue
            if not self._manager.is_configured(provider):
                continue
            # Resolve the model: if the chain used a placeholder, take the
            # provider's stored default.
            resolved_model = model or self._manager.get_default_model(provider)
            if not resolved_model:
                continue
            if not self._manager.is_model_available(provider, resolved_model):
                # Try the provider's stored default as a final attempt.
                fallback = self._manager.get_default_model(provider)
                if fallback and self._manager.is_model_available(provider, fallback):
                    return (provider, fallback)
                continue
            return (provider, resolved_model)

        return None

    # ── Routing ──────────────────────────────────────────────────────────────

    async def route(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Tuple[ChatCompletion, Dict[str, str]]:
        """
        Classify + select + call.  Returns (completion, route_info).

        route_info = {
            "mode":     "auto",
            "category": <classified category>,
            "provider": <chosen provider name>,
            "model":    <chosen model>,
        }

        If no configured candidate exists, returns None for the selection and
        the caller is expected to fall back to the manual router.
        """
        prompt_text = "\n".join(
            m.content for m in messages if m.role in ("user", "system")
        )
        category = self.classify(prompt_text)
        selection = self.select(category)

        if selection is None:
            return None, {  # type: ignore[return-value]
                "mode": "auto",
                "category": category,
                "provider": None,
                "model": None,
            }

        provider_name, model = selection
        instance = self._manager.build_provider(provider_name, model)
        completion = await instance.chat_completion(
            messages, temperature=temperature, max_tokens=max_tokens, **kwargs
        )
        # Normalise provider name to the registry key for consistent metrics /
        # API responses (providers themselves report their class name).
        completion.provider = provider_name
        return completion, {
            "mode": "auto",
            "category": category,
            "provider": provider_name,
            "model": model,
        }
