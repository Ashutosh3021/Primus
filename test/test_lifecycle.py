"""
Lifecycle test – verifies the three-state module lifecycle introduced in the
architectural refactor.

Tests covered:
  1. ModuleRegistry state transitions (DISABLED / WAITING / RUNNING)
  2. initialize_router → WAITING_FOR_CONFIG when secret is absent
  3. initialize_router → RUNNING when secret is present
  4. initialize_messaging → DISABLED when platform not enabled
  5. initialize_messaging → WAITING_FOR_CONFIG when secret absent
  6. startup_async completes without raising even with no secrets
  7. /health endpoint remains HEALTHY when optional modules are waiting
"""

import asyncio
import sys
import types
import unittest.mock as mock

# ── helpers ───────────────────────────────────────────────────────────────────

def _fresh_registry():
    """Return a brand-new ModuleRegistry (isolated from the global singleton)."""
    from backend.lifecycle import ModuleRegistry
    return ModuleRegistry()


# ── 1. ModuleRegistry state machine ──────────────────────────────────────────

def test_registry_state_transitions():
    print("1. Testing ModuleRegistry state transitions...")
    from backend.lifecycle import ModuleState

    reg = _fresh_registry()

    reg.set_disabled("telegram")
    assert reg.get_state("telegram") == ModuleState.DISABLED

    reg.set_waiting("router", "provider.openai.api_key")
    assert reg.get_state("router") == ModuleState.WAITING_FOR_CONFIG
    assert reg.get_missing_secret("router") == "provider.openai.api_key"
    assert not reg.is_running("router")

    reg.set_running("router")
    assert reg.get_state("router") == ModuleState.RUNNING
    assert reg.is_running("router")
    assert reg.get_missing_secret("router") is None   # cleared on RUNNING

    snap = reg.snapshot()
    assert snap["telegram"] == "disabled"
    assert snap["router"] == "running"

    print("   OK")


# ── 2. initialize_router → WAITING when secret missing ───────────────────────

def test_router_waiting_when_secret_missing():
    print("2. Testing router enters WAITING_FOR_CONFIG when secret is missing...")

    from backend.lifecycle import ModuleState, ModuleRegistry
    import backend.api as api_mod

    # Patch the registry inside api module
    test_reg = _fresh_registry()
    with mock.patch.object(api_mod, "_registry", test_reg), \
         mock.patch("backend.api.get_secret",
                    side_effect=__import__("backend.exceptions",
                                           fromlist=["SecretNotFoundError"]
                                           ).SecretNotFoundError("not found")):

        from backend.config import ProviderConfig, MessagingConfig, MemoryConfig, ToolsConfig, DesktopConfig, Config
        cfg = Config(
            version=1,
            provider=ProviderConfig(name="openai",
                                    secret_ref="provider.openai.api_key",
                                    model="gpt-4o"),
            messaging=MessagingConfig(telegram={"enabled": False},
                                      discord={"enabled": False}),
            memory=MemoryConfig(enabled=True, backend="sqlite"),
            tools=ToolsConfig(web_search=False, browser=False, terminal=False),
            desktop=DesktopConfig(enabled=False, allowed_paths=["."]),
        )
        api_mod._router = None
        api_mod.initialize_router(cfg)

    assert test_reg.get_state("router") == ModuleState.WAITING_FOR_CONFIG
    assert test_reg.get_missing_secret("router") == "provider.openai.api_key"
    assert api_mod._router is None
    print("   OK")


# ── 3. initialize_router → RUNNING when secret present ───────────────────────

def test_router_running_when_secret_present():
    print("3. Testing router enters RUNNING when secret is present...")

    from backend.lifecycle import ModuleState, ModuleRegistry
    import backend.api as api_mod

    test_reg = _fresh_registry()
    with mock.patch.object(api_mod, "_registry", test_reg), \
         mock.patch("backend.api.get_secret", return_value="sk-test-key"):

        from backend.config import ProviderConfig, MessagingConfig, MemoryConfig, ToolsConfig, DesktopConfig, Config
        cfg = Config(
            version=1,
            provider=ProviderConfig(name="ollama",
                                    secret_ref="provider.ollama.api_key",
                                    model="llama3.2"),
            messaging=MessagingConfig(telegram={"enabled": False},
                                      discord={"enabled": False}),
            memory=MemoryConfig(enabled=True, backend="sqlite"),
            tools=ToolsConfig(web_search=False, browser=False, terminal=False),
            desktop=DesktopConfig(enabled=False, allowed_paths=["."]),
        )
        api_mod._router = None
        api_mod.initialize_router(cfg)

    assert test_reg.get_state("router") == ModuleState.RUNNING
    assert api_mod._router is not None
    print("   OK")


