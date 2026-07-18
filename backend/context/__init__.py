"""
Context Engine package — Primus's core asset.

Exposes the layered memory model, the budget tracker, the priority-order
prompt builder, and the engine that ties them together.
"""

from backend.context.layers import (
    ContextLayer,
    PERSISTED_LAYERS,
    LAYER_PRIORITY,
    LAYER_META,
    is_valid_layer,
)
from backend.context.budget import ContextBudget, estimate_tokens
from backend.context.prompt_builder import PromptBuilder
from backend.context.store import LayeredMemoryStore, DEFAULT_USER
from backend.context.engine import ContextEngine, SUMMARY_KEY

__all__ = [
    "ContextLayer",
    "PERSISTED_LAYERS",
    "LAYER_PRIORITY",
    "LAYER_META",
    "is_valid_layer",
    "ContextBudget",
    "estimate_tokens",
    "PromptBuilder",
    "LayeredMemoryStore",
    "DEFAULT_USER",
    "ContextEngine",
    "SUMMARY_KEY",
]
