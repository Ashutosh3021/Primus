"""
Jobs module for Primus.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type
from datetime import datetime
import asyncio

from backend.db import Job, JobStatus, JobStore
from backend.logger import get_errors_logger
from backend.exceptions import PrimusException

logger = get_errors_logger(__name__)

# Global job registry
_JOB_REGISTRY: Dict[str, Type["BaseJob"]] = {}


def register_job(name: str):
    """Decorator to register a job class."""
    def decorator(cls: Type["BaseJob"]):
        _JOB_REGISTRY[name] = cls
        logger.info(f"Registered job: {name}")
        return cls
    return decorator


def get_job_class(name: str) -> Optional[Type["BaseJob"]]:
    """Get a registered job class."""
    return _JOB_REGISTRY.get(name)


class BaseJob(ABC):
    """Base class for all jobs."""
    name: str = ""

    def __init__(self, params: Dict[str, Any]):
        self.params = params

    @abstractmethod
    async def run(self, checkpoint: Dict[str, Any]) -> Dict[str, Any]:
        """Run the job, returning result dict with 'content'."""
        pass


@register_job("daily_briefing")
class DailyBriefingJob(BaseJob):
    """Sample daily briefing job."""
    name = "daily_briefing"

    async def run(self, checkpoint: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("Running daily briefing job")
        return {"content": "Daily briefing complete!"}


class JobManager:
    """Manages job execution."""

    def __init__(self):
        self.job_store = JobStore()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._notification_callback: Optional[Any] = None

    async def start(self):
        """Start the job manager."""
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Job manager started")

    async def stop(self):
        """Stop the job manager."""
        self._running = False
        if self._worker_task:
            await self._worker_task

    async def submit(self, job: Job) -> Job:
        """Submit a job for execution."""
        job = await self.job_store.create(job)
        logger.info(f"Submitted job: {job.job_id} ({job.name}")
        return job

    async def _process_job(self, job: Job):
        """Process a single job."""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        await self.job_store.update(job)
        try:
            job_cls = get_job_class(job.name)
            if not job_cls:
                raise PrimusException(f"Job not registered: {job.name}")
            job_inst = job_cls(job.params)
            result = await job_inst.run(job.checkpoint)
            job.status = JobStatus.COMPLETED
            job.result = str(result.get("content", ""))
            logger.info(f"Job completed: {job.job_id}")
        except Exception as e:
            job.retry_count += 1
            if job.retry_count <= job.max_retries:
                job.status = JobStatus.PENDING
                job.error = f"Attempt {job.retry_count}: {str(e)}"
                logger.error(f"Job failed (retrying): {job.job_id}")
            else:
                job.status = JobStatus.FAILED
                job.error = f"Max retries reached: {str(e)}"
                logger.error(f"Job failed: {job.job_id}")
        finally:
            job.completed_at = datetime.utcnow()
            await self.job_store.update(job)

    async def _worker_loop(self):
        """Main worker loop to process pending jobs."""
        while self._running:
            try:
                pending_jobs = await self.job_store.get_pending(limit=5)
                for job in pending_jobs:
                    await self._process_job(job)
                await asyncio.sleep(1)
            except Exception as e:
                logger.error("Worker error:", exc_info=True)
                await asyncio.sleep(5)


__all__ = [
    "BaseJob",
    "register_job",
    "get_job_class",
    "JobManager",
    "DailyBriefingJob"
]
