"""
Git Learning module for Primus.

Scans a local git repository and extracts a structured summary:
  - Repository purpose (from README)
  - Programming languages in use
  - Frameworks / key dependencies
  - Architectural pattern (inferred from folder structure)
  - Open tasks (from TODO comments and commit messages)

The summary is written into the user's Knowledge/Project memory layer
so the Context Engine can inject relevant context automatically.

Usage
-----
    from backend.git_learning import GitLearner
    from backend.db import MemoryStore

    learner = GitLearner("/path/to/repo")
    summary = await learner.learn()
    await learner.save_to_memory(memory_store, user_id="default")
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from backend.db import MemoryStore, MemoryEntry, MemoryLayer
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class RepoSummary:
    """Structured summary extracted from a git repository."""
    path: str
    name: str
    purpose: str = ""
    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    architecture: str = ""
    open_tasks: List[str] = field(default_factory=list)
    recent_commits: List[str] = field(default_factory=list)
    branch: str = "unknown"
    error: Optional[str] = None

    def as_text(self) -> str:
        """Return a concise human-readable summary (stored in memory)."""
        lines = [f"Repository: {self.name}"]
        if self.purpose:
            lines.append(f"Purpose: {self.purpose}")
        if self.languages:
            lines.append(f"Languages: {', '.join(self.languages)}")
        if self.frameworks:
            lines.append(f"Frameworks: {', '.join(self.frameworks)}")
        if self.architecture:
            lines.append(f"Architecture: {self.architecture}")
        if self.branch and self.branch != "unknown":
            lines.append(f"Branch: {self.branch}")
        if self.open_tasks:
            tasks_preview = self.open_tasks[:5]
            lines.append(f"Open tasks ({len(self.open_tasks)} total): " + "; ".join(tasks_preview))
        if self.recent_commits:
            lines.append(f"Recent commits: " + "; ".join(self.recent_commits[:3]))
        return "\n".join(lines)


# ── Language detection ────────────────────────────────────────────────────────

_EXTENSION_MAP: Dict[str, str] = {
    ".py":    "Python",
    ".ts":    "TypeScript",
    ".tsx":   "TypeScript",
    ".js":    "JavaScript",
    ".jsx":   "JavaScript",
    ".java":  "Java",
    ".kt":    "Kotlin",
    ".go":    "Go",
    ".rs":    "Rust",
    ".cpp":   "C++",
    ".c":     "C",
    ".cs":    "C#",
    ".rb":    "Ruby",
    ".php":   "PHP",
    ".swift": "Swift",
    ".r":     "R",
    ".scala": "Scala",
    ".dart":  "Dart",
    ".html":  "HTML",
    ".css":   "CSS",
    ".sql":   "SQL",
    ".sh":    "Shell",
}

_FRAMEWORK_HINTS: Dict[str, List[str]] = {
    "FastAPI":    ["fastapi"],
    "Django":     ["django"],
    "Flask":      ["flask"],
    "React":      ["react", "react-dom"],
    "Next.js":    ["next"],
    "Express":    ["express"],
    "Spring":     ["spring-boot", "springframework"],
    "Rails":      ["rails", "railties"],
    "Laravel":    ["laravel/framework"],
    "Vue":        ["vue"],
    "Angular":    ["@angular/core"],
    "Svelte":     ["svelte"],
    "PyTorch":    ["torch"],
    "TensorFlow": ["tensorflow"],
    "SQLAlchemy": ["sqlalchemy"],
    "Pydantic":   ["pydantic"],
    "Uvicorn":    ["uvicorn"],
}

_ARCH_PATTERNS: Dict[str, List[str]] = {
    "Monolith":      ["server.py", "app.py", "main.py", "index.js", "index.ts"],
    "Microservices": ["docker-compose.yml", "kubernetes", "k8s"],
    "Serverless":    ["serverless.yml", "vercel.json", "netlify.toml", "render.yaml"],
    "MVC":           ["controllers", "models", "views", "templates"],
    "Clean / Layered": ["domain", "application", "infrastructure", "adapters"],
}


# ── GitLearner ────────────────────────────────────────────────────────────────

class GitLearner:
    """
    Scans a git repository and produces a structured RepoSummary.

    All I/O is non-blocking: subprocess calls are wrapped in
    asyncio.to_thread so they never block the event loop.
    """

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()

    # ── Public API ────────────────────────────────────────────────────────────

    async def learn(self) -> RepoSummary:
        """Analyse the repository and return a RepoSummary."""
        summary = RepoSummary(
            path=str(self.repo_path),
            name=self.repo_path.name,
        )
        try:
            await self._detect_languages(summary)
            await self._detect_frameworks(summary)
            await self._detect_architecture(summary)
            await self._extract_purpose(summary)
            await self._extract_open_tasks(summary)
            await self._extract_recent_commits(summary)
            await self._detect_branch(summary)
            logger.info(
                f"[GIT_LEARN] Completed scan of {self.repo_path.name} | "
                f"languages={summary.languages} | "
                f"frameworks={summary.frameworks}"
            )
        except Exception as exc:
            summary.error = str(exc)
            logger.error(f"[GIT_LEARN] Failed to scan {self.repo_path}: {exc}", exc_info=True)
        return summary

    async def save_to_memory(
        self,
        memory_store: MemoryStore,
        user_id: str = "default",
    ) -> None:
        """Learn and persist the summary into Project memory."""
        summary = await self.learn()
        if summary.error:
            logger.warning(f"[GIT_LEARN] Skipping memory save — scan had errors: {summary.error}")
            return

        entries = [
            MemoryEntry(
                user_id=user_id,
                layer=MemoryLayer.PROJECT,
                key=f"repo.{summary.name}.summary",
                value=summary.as_text(),
            ),
            MemoryEntry(
                user_id=user_id,
                layer=MemoryLayer.PROJECT,
                key=f"repo.{summary.name}.languages",
                value=", ".join(summary.languages) or "unknown",
            ),
            MemoryEntry(
                user_id=user_id,
                layer=MemoryLayer.PROJECT,
                key=f"repo.{summary.name}.frameworks",
                value=", ".join(summary.frameworks) or "none detected",
            ),
        ]
        if summary.open_tasks:
            entries.append(MemoryEntry(
                user_id=user_id,
                layer=MemoryLayer.PROJECT,
                key=f"repo.{summary.name}.open_tasks",
                value="\n".join(summary.open_tasks[:20]),
            ))

        for entry in entries:
            await memory_store.add(entry)
            logger.info(f"[GIT_LEARN] Saved memory entry: {entry.key}")

    # ── Detection helpers ─────────────────────────────────────────────────────

    async def _detect_languages(self, summary: RepoSummary) -> None:
        """Count file extensions to determine languages in use."""
        counts: Dict[str, int] = {}
        try:
            all_files = await asyncio.to_thread(self._walk_repo)
            for f in all_files:
                ext = Path(f).suffix.lower()
                lang = _EXTENSION_MAP.get(ext)
                if lang:
                    counts[lang] = counts.get(lang, 0) + 1
            # Sort by frequency, return top 5
            summary.languages = [
                lang for lang, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)
            ][:5]
        except Exception as exc:
            logger.warning(f"[GIT_LEARN] Language detection failed: {exc}")

    async def _detect_frameworks(self, summary: RepoSummary) -> None:
        """Detect frameworks from dependency files."""
        dep_content = ""
        for dep_file in ("requirements.txt", "package.json", "pom.xml",
                         "Cargo.toml", "go.mod", "Gemfile", "pyproject.toml"):
            fpath = self.repo_path / dep_file
            if fpath.exists():
                try:
                    dep_content += fpath.read_text(encoding="utf-8", errors="ignore").lower()
                except Exception:
                    pass

        detected = []
        for framework, hints in _FRAMEWORK_HINTS.items():
            if any(hint.lower() in dep_content for hint in hints):
                detected.append(framework)
        summary.frameworks = detected

    async def _detect_architecture(self, summary: RepoSummary) -> None:
        """Infer architectural pattern from folder/file names."""
        try:
            all_names = set()
            for item in self.repo_path.iterdir():
                all_names.add(item.name.lower())

            for arch, indicators in _ARCH_PATTERNS.items():
                if any(ind.lower() in all_names for ind in indicators):
                    summary.architecture = arch
                    return
            summary.architecture = "General"
        except Exception as exc:
            logger.warning(f"[GIT_LEARN] Architecture detection failed: {exc}")
            summary.architecture = "Unknown"

    async def _extract_purpose(self, summary: RepoSummary) -> None:
        """Read the first non-empty paragraph of README as the purpose."""
        for readme_name in ("README.md", "README.rst", "README.txt", "README"):
            readme = self.repo_path / readme_name
            if readme.exists():
                try:
                    text = readme.read_text(encoding="utf-8", errors="ignore")
                    # Strip markdown headings and find first real paragraph
                    lines = [l.strip() for l in text.splitlines()]
                    para_lines = []
                    in_para = False
                    for line in lines:
                        clean = re.sub(r"^#+\s*", "", line)  # strip headings
                        if clean and not clean.startswith(("---", "===", "```", "<!--")):
                            para_lines.append(clean)
                            in_para = True
                        elif in_para and not line:
                            break
                    purpose = " ".join(para_lines).strip()
                    # Truncate to ~200 chars
                    summary.purpose = purpose[:200] + ("…" if len(purpose) > 200 else "")
                    return
                except Exception as exc:
                    logger.warning(f"[GIT_LEARN] README read failed: {exc}")

    async def _extract_open_tasks(self, summary: RepoSummary) -> None:
        """Collect TODO/FIXME/HACK comments from source files."""
        pattern = re.compile(r"(TODO|FIXME|HACK|XXX)\s*[:\-]?\s*(.+)", re.IGNORECASE)
        tasks: List[str] = []
        try:
            source_files = await asyncio.to_thread(self._walk_repo, max_files=300)
            for fpath in source_files:
                ext = Path(fpath).suffix.lower()
                if ext not in _EXTENSION_MAP:
                    continue
                try:
                    text = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                    for match in pattern.finditer(text):
                        tag = match.group(1).upper()
                        msg = match.group(2).strip()[:120]
                        tasks.append(f"[{tag}] {msg}")
                        if len(tasks) >= 50:
                            break
                except Exception:
                    pass
                if len(tasks) >= 50:
                    break
            summary.open_tasks = tasks
        except Exception as exc:
            logger.warning(f"[GIT_LEARN] Task extraction failed: {exc}")

    async def _extract_recent_commits(self, summary: RepoSummary) -> None:
        """Get the last 10 commit messages via git log."""
        try:
            result = await asyncio.to_thread(
                self._run_git, ["log", "--oneline", "-10"]
            )
            if result:
                summary.recent_commits = [line.strip() for line in result.splitlines() if line.strip()]
        except Exception as exc:
            logger.warning(f"[GIT_LEARN] git log failed: {exc}")

    async def _detect_branch(self, summary: RepoSummary) -> None:
        """Get current branch name."""
        try:
            result = await asyncio.to_thread(
                self._run_git, ["rev-parse", "--abbrev-ref", "HEAD"]
            )
            if result:
                summary.branch = result.strip()
        except Exception as exc:
            logger.warning(f"[GIT_LEARN] Branch detection failed: {exc}")

    # ── Sync helpers (run via to_thread) ─────────────────────────────────────

    def _walk_repo(self, max_files: int = 500) -> List[str]:
        """Walk the repo and return file paths, skipping common noise dirs."""
        _SKIP_DIRS = {
            ".git", ".venv", "venv", "node_modules", "__pycache__",
            ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
            "target", ".idea", ".vscode",
        }
        files: List[str] = []
        for root, dirs, filenames in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in filenames:
                files.append(os.path.join(root, fname))
                if len(files) >= max_files:
                    return files
        return files

    def _run_git(self, args: List[str]) -> str:
        """Run a git command in the repo directory and return stdout."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""


# ── Job integration ───────────────────────────────────────────────────────────

def register_git_learning_job() -> None:
    """Register GitLearningJob with the job registry (call once at startup)."""
    try:
        from backend.jobs import register_job, BaseJob

        @register_job("git_learning")
        class GitLearningJob(BaseJob):
            """Job that runs GitLearner on a specified repo path."""
            name = "git_learning"

            async def run(self, checkpoint: dict) -> dict:
                repo_path = self.params.get("repo_path", ".")
                user_id = self.params.get("user_id", "default")
                learner = GitLearner(repo_path)
                from backend.db import MemoryStore
                store = MemoryStore()
                await learner.save_to_memory(store, user_id=user_id)
                summary = await learner.learn()
                return {"content": summary.as_text()}

    except Exception as exc:
        logger.warning(f"[GIT_LEARN] Could not register git_learning job: {exc}")


# Register the job at import time
register_git_learning_job()


__all__ = [
    "GitLearner",
    "RepoSummary",
    "register_git_learning_job",
]
