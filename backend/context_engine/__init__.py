"""
Context engine and scheduler module.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio
import re

from backend.db import CronStore, CronSchedule, Job, JobStatus, NotificationStore, Notification
from backend.jobs import JobManager
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


class NotificationEngine:
    """Sends notifications via various channels."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.notification_store = NotificationStore()
        self._channels: Dict[str, Any] = {}

    async def send(self, user_id: str, channel: str, title: str, content: str):
        """Send a notification."""
        logger.info(f"Sending notification to {user_id} via {channel}: {title}")
        notification = Notification(
            user_id=user_id,
            channel=channel,
            title=title,
            content=content,
            sent_at=datetime.utcnow()
        )
        await self.notification_store.create(notification)


class Scheduler:
    """Cron scheduler for jobs."""

    def __init__(self, job_manager: JobManager, notification_engine: NotificationEngine):
        self.job_manager = job_manager
        self.notification_engine = notification_engine
        self.cron_store = CronStore()
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the scheduler."""
        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler started")

    async def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._scheduler_task:
            await self._scheduler_task

    async def add_schedule(self, schedule: CronSchedule) -> CronSchedule:
        """Add a new cron schedule."""
        return await self.cron_store.create(schedule)

    def _parse_cron(self, expr: str, now: datetime) -> Optional[datetime]:
        """Simple cron parser to get next run time."""
        parts = expr.split()
        if len(parts) < 5:
            return None
        
        minute, hour, dom, month, dow = parts
        
        next_time = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(525600):  # 1 year max search
            match = True
            
            if minute != "*" and str(next_time.minute) != minute:
                match = False
            if hour != "*" and str(next_time.hour) != hour:
                match = False
            if dom != "*" and str(next_time.day) != dom:
                match = False
            if month != "*" and str(next_time.month) != month:
                match = False
            if dow != "*" and str((next_time.weekday() + 1) % 7) != dow:
                match = False
                
            if match:
                return next_time
            
            next_time += timedelta(minutes=1)
        
        return None

    async def _scheduler_loop(self):
        """Main scheduling loop."""
        while self._running:
            try:
                schedules = await self.cron_store.get_enabled()
                now = datetime.utcnow()
                
                for schedule in schedules:
                    if schedule.next_run is None:
                        schedule.next_run = self._parse_cron(schedule.cron_expr, now)
                        await self.cron_store.update(schedule)
                    elif schedule.next_run <= now:
                        job = Job(
                            name=schedule.job_name,
                            user_id=schedule.user_id,
                            status=JobStatus.PENDING,
                            params=schedule.params
                        )
                        await self.job_manager.submit(job)
                        
                        schedule.last_run = now
                        schedule.next_run = self._parse_cron(schedule.cron_expr, now)
                        await self.cron_store.update(schedule)
                
                await asyncio.sleep(30)  # Check every 30 sec
            except Exception as e:
                logger.error("Scheduler error:", exc_info=True)
                await asyncio.sleep(60)


__all__ = [
    "NotificationEngine",
    "Scheduler"
]
