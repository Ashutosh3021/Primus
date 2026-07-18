# HTTP API Reference

Primus exposes a FastAPI server. Interactive docs are available at
`/api/docs` (Swagger) and `/api/redoc` (ReDoc). All endpoints return structured
JSON. This document is the canonical list of every endpoint in v1.3.0.

> Every chat/messaging path funnels through the single runtime
> `backend.api.handle_message`. There is no interface-specific AI logic.

---

## Health & Status

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Lightweight health check (Render / load balancers) |
| GET | `/api/status` | Full status: provider, model, memory, jobs, health, metrics, uptime, **every lifecycle module** |
| GET | `/api/diagnostics` | Startup timeline, system info, module states |
| GET | `/api/dashboard` | Aggregated metrics panel (uptime, jobs, AI, Telegram, errors, memory) |
| GET | `/api/metrics` | Counters, gauges, timers |
| GET | `/api/logs` | Recent log lines from any log stream |
| GET | `/api/capabilities` | Provider + desktop capability flags |
| GET | `/api/recovery` | Circuit-breaker and failure state |
| GET | `/api/trigger/status` | Trigger/keepalive subsystem status |

---

## Config & Secrets

| Method | Path | Description |
|---|---|---|
| GET | `/api/config` | Current config (secrets stripped) |
| POST | `/api/config/validate` | Validate a config dict without applying |
| POST | `/api/config/apply` | Write `config.json` and re-initialise all modules |
| POST | `/api/secrets/set` | Store a secret in the OS keyring or `.env` |
| GET | `/api/secrets/check/{secret_ref:path}` | Whether a secret exists |
| GET | `/api/secrets/stored` | Which secret refs are stored (names only) |

---

## Providers & Models

| Method | Path | Description |
|---|---|---|
| GET | `/api/providers` | All configured providers + per-provider state |
| GET | `/api/models` | Available models for the active/current provider |
| POST | `/api/provider` | Switch active provider `{ "provider": "openai" }` |
| POST | `/api/model` | Switch active model `{ "model": "gpt-4o" }` |
| POST | `/api/auto` | Toggle Auto Router `{ "enabled": true }` |

---

## Chat & Context

| Method | Path | Description |
|---|---|---|
| POST | `/api/chat` | Send a message `{ "messages": [...], "user_id", "conversation_id" }` and get a response |
| GET | `/api/context` | Constructed context for a conversation |
| POST | `/api/compact` | Summarize the session to reclaim context budget |
| GET | `/api/context/memory` | Memory entries backing the context |
| POST | `/api/context/memory` | Write a context-memory entry |
| DELETE | `/api/context/memory` | Delete a context-memory entry |

---

## Persona

| Method | Path | Description |
|---|---|---|
| GET | `/api/personas` | Presets, active persona, active detail (5 fields), custom text |
| POST | `/api/persona` | Switch preset or set a custom persona `{ "name": "analyst" }` / `{ "custom_text": "..." }` |

Persona architecture: see `Docs/ARCHITECTURE.md` §6a.

---

## Skills

| Method | Path | Description |
|---|---|---|
| GET | `/api/skills` | List all skills (with active flag) |
| POST | `/api/skill` | Create or update a skill `{ "name", "prompt", "active" }` |
| POST | `/api/skill/import` | Import a skill from JSON `{ "skill": {...} }` |
| GET | `/api/skill/export?name=` | Export a skill as JSON |
| POST | `/api/skill/active` | Toggle a skill active `{ "name", "active" }` |
| DELETE | `/api/skill?name=` | Delete a skill |

Skill architecture: see `Docs/ARCHITECTURE.md` §6b.

---

## Jobs, Scheduler & Notifications

| Method | Path | Description |
|---|---|---|
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/{job_id}` | Single job by ID |
| GET | `/api/cron` | Enabled cron schedules |
| GET | `/api/notifications` | Recent notifications |

---

## Memory

| Method | Path | Description |
|---|---|---|
| GET | `/api/memory` | Memory entries for a user |

---

## Git Learning

| Method | Path | Description |
|---|---|---|
| POST | `/api/git-learning/scan` | Scan a repo → Project memory `{ "repo_path": ".", "save_to_memory": true }` |
| GET | `/api/git-learning/jobs` | All `git_learning` jobs |

---

## Automation

| Method | Path | Description |
|---|---|---|
| POST | `/api/automation/run` | Execute a named or inline workflow `{ "workflow": "git_status" }` |
| GET | `/api/automation/workflows` | List built-in automation workflows |

---

## Frontend ↔ Backend Contract

| Page | Endpoints used |
|---|---|
| Wizard (`pages/Wizard`) | `/api/config/apply`, `/api/secrets/set`, `/health` (poll `startup_done`) |
| Ledger (`pages/ledger`) | `/api/status`, `/api/jobs`, `/api/dashboard` (auto-refresh 30s) |
| Chat (`pages/chat`) | `/api/chat`, `/api/personas`, `/api/skills`, `/api/status` |
| Promotional (`pages/Dashbord`) | `/api/status`, `/api/dashboard` (auto-refresh 30s) |

All pages default to `window.location.origin` and honour
`window.PRIMUS_API_URL` when the backend is on a different host/port.