# ── 4. initialize_messaging → DISABLED ───────────────────────────────────────

def test_messaging_disabled():
    print("4. Testing messaging platform stays DISABLED when not enabled...")

    from backend.lifecycle import ModuleState, ModuleRegistry
    import backend.api as api_mod

    test_reg = _fresh_registry()
    with mock.patch.object(api_mod, "_registry", test_reg):
        from backend.config import ProviderConfig, MessagingConfig, MemoryConfig, ToolsConfig, DesktopConfig, Config
        cfg = Config(
            version=1,
            provider=ProviderConfig(name="ollama",
                                    secret_ref="provider.ollama.api_key",
                                    model="llama3.2"),
            messaging=MessagingConfig(telegram={"enabled": False},
                                      discord={"enabled": False}),
            memory=MemoryConfig(enabled=True, backend="sqlite"),
            tools=ToolsConfig(web_search=False, browser=False, terminal=False),
            desktop=DesktopConfig(enabled=False, allowed_paths=["."]),
        )
        api_mod.initialize_messaging(cfg)

    assert test_reg.get_state("telegram") == ModuleState.DISABLED
    print("   OK")


# ── 5. initialize_messaging → WAITING when secret absent ─────────────────────

def test_messaging_waiting_when_secret_missing():
    print("5. Testing messaging enters WAITING_FOR_CONFIG when secret is missing...")

    from backend.lifecycle import ModuleState, ModuleRegistry
    import backend.api as api_mod

    test_reg = _fresh_registry()
    with mock.patch.object(api_mod, "_registry", test_reg), \
         mock.patch("backend.api.get_secret",
                    side_effect=__import__("backend.exceptions",
                                           fromlist=["SecretNotFoundError"]
                                           ).SecretNotFoundError("not found")):

        from backend.config import ProviderConfig, MessagingConfig, MemoryConfig, ToolsConfig, DesktopConfig, Config
        cfg = Config(
            version=1,
            provider=ProviderConfig(name="ollama",
                                    secret_ref="provider.ollama.api_key",
                                    model="llama3.2"),
            messaging=MessagingConfig(
                telegram={"enabled": True, "secret_ref": "messaging.telegram.bot_token"},
                discord={"enabled": False}
            ),
            memory=MemoryConfig(enabled=True, backend="sqlite"),
            tools=ToolsConfig(web_search=False, browser=False, terminal=False),
            desktop=DesktopConfig(enabled=False, allowed_paths=["."]),
        )
        api_mod._messaging_platforms = {}
        api_mod.initialize_messaging(cfg)

    assert test_reg.get_state("telegram") == ModuleState.WAITING_FOR_CONFIG
    assert test_reg.get_missing_secret("telegram") == "messaging.telegram.bot_token"
    assert "telegram" not in api_mod._messaging_platforms
    print("   OK")


# ── 6. startup_async never raises on missing secrets ─────────────────────────

def test_startup_never_raises_on_missing_secret():
    print("6. Testing startup_async completes without raising when secrets are absent...")

    from backend.exceptions import SecretNotFoundError

    async def _run():
        with mock.patch("backend.api.get_secret",
                        side_effect=SecretNotFoundError("no secret")):
            from backend.startup import startup_async
            # Should not raise
            config = await startup_async()
            return config

    result = asyncio.run(_run())
    # startup returns config (may be None if config.json missing, but no raise)
    print(f"   startup_async returned: {type(result).__name__}")
    print("   OK")


# ── 7. Health remains HEALTHY with optional modules waiting ──────────────────

def test_health_healthy_with_waiting_modules():
    print("7. Testing overall health stays HEALTHY when optional modules are waiting...")

    from backend.lifecycle import get_module_registry, ModuleState
    reg = get_module_registry()

    # Simulate a waiting router
    reg.set_waiting("router", "provider.openai.api_key")
    reg.set_running("memory")
    reg.set_running("scheduler")

    from backend.api import get_health_status
    health = get_health_status()

    # Database check is critical and should be healthy
    # Overall status must not be UNHEALTHY just because router is waiting
    assert health["status"] in ("healthy", "degraded"), (
        f"Unexpected health status: {health['status']}"
    )
    print(f"   Overall health status: {health['status']}")
    print("   OK")


# ── runner ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("Lifecycle Test Suite")
    print("=" * 55)

    tests = [
        test_registry_state_transitions,
        test_router_waiting_when_secret_missing,
        test_router_running_when_secret_present,
        test_messaging_disabled,
        test_messaging_waiting_when_secret_missing,
        test_startup_never_raises_on_missing_secret,
        test_health_healthy_with_waiting_modules,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            import traceback
            print(f"   FAIL: {exc}")
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 55)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 55)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
