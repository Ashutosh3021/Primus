
"""
Test script for Phase 7: Production Quality
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.health import HealthChecker, HealthStatus, get_health_checker
from backend.metrics import MetricsRegistry, MetricType, get_metrics_registry
from backend.diagnostics import DiagnosticsManager, get_diagnostics_manager
from backend.recovery import RecoveryManager, get_recovery_manager

# Import our API functions
from backend.api import (
    get_health_status, get_metrics, get_diagnostics, get_recovery_state
)


def test_health_checker():
    print("\n" + "="*50)
    print("Testing health checker")
    print("="*50)

    # Test with the singleton
    checker = get_health_checker()
    result = checker.run_all_checks()
    print(f"Status: {result['status']}")
    print(f"Checks: {len(result['checks'])}")
    assert result['status'] == 'healthy'
    print("OK: Health checker basic tests passed")


def test_metrics_registry():
    print("\n" + "="*50)
    print("Testing metrics registry")
    print("="*50)

    registry = MetricsRegistry()

    # Test counter
    registry.increment("test.counter", labels={"env": "test"}, value=1)
    registry.increment("test.counter", labels={"env": "test"}, value=2)

    # Test gauge
    registry.gauge("test.gauge", value=42.0, labels={"env": "test"})

    # Test timer
    with registry.time("test.timer", labels={"env": "test"}):
        time.sleep(0.01)

    metrics = registry.get_metrics()
    print(f"Counters: {list(metrics['counters'].keys())}")
    print(f"Gauges: {list(metrics['gauges'].keys())}")
    print(f"Timers: {list(metrics['timers'].keys())}")
    assert len(metrics['counters']) > 0
    print("OK: Metrics registry tests passed")


def test_diagnostics_manager():
    print("\n" + "="*50)
    print("Testing diagnostics manager")
    print("="*50)

    diag = DiagnosticsManager()
    diag.start_diagnostics()
    diag.mark_config_loaded()
    diag.mark_db_initialized()
    diag.mark_memory_initialized()
    diag.mark_tools_initialized()
    diag.mark_jobs_initialized()
    diag.mark_router_initialized()
    diag.mark_messaging_initialized()
    diag.mark_desktop_initialized()

    startup_diag = diag.get_startup_diagnostic()
    print(f"Startup config loaded: {startup_diag.config_loaded}")

    # Don't try to get system info which may hit psutil issues on Windows,
    # just check we have uptime
    uptime = diag.get_uptime()
    print(f"Uptime (s): {uptime}")
    assert startup_diag.config_loaded
    print("OK: Diagnostics manager tests passed")


def test_recovery_manager():
    print("\n" + "="*50)
    print("Testing recovery manager")
    print("="*50)

    recovery = RecoveryManager(max_failures=2, circuit_break_duration=10)

    # Record some failures
    class TestError(Exception):
        pass

    recovery.record_failure("test.component", TestError("Test failure 1"))
    recovery.record_failure("test.component", TestError("Test failure 2"))

    state = recovery.get_recovery_state()
    print(f"Failures recorded: {len(state['failures'])}")
    assert len(state['failures']) > 0
    print("OK: Recovery manager tests passed")


def test_singletons():
    print("\n" + "="*50)
    print("Testing singleton instances")
    print("="*50)

    h1 = get_health_checker()
    h2 = get_health_checker()
    assert h1 is h2

    m1 = get_metrics_registry()
    m2 = get_metrics_registry()
    assert m1 is m2

    d1 = get_diagnostics_manager()
    d2 = get_diagnostics_manager()
    assert d1 is d2

    r1 = get_recovery_manager()
    r2 = get_recovery_manager()
    assert r1 is r2

    print("OK: All singletons work correctly")


async def test_api_functions():
    print("\n" + "="*50)
    print("Testing API functions for production features")
    print("="*50)

    health = get_health_status()
    print(f"Health status: {health['status']}")

    metrics = get_metrics()
    print(f"Metrics keys: {list(metrics.keys())}")

    print("OK: All API functions are available")


async def main():
    print("\n" + "="*50)
    print("Phase 7 Test Suite")
    print("="*50)

    test_health_checker()
    test_metrics_registry()
    test_diagnostics_manager()
    test_recovery_manager()
    test_singletons()
    await test_api_functions()

    print("\n" + "="*50)
    print("Phase 7 tests complete! All production quality features are working!")
    print("="*50)


if __name__ == "__main__":
    asyncio.run(main())

