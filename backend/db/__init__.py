"""
Database module for Primus.
"""

import json
import aiosqlite
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from backend.constants import BASE_DIR
from backend.db.schema import (
    MemoryEntry,
    ConversationMessage,
    MemoryLayer,
    Job,
    JobStatus,
    CronSchedule,
    Notification,
    ALL_TABLES
)
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)

DB_PATH = BASE_DIR / "primus.db"


async def init_db():
    """Initialize the database and create tables if they don't exist."""
    logger.info(f"Initializing database at {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as conn:
        for create_stmt in ALL_TABLES:
            await conn.executescript(create_stmt)
        await conn.commit()
    logger.info("Database initialized successfully")


async def _json_from_metadata(metadata: Optional[Dict[str, Any]]) -> str:
    return json.dumps(metadata) if metadata else "{}"


async def _metadata_from_json(metadata_str: Optional[str]) -> Dict[str, Any]:
    return json.loads(metadata_str) if metadata_str else {}


class MemoryStore:
    """Storage class for memory entries."""

    async def add(self, entry: MemoryEntry) -> MemoryEntry:
        """Add or update a memory entry."""
        now = datetime.utcnow()
        metadata_json = await _json_from_metadata(entry.metadata)
        
        async with aiosqlite.connect(DB_PATH) as conn:
            # Try to update first
            cursor = await conn.execute(
                """
                UPDATE memories 
                SET value = ?, metadata = ?, updated_at = ?
                WHERE user_id = ? AND layer = ? AND key = ?
                """,
                (entry.value, metadata_json, now, entry.user_id, entry.layer.value, entry.key)
            )
            
            if cursor.rowcount == 0:
                # Insert new
                cursor = await conn.execute(
                    """
                    INSERT INTO memories (user_id, layer, key, value, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entry.user_id, entry.layer.value, entry.key, entry.value, metadata_json, now, now)
                )
                entry.id = cursor.lastrowid
            else:
                # Get existing id
                cursor = await conn.execute(
                    "SELECT id FROM memories WHERE user_id = ? AND layer = ? AND key = ?",
                    (entry.user_id, entry.layer.value, entry.key)
                )
                row = await cursor.fetchone()
                if row:
                    entry.id = row[0]
            
            await conn.commit()
        
        entry.created_at = entry.created_at or now
        entry.updated_at = now
        return entry

    async def get(self, user_id: str, layer: MemoryLayer, key: str) -> Optional[MemoryEntry]:
        """Get a memory entry by user, layer, and key."""
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT id, user_id, layer, key, value, metadata, created_at, updated_at "
                "FROM memories WHERE user_id = ? AND layer = ? AND key = ?",
                (user_id, layer.value, key)
            )
            row = await cursor.fetchone()
        
        if row:
            return MemoryEntry(
                id=row[0],
                user_id=row[1],
                layer=MemoryLayer(row[2]),
                key=row[3],
                value=row[4],
                metadata=await _metadata_from_json(row[5]),
                created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                updated_at=datetime.fromisoformat(row[7]) if row[7] else None
            )
        return None

    async def get_all(self, user_id: str, layer: Optional[MemoryLayer] = None) -> List[MemoryEntry]:
        """Get all memory entries for a user, optionally filtered by layer."""
        entries = []
        async with aiosqlite.connect(DB_PATH) as conn:
            if layer:
                cursor = await conn.execute(
                    "SELECT id, user_id, layer, key, value, metadata, created_at, updated_at "
                    "FROM memories WHERE user_id = ? AND layer = ? ORDER BY updated_at DESC",
                    (user_id, layer.value)
                )
            else:
                cursor = await conn.execute(
                    "SELECT id, user_id, layer, key, value, metadata, created_at, updated_at "
                    "FROM memories WHERE user_id = ? ORDER BY updated_at DESC",
                    (user_id,)
                )
            
            async for row in cursor:
                entries.append(MemoryEntry(
                    id=row[0],
                    user_id=row[1],
                    layer=MemoryLayer(row[2]),
                    key=row[3],
                    value=row[4],
                    metadata=await _metadata_from_json(row[5]),
                    created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                    updated_at=datetime.fromisoformat(row[7]) if row[7] else None
                ))
        
        return entries

    async def delete(self, user_id: str, layer: MemoryLayer, key: str) -> bool:
        """Delete a memory entry."""
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "DELETE FROM memories WHERE user_id = ? AND layer = ? AND key = ?",
                (user_id, layer.value, key)
            )
            await conn.commit()
            return cursor.rowcount > 0


class ConversationStore:
    """Storage class for conversation messages."""

    async def add(self, message: ConversationMessage) -> ConversationMessage:
        """Add a new conversation message."""
        metadata_json = await _json_from_metadata(message.metadata)
        
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO conversations (user_id, conversation_id, role, content, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message.user_id, message.conversation_id, message.role, message.content, metadata_json)
            )
            await conn.commit()
            message.id = cursor.lastrowid
            message.timestamp = datetime.utcnow()
        
        return message

    async def get_conversation(
        self, 
        user_id: str, 
        conversation_id: str, 
        limit: int = 50
    ) -> List[ConversationMessage]:
        """Get conversation messages, newest first (but return in order)."""
        messages = []
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """
                SELECT id, user_id, conversation_id, role, content, timestamp, metadata
                FROM conversations 
                WHERE user_id = ? AND conversation_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (user_id, conversation_id, limit)
            )
            
            async for row in cursor:
                messages.insert(0, ConversationMessage(
                    id=row[0],
                    user_id=row[1],
                    conversation_id=row[2],
                    role=row[3],
                    content=row[4],
                    timestamp=datetime.fromisoformat(row[5]) if row[5] else None,
                    metadata=await _metadata_from_json(row[6])
                ))
        
        return messages

    async def clear_conversation(self, user_id: str, conversation_id: str) -> bool:
        """Clear all messages from a conversation."""
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "DELETE FROM conversations WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id)
            )
            await conn.commit()
            return cursor.rowcount > 0


