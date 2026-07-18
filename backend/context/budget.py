"""
Context budget tracking for the Context Engine.

Tracks how many tokens of context are in use against a configurable maximum,
so the UI and the auto-pruner can react before the window overflows.

Token counting is a deterministic heuristic (≈4 characters per token) which is
provider-agnostic and always available — no tokenizer download required.
"""

from dataclasses import dataclass, field
from typing import Dict, Any


def estimate_tokens(text: str) -> int:
    """Rough, provider-agnostic token estimate (≈4 chars / token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


@dataclass
class ContextBudget:
    """Live snapshot of context-window usage."""

    max_tokens: int = 128_000
    prune_threshold: float = 0.85
    current_tokens: int = 0

    def remaining(self) -> int:
        return max(0, self.max_tokens - self.current_tokens)

    def percentage(self) -> float:
        if self.max_tokens <= 0:
            return 0.0
        return round(min(100.0, self.current_tokens / self.max_tokens * 100.0), 2)

    def soft_limit(self) -> int:
        """Token ceiling at which auto-pruning kicks in."""
        return int(self.max_tokens * self.prune_threshold)

    def exceeds(self) -> bool:
        return self.current_tokens > self.soft_limit()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "current_tokens": self.current_tokens,
            "remaining": self.remaining(),
            "percentage": self.percentage(),
            "prune_threshold": self.prune_threshold,
            "soft_limit": self.soft_limit(),
        }


__all__ = ["ContextBudget", "estimate_tokens"]
