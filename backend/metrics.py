
"""
Metrics collection and tracking for Primus backend.
"""
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List
from collections import defaultdict
from enum import Enum


class MetricType(Enum):
    """Type of metric."""
    COUNTER = "counter"
    GAUGE = "gauge"
    TIMER = "timer"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    """Represents a single metric."""
    name: str
    type: MetricType
    value: Any
    labels: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MetricsRegistry:
    """Registry for collecting and managing metrics."""

    def __init__(self):
        self._metrics = []
        self._counters = defaultdict(int)
        self._gauges = defaultdict(float)
        self._timers = defaultdict(list)

    def increment(self, name, labels=None, value=1):
        """
        Increment a counter metric.

        Args:
            name: Name of the metric
            labels: Optional labels for the metric
            value: Value to increment by
        """
        key = self._make_key(name, labels or {})
        self._counters[key] += value
        self._metrics.append(Metric(
            name=name,
            type=MetricType.COUNTER,
            value=self._counters[key],
            labels=labels or {}
        ))

    def gauge(self, name, value, labels=None):
        """
        Set a gauge metric.

        Args:
            name: Name of the metric
            value: Value of the gauge
            labels: Optional labels for the metric
        """
        key = self._make_key(name, labels or {})
        self._gauges[key] = value
        self._metrics.append(Metric(
            name=name,
            type=MetricType.GAUGE,
            value=value,
            labels=labels or {}
        ))

    def time(self, name, labels=None):
        """
        Context manager for timing operations.

        Args:
            name: Name of the metric
            labels: Optional labels for the metric
        """
        class TimerContext:
            def __init__(self, registry, name, labels):
                self.registry = registry
                self.name = name
                self.labels = labels or {}
                self.start_time = None

            def __enter__(self):
                self.start_time = time.time()
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                duration = time.time() - self.start_time
                key = self.registry._make_key(self.name, self.labels)
                self.registry._timers[key].append(duration)
                self.registry._metrics.append(Metric(
                    name=self.name,
                    type=MetricType.TIMER,
                    value=duration,
                    labels=self.labels
                ))

        return TimerContext(self, name, labels)

    def get_metrics(self):
        """
        Get all collected metrics as a dictionary.

        Returns:
            Dictionary of metrics
        """
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "timers": {
                name: {
                    "count": len(times),
                    "sum": sum(times),
                    "avg": sum(times)/len(times) if times else 0,
                    "min": min(times) if times else 0,
                    "max": max(times) if times else 0
                }
                for name, times in self._timers.items()
            }
        }

    def reset(self):
        """Reset all metrics."""
        self._metrics.clear()
        self._counters.clear()
        self._gauges.clear()
        self._timers.clear()

    def _make_key(self, name, labels):
        """Create a unique key from name and labels."""
        sorted_labels = sorted(labels.items())
        label_str = ",".join(f"{k}={v}" for k, v in sorted_labels)
        return f"{name}[{label_str}]"


# Global metrics registry
_metrics_registry = MetricsRegistry()


def get_metrics_registry():
    """Get the global metrics registry."""
    return _metrics_registry