class JobStore:
    """Storage class for jobs."""

    async def create(self, job: Job) -> Job:
        """Create a new job."""
        if not job.job_id:
            job.job_id = str(uuid.uuid4())
        now = datetime.utcnow()
        params_json = await _json_from_metadata(job.params)
        checkpoint_json = await _json_from_metadata(job.checkpoint)
        
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO jobs (
                    job_id, name, user_id, status, params, checkpoint,
                    retry_count, max_retries, result, error,
                    scheduled_at, started_at, completed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id, job.name, job.user_id, job.status.value, params_json, checkpoint_json,
                    job.retry_count, job.max_retries, job.result, job.error,
                    job.scheduled_at.isoformat() if job.scheduled_at else None,
                    job.started_at.isoformat() if job.started_at else None,
                    job.completed_at.isoformat() if job.completed_at else None,
                    now, now
                )
            )
            await conn.commit()
            job.id = cursor.lastrowid
        
        job.created_at = now
        job.updated_at = now
        return job

    async def get(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT id, job_id, name, user_id, status, params, checkpoint, "
                "retry_count, max_retries, result, error, scheduled_at, "
                "started_at, completed_at, created_at, updated_at "
                "FROM jobs WHERE job_id = ?",
                (job_id,)
            )
            row = await cursor.fetchone()
        
        if row:
            return Job(
                id=row[0],
                job_id=row[1],
                name=row[2],
                user_id=row[3],
                status=JobStatus(row[4]),
                params=await _metadata_from_json(row[5]),
                checkpoint=await _metadata_from_json(row[6]),
                retry_count=row[7],
                max_retries=row[8],
                result=row[9],
                error=row[10],
                scheduled_at=datetime.fromisoformat(row[11]) if row[11] else None,
                started_at=datetime.fromisoformat(row[12]) if row[12] else None,
                completed_at=datetime.fromisoformat(row[13]) if row[13] else None,
                created_at=datetime.fromisoformat(row[14]) if row[14] else None,
                updated_at=datetime.fromisoformat(row[15]) if row[15] else None
            )
        return None

    async def update(self, job: Job) -> Job:
        """Update an existing job."""
        now = datetime.utcnow()
        params_json = await _json_from_metadata(job.params)
        checkpoint_json = await _json_from_metadata(job.checkpoint)
        
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                """
                UPDATE jobs 
                SET status = ?, params = ?, checkpoint = ?, retry_count = ?, max_retries = ?,
                    result = ?, error = ?, scheduled_at = ?, started_at = ?, completed_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    job.status.value, params_json, checkpoint_json, job.retry_count, job.max_retries,
                    job.result, job.error,
                    job.scheduled_at.isoformat() if job.scheduled_at else None,
                    job.started_at.isoformat() if job.started_at else None,
                    job.completed_at.isoformat() if job.completed_at else None,
                    now, job.job_id
                )
            )
            await conn.commit()
        
        job.updated_at = now
        return job

    async def get_pending(self, limit: int = 10) -> List[Job]:
        """Get pending jobs, oldest first."""
        jobs = []
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT id, job_id, name, user_id, status, params, checkpoint, "
                "retry_count, max_retries, result, error, scheduled_at, "
                "started_at, completed_at, created_at, updated_at "
                "FROM jobs WHERE status = ? ORDER BY created_at ASC LIMIT ?",
                (JobStatus.PENDING.value, limit)
            )
            
            async for row in cursor:
                jobs.append(Job(
                    id=row[0],
                    job_id=row[1],
                    name=row[2],
                    user_id=row[3],
                    status=JobStatus(row[4]),
                    params=await _metadata_from_json(row[5]),
                    checkpoint=await _metadata_from_json(row[6]),
                    retry_count=row[7],
                    max_retries=row[8],
                    result=row[9],
                    error=row[10],
                    scheduled_at=datetime.fromisoformat(row[11]) if row[11] else None,
                    started_at=datetime.fromisoformat(row[12]) if row[12] else None,
                    completed_at=datetime.fromisoformat(row[13]) if row[13] else None,
                    created_at=datetime.fromisoformat(row[14]) if row[14] else None,
                    updated_at=datetime.fromisoformat(row[15]) if row[15] else None
                ))
        return jobs

    async def get_counts_by_status(self) -> Dict[str, int]:
        """Return a dict of job counts grouped by status."""
        counts: Dict[str, int] = {s.value: 0 for s in JobStatus}
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT status, COUNT(*) FROM jobs GROUP BY status"
            )
            async for row in cursor:
                counts[row[0]] = row[1]
        return counts

    async def get_all(self, user_id: Optional[str] = None, limit: int = 100) -> List[Job]:
        """Get all jobs, optionally filtered by user."""
        jobs = []
        async with aiosqlite.connect(DB_PATH) as conn:
            if user_id:
                cursor = await conn.execute(
                    "SELECT id, job_id, name, user_id, status, params, checkpoint, "
                    "retry_count, max_retries, result, error, scheduled_at, "
                    "started_at, completed_at, created_at, updated_at "
                    "FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit)
                )
            else:
                cursor = await conn.execute(
                    "SELECT id, job_id, name, user_id, status, params, checkpoint, "
                    "retry_count, max_retries, result, error, scheduled_at, "
                    "started_at, completed_at, created_at, updated_at "
                    "FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
            
            async for row in cursor:
                jobs.append(Job(
                    id=row[0],
                    job_id=row[1],
                    name=row[2],
                    user_id=row[3],
                    status=JobStatus(row[4]),
                    params=await _metadata_from_json(row[5]),
                    checkpoint=await _metadata_from_json(row[6]),
                    retry_count=row[7],
                    max_retries=row[8],
                    result=row[9],
                    error=row[10],
                    scheduled_at=datetime.fromisoformat(row[11]) if row[11] else None,
                    started_at=datetime.fromisoformat(row[12]) if row[12] else None,
                    completed_at=datetime.fromisoformat(row[13]) if row[13] else None,
                    created_at=datetime.fromisoformat(row[14]) if row[14] else None,
                    updated_at=datetime.fromisoformat(row[15]) if row[15] else None
                ))
        return jobs


class CronStore:
    """Storage class for cron schedules."""

    async def create(self, schedule: CronSchedule) -> CronSchedule:
        """Create a new cron schedule."""
        if not schedule.cron_id:
            schedule.cron_id = str(uuid.uuid4())
        now = datetime.utcnow()
        params_json = await _json_from_metadata(schedule.params)
        
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO cron_schedules (
                    cron_id, name, user_id, job_name, cron_expr, params, enabled,
                    last_run, next_run, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule.cron_id, schedule.name, schedule.user_id,
                    schedule.job_name, schedule.cron_expr, params_json,
                    1 if schedule.enabled else 0,
                    schedule.last_run.isoformat() if schedule.last_run else None,
                    schedule.next_run.isoformat() if schedule.next_run else None,
                    now, now
                )
            )
            await conn.commit()
            schedule.id = cursor.lastrowid
        
        schedule.created_at = now
        schedule.updated_at = now
        return schedule

    async def get(self, cron_id: str) -> Optional[CronSchedule]:
        """Get a cron schedule by ID."""
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT id, cron_id, name, user_id, job_name, cron_expr, params, enabled, "
                "last_run, next_run, created_at, updated_at "
                "FROM cron_schedules WHERE cron_id = ?",
                (cron_id,)
            )
            row = await cursor.fetchone()
        
        if row:
            return CronSchedule(
                id=row[0],
                cron_id=row[1],
                name=row[2],
                user_id=row[3],
                job_name=row[4],
                cron_expr=row[5],
                params=await _metadata_from_json(row[6]),
                enabled=bool(row[7]),
                last_run=datetime.fromisoformat(row[8]) if row[8] else None,
                next_run=datetime.fromisoformat(row[9]) if row[9] else None,
                created_at=datetime.fromisoformat(row[10]) if row[10] else None,
                updated_at=datetime.fromisoformat(row[11]) if row[11] else None
            )
        return None

    async def update(self, schedule: CronSchedule) -> CronSchedule:
        """Update an existing cron schedule."""
        now = datetime.utcnow()
        params_json = await _json_from_metadata(schedule.params)
        
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                """
                UPDATE cron_schedules 
                SET name = ?, job_name = ?, cron_expr = ?, params = ?, enabled = ?,
                    last_run = ?, next_run = ?, updated_at = ?
                WHERE cron_id = ?
                """,
                (
                    schedule.name, schedule.job_name, schedule.cron_expr, params_json,
                    1 if schedule.enabled else 0,
                    schedule.last_run.isoformat() if schedule.last_run else None,
                    schedule.next_run.isoformat() if schedule.next_run else None,
                    now, schedule.cron_id
                )
            )
            await conn.commit()
        
        schedule.updated_at = now
        return schedule

    async def get_enabled(self) -> List[CronSchedule]:
        """Get all enabled cron schedules."""
        schedules = []
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT id, cron_id, name, user_id, job_name, cron_expr, params, enabled, "
                "last_run, next_run, created_at, updated_at "
                "FROM cron_schedules WHERE enabled = 1 ORDER BY next_run ASC",
                ()
            )
            
            async for row in cursor:
                schedules.append(CronSchedule(
                    id=row[0],
                    cron_id=row[1],
                    name=row[2],
                    user_id=row[3],
                    job_name=row[4],
                    cron_expr=row[5],
                    params=await _metadata_from_json(row[6]),
                    enabled=bool(row[7]),
                    last_run=datetime.fromisoformat(row[8]) if row[8] else None,
                    next_run=datetime.fromisoformat(row[9]) if row[9] else None,
                    created_at=datetime.fromisoformat(row[10]) if row[10] else None,
                    updated_at=datetime.fromisoformat(row[11]) if row[11] else None
                ))
        return schedules


class NotificationStore:
    """Storage class for notifications."""

    async def create(self, notification: Notification) -> Notification:
        """Create a new notification."""
        if not notification.notification_id:
            notification.notification_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO notifications (
                    notification_id, user_id, channel, title, content, sent_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notification.notification_id, notification.user_id,
                    notification.channel, notification.title, notification.content,
                    notification.sent_at.isoformat() if notification.sent_at else None,
                    now
                )
            )
            await conn.commit()
            notification.id = cursor.lastrowid
        
        notification.created_at = now
        return notification


__all__ = [
    "init_db",
    "MemoryStore",
    "ConversationStore",
    "JobStore",
    "CronStore",
    "NotificationStore",
    "MemoryEntry",
    "ConversationMessage",
    "Job",
    "JobStatus",
    "CronSchedule",
    "Notification",
    "MemoryLayer"
]
