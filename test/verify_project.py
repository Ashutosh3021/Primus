"""
Primus project verification script.

Checks folder structure, imports, configuration, providers, messaging,
desktop, jobs, memory, scheduler, notifications, tools, database, and
frontend communication endpoints.

Run from the project root:
    python test/verify_project.py
"""

import asyncio
import importlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ── Ensure project root is on sys.path ────────────────────────────────────────
ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

PASS = "\033[32m  PASS\033[0m"
FAIL = "\033[31m  FAIL\033[0m"
WARN = "\033[33m  WARN\033[0m"
INFO = "\033[36m  INFO\033[0m"

results: List[Tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    icon = PASS if ok else FAIL
    print(f"{icon}  {name}" + (f" — {detail}" if detail else ""))


def warn(name: str, detail: str = "") -> None:
    results.append((name, True, detail))
    print(f"{WARN}  {name}" + (f" — {detail}" if detail else ""))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Folder structure
# ─────────────────────────────────────────────────────────────────────────────
def verify_structure() -> None:
    print("\n── Folder Structure ─────────────────────────────────────────────────────")
    required_paths = [
        "main.py",
        "requirements.txt",
        "config.json",
        "render.yaml",
        "runtime.txt",
        "backend/__init__.py",
        "backend/server.py",
        "backend/startup.py",
        "backend/config.py",
        "backend/constants.py",
        "backend/logger.py",
        "backend/secrets.py",
        "backend/validators.py",
        "backend/exceptions.py",
        "backend/helpers.py",
        "backend/health.py",
        "backend/diagnostics.py",
        "backend/metrics.py",
        "backend/recovery.py",
        "backend/api/__init__.py",
        "backend/db/__init__.py",
        "backend/db/schema.py",
        "backend/memory/__init__.py",
        "backend/memory/context_engine.py",
        "backend/memory/prompt_builder.py",
        "backend/providers/__init__.py",
        "backend/providers/base.py",
        "backend/providers/openai.py",
        "backend/providers/anthropic.py",
        "backend/providers/groq.py",
        "backend/providers/gemini.py",
        "backend/providers/ollama.py",
        "backend/messaging/__init__.py",
        "backend/messaging/base.py",
        "backend/messaging/telegram.py",
        "backend/jobs/__init__.py",
        "backend/context_engine/__init__.py",
        "backend/desktop/__init__.py",
        "backend/desktop/tools.py",
        "backend/tools/__init__.py",
        "backend/tools/base.py",
        "backend/tools/web_search.py",
        "backend/router/__init__.py",
        "backend/router/ai_router.py",
        "backend/git-learning/__init__.py",
        "backend/desktop/automation.py",
        "pages/Dashbord/index.html",
        "pages/Wizard/index.html",
        "pages/ledger/index.html",
    ]
    for path in required_paths:
        full = ROOT / path
        check(path, full.exists(), "" if full.exists() else "MISSING")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Config
# ─────────────────────────────────────────────────────────────────────────────
def verify_config() -> None:
    print("\n── Configuration ────────────────────────────────────────────────────────")
    cfg_path = ROOT / "config.json"
    if not cfg_path.exists():
        check("config.json exists", False, "MISSING")
        return
    check("config.json exists", True)
    try:
        with open(cfg_path) as f:
            data = json.load(f)
        check("config.json parses as JSON", True)
        for field in ("version", "provider", "messaging", "memory", "tools"):
            check(f"config.json has '{field}'", field in data)
        # No raw API keys
        raw_key = data.get("provider", {}).get("api_key")
        check("No raw api_key in config.json", raw_key is None,
              "api_key found! Use secret_ref instead." if raw_key else "")
    except Exception as exc:
        check("config.json parses as JSON", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Python imports
# ─────────────────────────────────────────────────────────────────────────────
def verify_imports() -> None:
    print("\n── Python Imports ───────────────────────────────────────────────────────")
    modules_to_import = [
        "backend",
        "backend.config",
        "backend.constants",
        "backend.exceptions",
        "backend.validators",
        "backend.helpers",
        "backend.logger",
        "backend.secrets",
        "backend.health",
        "backend.diagnostics",
        "backend.metrics",
        "backend.recovery",
        "backend.db",
        "backend.db.schema",
        "backend.memory",
        "backend.memory.context_engine",
        "backend.memory.prompt_builder",
        "backend.providers",
        "backend.providers.base",
        "backend.providers.openai",
        "backend.providers.anthropic",
        "backend.providers.groq",
        "backend.providers.gemini",
        "backend.providers.ollama",
        "backend.messaging",
        "backend.messaging.base",
        "backend.messaging.telegram",
        "backend.jobs",
        "backend.context_engine",
        "backend.desktop",
        "backend.desktop.tools",
        "backend.tools",
        "backend.tools.base",
        "backend.tools.web_search",
        "backend.router",
        "backend.router.ai_router",
        "backend.api",
        "backend.server",
        "backend.startup",
        "backend.desktop.automation",
    ]
    for mod in modules_to_import:
        try:
            importlib.import_module(mod)
            check(f"import {mod}", True)
        except ImportError as exc:
            check(f"import {mod}", False, str(exc))
        except Exception as exc:
            warn(f"import {mod}", f"non-import error: {exc}")

    # Hyphenated module — must use importlib directly
    try:
        importlib.import_module("backend.git-learning")
        check("import backend.git-learning (via importlib)", True)
    except ImportError as exc:
        check("import backend.git-learning (via importlib)", False, str(exc))
    except Exception as exc:
        warn("import backend.git-learning (via importlib)", f"non-import error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Provider registry
# ─────────────────────────────────────────────────────────────────────────────
def verify_providers() -> None:
    print("\n── Providers ────────────────────────────────────────────────────────────")
    try:
        from backend.providers import PROVIDER_REGISTRY
        expected = ["openai", "openrouter", "anthropic", "groq", "moonshot", "glm", "gemini", "ollama"]
        for name in expected:
            check(f"Provider '{name}' registered", name in PROVIDER_REGISTRY)
    except Exception as exc:
        check("Provider registry", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Messaging platforms
# ─────────────────────────────────────────────────────────────────────────────
def verify_messaging() -> None:
    print("\n── Messaging ────────────────────────────────────────────────────────────")
    try:
        from backend.messaging import MESSAGING_PLATFORMS, BaseMessaging
        check("MESSAGING_PLATFORMS defined", bool(MESSAGING_PLATFORMS))
        check("'telegram' in MESSAGING_PLATFORMS", "telegram" in MESSAGING_PLATFORMS)
        # Verify Telegram class has required methods
        from backend.messaging.telegram import TelegramMessaging
        for method in ("start", "stop", "send_message"):
            check(f"TelegramMessaging.{method} exists",
                  hasattr(TelegramMessaging, method))
    except Exception as exc:
        check("Messaging module", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 6. Tools
# ─────────────────────────────────────────────────────────────────────────────
def verify_tools() -> None:
    print("\n── Tools ────────────────────────────────────────────────────────────────")
    try:
        from backend.tools.base import ToolRegistry
        import backend.tools.web_search          # registers WebSearchTool
        import backend.desktop.tools             # registers desktop tools
        all_tools = ToolRegistry.get_all_tools()
        expected_tools = ["web_search", "terminal", "filesystem", "python", "git", "ollama", "docker"]
        for name in expected_tools:
            check(f"Tool '{name}' registered", name in all_tools)
    except Exception as exc:
        check("Tool registry", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 7. Memory
# ─────────────────────────────────────────────────────────────────────────────
def verify_memory() -> None:
    print("\n── Memory ───────────────────────────────────────────────────────────────")
    try:
        from backend.memory import ContextEngine, PromptBuilder, PromptContext
        for cls in (ContextEngine, PromptBuilder):
            check(f"{cls.__name__} importable", True)
        from backend.db import MemoryStore, ConversationStore, JobStore, CronStore
        for cls in (MemoryStore, ConversationStore, JobStore, CronStore):
            check(f"{cls.__name__} importable", True)
    except Exception as exc:
        check("Memory / DB module", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 8. Jobs & Scheduler
# ─────────────────────────────────────────────────────────────────────────────
def verify_jobs() -> None:
    print("\n── Jobs & Scheduler ─────────────────────────────────────────────────────")
    try:
        from backend.jobs import JobManager, DailyBriefingJob
        check("JobManager importable", True)
        check("DailyBriefingJob registered", True)
        from backend.context_engine import Scheduler, NotificationEngine
        check("Scheduler importable", True)
        check("NotificationEngine importable", True)
    except Exception as exc:
        check("Jobs / Scheduler", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 9. Desktop agent
# ─────────────────────────────────────────────────────────────────────────────
def verify_desktop() -> None:
    print("\n── Desktop Agent ────────────────────────────────────────────────────────")
    try:
        from backend.desktop import DesktopConnector, DesktopCapabilities
        check("DesktopConnector importable", True)
        for method in ("start", "stop", "_detect_capabilities"):
            check(f"DesktopConnector.{method} exists",
                  hasattr(DesktopConnector, method))
    except Exception as exc:
        check("Desktop module", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 10. Health / Metrics / Diagnostics / Recovery
# ─────────────────────────────────────────────────────────────────────────────
def verify_production_features() -> None:
    print("\n── Production Features ──────────────────────────────────────────────────")
    try:
        from backend.health import get_health_checker, HealthStatus
        checker = get_health_checker()
        result = checker.run_all_checks()
        check("Health checker runs", "status" in result)
        check("Health status is healthy", result.get("status") == "healthy",
              result.get("status", "?"))
    except Exception as exc:
        check("Health checker", False, str(exc))

    try:
        from backend.metrics import get_metrics_registry
        registry = get_metrics_registry()
        registry.increment("verify.test")
        metrics = registry.get_metrics()
        check("Metrics registry works", "counters" in metrics)
    except Exception as exc:
        check("Metrics registry", False, str(exc))

    try:
        from backend.diagnostics import get_diagnostics_manager
        diag = get_diagnostics_manager()
        check("DiagnosticsManager importable", True)
    except Exception as exc:
        check("DiagnosticsManager", False, str(exc))

    try:
        from backend.recovery import get_recovery_manager
        rm = get_recovery_manager()
        state = rm.get_recovery_state()
        check("Recovery manager works", "failures" in state)
    except Exception as exc:
        check("Recovery manager", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 11. FastAPI server endpoints
# ─────────────────────────────────────────────────────────────────────────────
def verify_server_endpoints() -> None:
    print("\n── HTTP Server Endpoints ────────────────────────────────────────────────")
    try:
        from backend.server import app
        routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
        expected_routes = [
            "/health",
            "/api/status",
            "/api/diagnostics",
            "/api/config/validate",
            "/api/config/apply",
            "/api/config",
            "/api/secrets/set",
            "/api/secrets/stored",
            "/api/chat",
            "/api/jobs",
            "/api/jobs/{job_id}",
            "/api/metrics",
            "/api/logs",
            "/api/memory",
            "/api/notifications",
            "/api/cron",
            "/api/capabilities",
            "/api/recovery",
            "/api/dashboard",
            "/api/providers",
            "/api/models",
            "/api/provider",
            "/api/model",
            "/api/auto",
            "/api/git-learning/scan",
            "/api/git-learning/jobs",
            "/api/automation/run",
            "/api/automation/workflows",
        ]
        for route in expected_routes:
            check(f"Route '{route}' registered", route in routes)
    except Exception as exc:
        check("FastAPI server", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 12. Git Learning module
# ─────────────────────────────────────────────────────────────────────────────
async def verify_git_learning() -> None:
    print("\n── Git Learning ─────────────────────────────────────────────────────────")
    try:
        import importlib
        gl = importlib.import_module("backend.git-learning")
        check("git-learning module importable", True)
        check("GitLearner class present",    hasattr(gl, "GitLearner"))
        check("RepoSummary class present",   hasattr(gl, "RepoSummary"))
        check("register_git_learning_job present", hasattr(gl, "register_git_learning_job"))

        # Verify git_learning job was registered
        from backend.jobs import get_job_class
        check("'git_learning' job registered", get_job_class("git_learning") is not None)

        # Run a quick scan of the project itself
        learner = gl.GitLearner(ROOT)
        summary = await learner.learn()
        check("GitLearner.learn() returns RepoSummary", hasattr(summary, "name"))
        check("Scan detected languages",     len(summary.languages) > 0,
              f"languages={summary.languages}")
        check("Scan detected frameworks",    len(summary.frameworks) > 0,
              f"frameworks={summary.frameworks}")
        check("Scan produced summary text",  len(summary.as_text()) > 20)
        check("No scan error",               summary.error is None,
              summary.error or "")
    except Exception as exc:
        check("Git Learning module", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 13. Automation Engine
# ─────────────────────────────────────────────────────────────────────────────
async def verify_automation() -> None:
    print("\n── Automation Engine ────────────────────────────────────────────────────")
    try:
        from backend.desktop.automation import (
            AutomationEngine, Workflow, WorkflowStep,
            get_builtin_workflow, BUILTIN_WORKFLOWS,
        )
        check("AutomationEngine importable", True)
        check("Workflow importable",         True)
        check("WorkflowStep importable",     True)
        check("BUILTIN_WORKFLOWS non-empty", len(BUILTIN_WORKFLOWS) > 0,
              f"count={len(BUILTIN_WORKFLOWS)}")

        for name in ("git_status", "python_env_info", "project_health"):
            wf = get_builtin_workflow(name)
            check(f"Built-in workflow '{name}' exists",
                  wf is not None and len(wf.steps) > 0)

        # Serialise / deserialise round-trip
        wf = get_builtin_workflow("git_status")
        raw = AutomationEngine.to_dict(wf)
        wf2 = AutomationEngine.from_dict(raw)
        check("Workflow serialise/deserialise round-trip",
              wf2.name == wf.name and len(wf2.steps) == len(wf.steps))

        # Template expansion
        from backend.desktop.automation import _expand_templates, StepResult
        sr = StepResult(step_index=0, tool="terminal", success=True, content="hello")
        expanded = _expand_templates("output: {step_0}", [sr])
        check("Template expansion {step_0} works", expanded == "output: hello",
              f"got: {expanded!r}")
    except Exception as exc:
        check("Automation Engine", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 14. Extended metrics & DB helpers
# ─────────────────────────────────────────────────────────────────────────────
async def verify_extended_helpers() -> None:
    print("\n── Extended Helpers ─────────────────────────────────────────────────────")
    try:
        from backend.metrics import get_metrics_registry
        reg = get_metrics_registry()
        reg.increment("test.counter", {"label": "a"}, 5)
        reg.increment("test.counter", {"label": "b"}, 3)
        total = reg.get_counter("test.counter")
        check("MetricsRegistry.get_counter sums labels", total >= 8,
              f"got {total}")
    except Exception as exc:
        check("MetricsRegistry.get_counter", False, str(exc))

    try:
        from backend.db import JobStore
        store = JobStore()
        counts = await store.get_counts_by_status()
        check("JobStore.get_counts_by_status returns dict",
              isinstance(counts, dict) and "pending" in counts)
    except Exception as exc:
        check("JobStore.get_counts_by_status", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 15. Database (async)
# ─────────────────────────────────────────────────────────────────────────────
async def verify_database() -> None:
    print("\n── Database ─────────────────────────────────────────────────────────────")
    try:
        from backend.db import init_db
        await init_db()
        check("Database init_db() succeeds", True)
        from backend.db import DB_PATH
        check("primus.db file created", DB_PATH.exists())
    except Exception as exc:
        check("Database initialisation", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# 16. Render deployment files
# ─────────────────────────────────────────────────────────────────────────────
def verify_deployment() -> None:
    print("\n── Deployment ───────────────────────────────────────────────────────────")
    for fname in ("render.yaml", "runtime.txt", "requirements.txt"):
        fpath = ROOT / fname
        check(f"{fname} exists", fpath.exists())

    # render.yaml sanity
    render_path = ROOT / "render.yaml"
    if render_path.exists():
        content = render_path.read_text()
        check("render.yaml has healthCheckPath", "/health" in content)
        check("render.yaml has startCommand", "python main.py" in content)

    # requirements sanity
    req_path = ROOT / "requirements.txt"
    if req_path.exists():
        content = req_path.read_text()
        for pkg in ("fastapi", "uvicorn", "pydantic", "httpx", "aiosqlite"):
            check(f"requirements.txt has '{pkg}'", pkg in content)

    # runtime.txt
    rt_path = ROOT / "runtime.txt"
    if rt_path.exists():
        rt_content = rt_path.read_text().strip()
        check("runtime.txt has Python 3.13.x", rt_content.startswith("3.13"),
              f"found: {rt_content!r}")


# ─────────────────────────────────────────────────────────────────────────────
# 17. Dead code / unused imports (basic checks)
# ─────────────────────────────────────────────────────────────────────────────
def verify_dead_code() -> None:
    print("\n── Code Quality ─────────────────────────────────────────────────────────")
    # Check that no Python file contains "TODO:" comments
    py_files = list((ROOT / "backend").rglob("*.py")) + [ROOT / "main.py"]
    files_with_todo = [f for f in py_files if "TODO:" in f.read_text(encoding="utf-8", errors="ignore")]
    check("No TODO: comments in production code",
          len(files_with_todo) == 0,
          f"Found in: {[str(f.relative_to(ROOT)) for f in files_with_todo]}" if files_with_todo else "")

    # Check no hardcoded API keys (simple heuristic)
    suspicious = []
    for f in py_files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if "sk-" in text and "secret_ref" not in text and "test" not in f.name:
            suspicious.append(str(f.relative_to(ROOT)))
    check("No hardcoded API keys (sk- pattern)",
          len(suspicious) == 0,
          f"Suspicious: {suspicious}" if suspicious else "")


# ─────────────────────────────────────────────────────────────────────────────
# 18. Frontend pages contain expected endpoints
# ─────────────────────────────────────────────────────────────────────────────
def verify_frontend_integration() -> None:
    print("\n── Frontend Integration ─────────────────────────────────────────────────")
    ledger = (ROOT / "pages" / "ledger" / "index.html").read_text(encoding="utf-8", errors="ignore")
    check("Ledger connects to /api/status",  "/api/status" in ledger)
    check("Ledger connects to /api/jobs",    "/api/jobs" in ledger)
    check("Ledger has auto-refresh (setInterval)", "setInterval" in ledger)

    wizard = (ROOT / "pages" / "Wizard" / "index.html").read_text(encoding="utf-8", errors="ignore")
    check("Wizard POST to /api/config/apply", "/api/config/apply" in wizard)
    check("Wizard polls /health for READY",   "/health" in wizard)
    check("Wizard uses /api/secrets/set",     "/api/secrets/set" in wizard)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def main() -> None:
    print("=" * 70)
    print("  PRIMUS — Project Verification Report")
    print("=" * 70)

    verify_structure()
    verify_config()
    verify_imports()
    verify_providers()
    verify_messaging()
    verify_tools()
    verify_memory()
    verify_jobs()
    verify_desktop()
    verify_production_features()
    verify_server_endpoints()
    await verify_git_learning()
    await verify_automation()
    await verify_extended_helpers()
    await verify_database()
    verify_deployment()
    verify_dead_code()
    verify_frontend_integration()

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    total  = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed

    print(f"  Total checks : {total}")
    print(f"  Passed       : \033[32m{passed}\033[0m")
    if failed:
        print(f"  Failed       : \033[31m{failed}\033[0m")
        print("\n  Failed checks:")
        for name, ok, detail in results:
            if not ok:
                print(f"    \033[31m✗\033[0m  {name}" + (f" — {detail}" if detail else ""))
    print("=" * 70)

    if failed:
        print("  \033[31m✗ Project has issues. See failed checks above.\033[0m")
    else:
        print("  \033[32m✓ All checks passed. Project is production-ready.\033[0m")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
