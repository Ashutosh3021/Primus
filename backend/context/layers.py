"""
Context layers for the Primus Context Engine.

The Context Engine is the core asset of Primus.  It maintains ONE shared
memory (never provider-specific) organised into eight explicit layers.  Each
layer has a fixed priority used by the Prompt Builder when assembling a prompt
(highest priority first).
"""

from enum import Enum
from typing import Dict, Any, List


class ContextLayer(str, Enum):
    """The eight layered memory regions of the Context Engine."""

    PERSONA = "persona"
    USER_FACTS = "user_facts"
    LONG_TERM = "long_term"
    CONVERSATION_SUMMARY = "conversation_summary"
    ACTIVE_SESSION = "active_session"
    SKILLS = "skills"
    COMPACT_MEMORY = "compact_memory"
    PROJECT_MEMORY = "project_memory"


# Layers that are durably persisted in the `memories` table.
# ACTIVE_SESSION is the live conversation (stored in `conversations`) and is
# handled separately, but it still participates in the budget / priority order.
PERSISTED_LAYERS: List[ContextLayer] = [
    ContextLayer.PERSONA,
    ContextLayer.USER_FACTS,
    ContextLayer.LONG_TERM,
    ContextLayer.CONVERSATION_SUMMARY,
    ContextLayer.SKILLS,
    ContextLayer.COMPACT_MEMORY,
    ContextLayer.PROJECT_MEMORY,
]


# Priority order for prompt construction — highest priority first.
# The Prompt Builder walks this list so the most important context is always
# placed earliest in the prompt.
LAYER_PRIORITY: List[ContextLayer] = [
    ContextLayer.PERSONA,               # identity / behaviour (not implemented yet)
    ContextLayer.USER_FACTS,            # who the user is
    ContextLayer.PROJECT_MEMORY,        # project context & decisions
    ContextLayer.LONG_TERM,             # durable knowledge & decisions
    ContextLayer.SKILLS,                # learned procedures & recipes
    ContextLayer.COMPACT_MEMORY,        # archived /compact summaries
    ContextLayer.CONVERSATION_SUMMARY,  # current rolling summary
    ContextLayer.ACTIVE_SESSION,        # live recent messages (pruned first)
]


LAYER_META: Dict[ContextLayer, Dict[str, Any]] = {
    ContextLayer.PERSONA: {
        "title": "Persona",
        "description": "Assistant identity & behaviour.",
        "persistent": True,
    },
    ContextLayer.USER_FACTS: {
        "title": "User Facts",
        "description": "Durable facts about the user.",
        "persistent": True,
    },
    ContextLayer.PROJECT_MEMORY: {
        "title": "Project Memory",
        "description": "Project-specific context & decisions.",
        "persistent": True,
    },
    ContextLayer.LONG_TERM: {
        "title": "Long Term Memory",
        "description": "Durable knowledge & decisions.",
        "persistent": True,
    },
    ContextLayer.SKILLS: {
        "title": "Skills",
        "description": "Learned procedures & recipes.",
        "persistent": True,
    },
    ContextLayer.COMPACT_MEMORY: {
        "title": "Compact Memory",
        "description": "Archived conversation summaries from /compact.",
        "persistent": True,
    },
    ContextLayer.CONVERSATION_SUMMARY: {
        "title": "Conversation Summary",
        "description": "Current rolling conversation summary.",
        "persistent": True,
    },
    ContextLayer.ACTIVE_SESSION: {
        "title": "Active Session",
        "description": "Live recent messages (auto-pruned).",
        "persistent": False,
    },
}


def is_valid_layer(value: str) -> bool:
    """Return True if `value` names a known context layer."""
    return value in {layer.value for layer in ContextLayer}


__all__ = [
    "ContextLayer",
    "PERSISTED_LAYERS",
    "LAYER_PRIORITY",
    "LAYER_META",
    "is_valid_layer",
]
