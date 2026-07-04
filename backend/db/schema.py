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


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


@dataclass
class Job:
    id: Optional[int] = None
    job_id: str = ""
    name: str = ""
    user_id: str = "default"
    status: JobStatus = JobStatus.PENDING
    params: Dict[str, Any] = field(default_factory=dict)
    checkpoint: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3
    result: Optional[str] = None
    error: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class CronSchedule:
    id: Optional[int] = None
    cron_id: str = ""
    name: str = ""
    user_id: str = "default"
    job_name: str = ""
    cron_expr: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Notification:
    id: Optional[int] = None
    notification_id: str = ""
    user_id: str = "default"
    channel: str = ""
    title: str = ""
    content: str = ""
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


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

CREATE_TABLE_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    params TEXT,
    checkpoint TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    result TEXT,
    error TEXT,
    scheduled_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TABLE_CRON_SCHEDULES = """
CREATE TABLE IF NOT EXISTS cron_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cron_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    job_name TEXT NOT NULL,
    cron_expr TEXT NOT NULL,
    params TEXT,
    enabled BOOLEAN DEFAULT 1,
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TABLE_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_INDEX_MEMORIES = """
CREATE INDEX IF NOT EXISTS idx_memories_user_layer ON memories(user_id, layer);
CREATE INDEX IF NOT EXISTS idx_conversations_user_conversation ON conversations(user_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_cron_enabled ON cron_schedules(enabled);
CREATE INDEX IF NOT EXISTS idx_cron_next_run ON cron_schedules(next_run);
"""

ALL_TABLES = [
    CREATE_TABLE_MEMORIES,
    CREATE_TABLE_CONVERSATIONS,
    CREATE_TABLE_JOBS,
    CREATE_TABLE_CRON_SCHEDULES,
    CREATE_TABLE_NOTIFICATIONS,
    CREATE_INDEX_MEMORIES
]
