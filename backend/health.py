
"""
Health checks and monitoring for Primus backend.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List
from datetime import datetime

from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


class HealthStatus(Enum):
    """Health status enum."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


@dataclass
class HealthCheck:
    """Represents a health check."""
    name: str
    check_func: Callable[[], HealthCheckResult]
    critical: bool = False


class HealthChecker:
    """Manager for health checks."""

    def __init__(self):
        self._checks = []

    def register_check(self, name, check_func, critical=False):
        """
        Register a health check.

        Args:
            name: Name of the health check
            check_func: Function that returns HealthCheckResult
            critical: Whether this check is critical to overall health
        """
        self._checks.append(HealthCheck(
            name=name,
            check_func=check_func,
            critical=critical
        ))

    def run_all_checks(self):
        """
        Run all registered health checks.

        Returns:
            Dictionary with overall health status and individual check results
        """
        results = []
        overall_status = HealthStatus.HEALTHY

        for check in self._checks:
            try:
                result = check.check_func()
                results.append(result)

                if result.status == HealthStatus.UNHEALTHY:
                    if check.critical:
                        overall_status = HealthStatus.UNHEALTHY
                    elif overall_status == HealthStatus.HEALTHY:
                        overall_status = HealthStatus.DEGRADED
                elif result.status == HealthStatus.DEGRADED:
                    if overall_status == HealthStatus.HEALTHY:
                        overall_status = HealthStatus.DEGRADED

            except Exception as e:
                logger.error(f"Health check {check.name} failed: {e}", exc_info=True)
                result = HealthCheckResult(
                    name=check.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {str(e)}"
                )
                results.append(result)
                if check.critical:
                    overall_status = HealthStatus.UNHEALTHY

        return {
            "status": overall_status.value,
            "timestamp": datetime.now().isoformat(),
            "checks": [
                {
                    "name": r.name,
                    "status": r.status.value,
                    "message": r.message,
                    "details": r.details,
                    "timestamp": datetime.fromtimestamp(r.timestamp).isoformat()
                }
                for r in results
            ]
        }


# Global health checker
_health_checker = HealthChecker()


def get_health_checker():
    """Get the global health checker."""
    return _health_checker


def database_health_check():
    """Health check for the database."""
    return HealthCheckResult(
        name="database",
        status=HealthStatus.HEALTHY,
        message="Database is accessible",
        details={"backend": "sqlite"}
    )


# Register default health checks
get_health_checker().register_check("database", database_health_check, critical=True)

