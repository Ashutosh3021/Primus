
"""
Recovery system for handling failures and graceful degradation.
"""
import asyncio
import traceback
from typing import Any, Callable, Dict, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


class RecoveryAction(Enum):
    """Types of recovery actions."""
    RETRY = "retry"
    CIRCUIT_BREAK = "circuit_break"
    FALLBACK = "fallback"
    RESTART = "restart"


@dataclass
class FailureRecord:
    """Record of a failure."""
    component: str
    error: str
    timestamp: float
    stack_trace: str


@dataclass
class RecoveryState:
    """State of the recovery system."""
    failures: List[FailureRecord] = field(default_factory=list)
    circuit_breakers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_recovery: float = 0.0


class RecoveryManager:
    """Manager for recovery operations."""

    def __init__(self, max_failures=5, circuit_break_duration=60):
        self._state = RecoveryState()
        self._max_failures = max_failures
        self._circuit_break_duration = circuit_break_duration

    def record_failure(self, component, error):
        """
        Record a failure.

        Args:
            component: Name of the component that failed
            error: The exception that occurred
        """
        record = FailureRecord(
            component=component,
            error=str(error),
            timestamp=datetime.now().timestamp(),
            stack_trace=traceback.format_exc()
        )
        self._state.failures.append(record)

        # Keep only last 100 failures
        if len(self._state.failures) > 100:
            self._state.failures = self._state.failures[-100:]

        # Check circuit breaker
        self._check_circuit_breaker(component)

        logger.error(f"Failure recorded for component {component}: {error}")

    async def execute_with_recovery(
        self,
        component,
        func,
        fallback=None,
        max_retries=3,
        retry_delay=1.0
    ):
        """
        Execute a function with recovery logic.

        Args:
            component: Name of the component
            func: Function to execute
            fallback: Optional fallback function if func fails
            max_retries: Maximum number of retries
            retry_delay: Delay between retries in seconds

        Returns:
            Result of func or fallback

        Raises:
            Exception: If func fails and no fallback is provided
        """
        # Check circuit breaker
        if self._is_circuit_broken(component):
            logger.warning(f"Circuit breaker open for {component}, using fallback")
            if fallback:
                return await self._call_async(fallback)
            raise RuntimeError(f"Circuit breaker open for {component}")

        retries = 0
        last_error = None

        while retries <= max_retries:
            try:
                return await self._call_async(func)
            except Exception as e:
                last_error = e
                self.record_failure(component, e)
                retries += 1

                if retries <= max_retries:
                    logger.warning(
                        f"Component {component} failed (attempt {retries}/{max_retries}), "
                        f"retrying in {retry_delay}s..."
                    )
                    await asyncio.sleep(retry_delay)

        # All retries failed, try fallback
        if fallback:
            logger.warning(f"All retries failed for {component}, using fallback")
            return await self._call_async(fallback)

        raise last_error

    def get_recovery_state(self):
        """
        Get the current recovery state.

        Returns:
            Dictionary of recovery state
        """
        return {
            "failures": [
                {
                    "component": f.component,
                    "error": f.error,
                    "timestamp": datetime.fromtimestamp(f.timestamp).isoformat(),
                    "stack_trace": f.stack_trace
                }
                for f in self._state.failures
            ],
            "circuit_breakers": self._state.circuit_breakers,
            "last_recovery": datetime.fromtimestamp(self._state.last_recovery).isoformat() if self._state.last_recovery else None
        }

    def reset_component(self, component):
        """
        Reset circuit breaker for a component.

        Args:
            component: Name of the component
        """
        if component in self._state.circuit_breakers:
            del self._state.circuit_breakers[component]
            logger.info(f"Circuit breaker reset for {component}")

    def _check_circuit_breaker(self, component):
        """Check if circuit breaker should be opened."""
        recent_failures = [
            f for f in self._state.failures
            if f.component == component and
            datetime.now().timestamp() - f.timestamp < self._circuit_break_duration
        ]

        if len(recent_failures) >= self._max_failures:
            if component not in self._state.circuit_breakers:
                self._state.circuit_breakers[component] = {
                    "opened_at": datetime.now().timestamp(),
                    "failure_count": len(recent_failures)
                }
                logger.error(f"Circuit breaker opened for {component}")

    def _is_circuit_broken(self, component):
        """Check if circuit breaker is open for a component."""
        if component not in self._state.circuit_breakers:
            return False

        breaker = self._state.circuit_breakers[component]
        elapsed = datetime.now().timestamp() - breaker["opened_at"]

        if elapsed >= self._circuit_break_duration:
            # Circuit breaker timeout, reset
            self.reset_component(component)
            return False

        return True

    async def _call_async(self, func):
        """Call a function, whether sync or async."""
        if asyncio.iscoroutinefunction(func):
            return await func()
        return func()


# Global recovery manager
_recovery_manager = RecoveryManager()


def get_recovery_manager():
    """Get the global recovery manager."""
    return _recovery_manager

