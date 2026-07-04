"""
Test script for Phase 5 - Jobs, scheduler, notifications.
"""

import asyncio
import sys

# Add parent dir to path
sys.path.insert(0, 'c:/Users/ashut/Downloads/Primus')

from backend.config import load_config
from backend.db import init_db, Job, JobStatus
from backend.api import (
    initialize_memory, initialize_tools, initialize_jobs,
    start_jobs, stop_jobs, submit_job
)
from backend.jobs import JobManager, get_job_class, register_job
from backend.context_engine import NotificationEngine, Scheduler


async def main():
    print("=" * 50)
    print("Phase 5 Test Suite")
    print("=" * 50)

    # Initialize everything
    config = load_config()
    await init_db()
    initialize_memory()
    initialize_tools(config)
    initialize_jobs(config)

    # Test job manager
    print("\n1. Testing job submission")
    job = Job(
        name="daily_briefing",
        user_id="test_user",
        status=JobStatus.PENDING
    )
    job = await submit_job(job)
    print(f"Submitted job: {job.job_id}")

    # Start jobs
    await start_jobs()

    # Wait a bit
    await asyncio.sleep(2)

    # Stop jobs
    await stop_jobs()

    print("\n" + "=" * 50)
    print("Phase 5 tests complete!")
    print("=" * 50)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
