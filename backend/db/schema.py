"""
Database schema definitions for Primus.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum


class MemoryLayer(str, Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    PROJECT = "project"
    PREFERENCE = "preference"


@dataclass
class MemoryEntry:
    id: Optional[int] = None
    user_id: str = "default"
    layer: MemoryLayer = MemoryLayer.LONG_TERM
    key: str = ""
    value: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ConversationMessage:
    id: Optional[int] = None
    user_id: str = "default"
    conversation_id: str = "default"
    role: str = "user"  # user, assistant, system
    content: str = ""
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


CREATE_TABLE_MEMORIES = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, layer, key)
);
"""

CREATE_TABLE_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
);
"""

CREATE_INDEX_MEMORIES = """
CREATE INDEX IF NOT EXISTS idx_memories_user_layer ON memories(user_id, layer);
CREATE INDEX IF NOT EXISTS idx_conversations_user_conversation ON conversations(user_id, conversation_id);
"""

ALL_TABLES = [CREATE_TABLE_MEMORIES, CREATE_TABLE_CONVERSATIONS, CREATE_INDEX_MEMORIES]
