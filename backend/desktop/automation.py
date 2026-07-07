"""
Automation Engine for Primus Desktop Agent.

Provides higher-level, multi-step workflow automation built on top of the
individual desktop tools (terminal, filesystem, git, python, docker, ollama).

Design principles
-----------------
- Each automation is a named, serialisable workflow: a list of steps where
  each step specifies a tool name and its parameters.
- Steps execute sequentially by default.  An optional ``stop_on_failure``
  flag halts the workflow at the first failed step.
- Results from earlier steps can be referenced in later step parameters via
  ``{step_N}`` template variables, where N is the 0-based step index.
- All execution is async-safe and integrates with the existing ToolManager.

Example workflow
----------------
    workflow = Workflow(
        name="setup_project",
        steps=[
            WorkflowStep(tool="terminal",   params={"command": "git clone https://... /tmp/repo"}),
            WorkflowStep(tool="filesystem", params={"operation": "read", "path": "/tmp/repo/README.md"}),
            WorkflowStep(tool="python",     params={"code": "print('done')"}),
        ],
        stop_on_failure=True,
    )
    engine = AutomationEngine(tool_manager)
    result = await engine.run(workflow)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.tools.base import ToolManager, ToolResult
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class WorkflowStep:
    """A single step in an automation workflow."""
    tool: str
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class StepResult:
    """Result of a single workflow step."""
    step_index: int
    tool: str
    success: bool
    content: str
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class WorkflowResult:
    """Aggregated result of running a full workflow."""
    name: str
    steps: List[StepResult] = field(default_factory=list)
    success: bool = True
    stopped_at: Optional[int] = None  # index of step that caused a halt
    total_duration_ms: int = 0

    def as_text(self) -> str:
        """Return a human-readable summary suitable for returning to the LLM."""
        lines = [f"Workflow '{self.name}': {'✓ completed' if self.success else '✗ failed'}"]
        for sr in self.steps:
            status = "✓" if sr.success else "✗"
            desc = f"step {sr.step_index} [{sr.tool}]"
            lines.append(f"  {status} {desc} ({sr.duration_ms} ms)")
            if sr.error:
                lines.append(f"      error: {sr.error}")
            elif sr.content:
                preview = sr.content[:200].replace("\n", " ")
                lines.append(f"      output: {preview}")
        return "\n".join(lines)


@dataclass
class Workflow:
    """A named, serialisable automation workflow."""
    name: str
    steps: List[WorkflowStep]
    stop_on_failure: bool = True
    description: str = ""


# ── Template expansion ────────────────────────────────────────────────────────

_TEMPLATE_RE = re.compile(r"\{step_(\d+)\}")


def _expand_templates(value: Any, step_results: List[StepResult]) -> Any:
    """
    Recursively expand ``{step_N}`` placeholders in strings.

    If step N succeeded, the placeholder is replaced with that step's
    content (stdout/output).  If it failed or doesn't exist, the
    placeholder is replaced with an empty string.
    """
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            idx = int(match.group(1))
            if idx < len(step_results) and step_results[idx].success:
                return step_results[idx].content
            return ""
        return _TEMPLATE_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _expand_templates(v, step_results) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_templates(item, step_results) for item in value]
    return value


# ── AutomationEngine ──────────────────────────────────────────────────────────

class AutomationEngine:
    """
    Executes multi-step automation workflows using the desktop ToolManager.

    The engine is stateless between workflow runs — instantiate it once and
    call ``run()`` as many times as needed.
    """

    def __init__(self, tool_manager: ToolManager):
        self.tool_manager = tool_manager

    async def run(self, workflow: Workflow) -> WorkflowResult:
        """
        Execute all steps in the workflow sequentially.

        Returns a WorkflowResult even when execution fails partway through.
        """
        result = WorkflowResult(name=workflow.name)
        wall_start = time.monotonic()

        logger.info(
            f"[AUTOMATION] Starting workflow '{workflow.name}' "
            f"({len(workflow.steps)} steps, stop_on_failure={workflow.stop_on_failure})"
        )

        for idx, step in enumerate(workflow.steps):
            step_start = time.monotonic()

            # Expand any {step_N} templates in this step's params
            expanded_params = _expand_templates(step.params, result.steps)

            logger.info(
                f"[AUTOMATION] Step {idx}: tool={step.tool} "
                f"| desc={step.description or '(no description)'}"
            )

            tool_result: ToolResult = await self.tool_manager.execute_tool(
                step.tool, **expanded_params
            )

            duration_ms = int((time.monotonic() - step_start) * 1000)
            step_result = StepResult(
                step_index=idx,
                tool=step.tool,
                success=tool_result.success,
                content=tool_result.content or "",
                error=tool_result.error,
                duration_ms=duration_ms,
            )
            result.steps.append(step_result)

            if not tool_result.success:
                logger.warning(
                    f"[AUTOMATION] Step {idx} failed: {tool_result.error}"
                )
                result.success = False
                if workflow.stop_on_failure:
                    result.stopped_at = idx
                    logger.warning(
                        f"[AUTOMATION] Halting workflow at step {idx} "
                        "(stop_on_failure=True)"
                    )
                    break
            else:
                logger.info(
                    f"[AUTOMATION] Step {idx} succeeded "
                    f"({duration_ms} ms, output_len={len(step_result.content)})"
                )

        result.total_duration_ms = int((time.monotonic() - wall_start) * 1000)
        logger.info(
            f"[AUTOMATION] Workflow '{workflow.name}' finished | "
            f"success={result.success} | "
            f"total_duration={result.total_duration_ms} ms"
        )
        return result

    # ── Convenience factory methods ───────────────────────────────────────────

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> Workflow:
        """
        Deserialise a workflow from a plain dict (e.g. from JSON/DB storage).

        Expected shape::

            {
              "name": "my_workflow",
              "description": "optional",
              "stop_on_failure": true,
              "steps": [
                {"tool": "terminal", "params": {"command": "ls"}, "description": "list files"},
                ...
              ]
            }
        """
        steps = [
            WorkflowStep(
                tool=s["tool"],
                params=s.get("params", {}),
                description=s.get("description", ""),
            )
            for s in raw.get("steps", [])
        ]
        return Workflow(
            name=raw.get("name", "unnamed"),
            steps=steps,
            stop_on_failure=raw.get("stop_on_failure", True),
            description=raw.get("description", ""),
        )

    @staticmethod
    def to_dict(workflow: Workflow) -> Dict[str, Any]:
        """Serialise a workflow to a plain dict."""
        return {
            "name": workflow.name,
            "description": workflow.description,
            "stop_on_failure": workflow.stop_on_failure,
            "steps": [
                {
                    "tool": s.tool,
                    "params": s.params,
                    "description": s.description,
                }
                for s in workflow.steps
            ],
        }


# ── Built-in workflow library ─────────────────────────────────────────────────

BUILTIN_WORKFLOWS: Dict[str, Dict] = {
    "git_status": {
        "name": "git_status",
        "description": "Show git status and last 5 commits for a repository",
        "stop_on_failure": False,
        "steps": [
            {"tool": "git", "params": {"command": "status"},  "description": "git status"},
            {"tool": "git", "params": {"command": "log --oneline -5"}, "description": "recent commits"},
        ],
    },
    "python_env_info": {
        "name": "python_env_info",
        "description": "Show Python version and installed packages",
        "stop_on_failure": False,
        "steps": [
            {"tool": "terminal", "params": {"command": "python --version"}, "description": "python version"},
            {"tool": "terminal", "params": {"command": "pip list"},          "description": "installed packages"},
        ],
    },
    "project_health": {
        "name": "project_health",
        "description": "Basic health check: git status + disk usage",
        "stop_on_failure": False,
        "steps": [
            {"tool": "git",      "params": {"command": "status --short"},   "description": "uncommitted changes"},
            {"tool": "terminal", "params": {"command": "python --version"}, "description": "python version"},
        ],
    },
}


def get_builtin_workflow(name: str) -> Optional[Workflow]:
    """Return a built-in workflow by name, or None if not found."""
    raw = BUILTIN_WORKFLOWS.get(name)
    if raw is None:
        return None
    return AutomationEngine.from_dict(raw)


__all__ = [
    "Workflow",
    "WorkflowStep",
    "WorkflowResult",
    "StepResult",
    "AutomationEngine",
    "get_builtin_workflow",
    "BUILTIN_WORKFLOWS",
]
