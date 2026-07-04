# Primus v1 — An Open-Source Operating System for AI

> Not another chatbot. An operating system for AI — provider-agnostic, memory-driven, and everywhere you are.

---

## Why Primus?

AI has become fragmented. One assistant lives in ChatGPT, another in Claude, another in Gemini, another on your desktop. Every conversation starts from scratch. Every ecosystem locks you in. Your work is scattered across apps that don't talk to each other and don't remember you between sessions.

Primus exists to unify those experiences into one persistent assistant that belongs to the user, not the provider.

---

## What This Is

Most AI assistants belong to a company. ChatGPT belongs to OpenAI. Claude belongs to Anthropic. Gemini belongs to Google.

**Primus belongs to you.**

It's infrastructure, not intelligence. You bring the API keys, the provider, the messaging platforms, and the memory. Primus orchestrates all of it into one persistent assistant that lives across every surface you use — Telegram, Discord, WhatsApp, desktop, browser — remembering your projects, your preferences, and your goals without you re-explaining yourself every session.

Think of it as Windows, but for AI: an operating system that applications (models) plug into, not a product that locks you into one model.

---

## Core Philosophy

1. **The AI belongs to the user.** No subscriptions. You provide the keys, the provider, the model. Nothing belongs to the platform.
2. **The AI exists everywhere.** Same assistant on Telegram, Discord, WhatsApp, desktop, or browser.
3. **The AI remembers.** Projects, preferences, career goals, past conversations — without resending context every time.
4. **The AI works, not just responds.** Scheduled jobs, browsing, file reading, repo analysis — running while you do something else.
5. **The AI costs almost nothing.** Free-tier providers (OpenRouter, Gemini, Groq, Ollama) are first-class citizens, not afterthoughts.

---

## Architecture at a Glance

Primus is three independent systems:

| System | Purpose |
|---|---|
| **Promotional Dashboard** | Marketing site — explains the project, no AI connection |
| **Wizard Dashboard** | One-question-at-a-time setup flow that generates and sends `config.json` to the backend |
| **Backend Engine** | FastAPI HTTP server — loads config, wires provider/memory/messaging/tools, serves the API |

The only contract between the Wizard and the Backend is `config.json`. No raw secrets ever touch that file.

Full technical breakdown: [Docs/ARCHITECTURE.md](./Docs/ARCHITECTURE.md)
Deployment guide: [Docs/DEPLOY.md](./Docs/DEPLOY.md)
Environment variables: [Docs/ENV_VARS.md](./Docs/ENV_VARS.md)

---

## Features — v1

### Multi-Provider AI Routing
Route every request through a single interface regardless of which provider is configured. Swap providers by changing one line in `config.json` — zero code changes.

| Provider | Type |
|---|---|
| OpenRouter | Cloud — unified access to hundreds of models |
| OpenAI | Cloud — GPT series |
| Anthropic | Cloud — Claude series |
| Google Gemini | Cloud — Gemini series |
| Groq | Cloud — fast inference |
| Moonshot / Kimi | Cloud — Kimi series |
| Z.AI / GLM | Cloud — GLM series |
| Ollama | Local — runs entirely on your machine, no API key |

Each provider declares its capabilities (vision, streaming, function calling) upfront. The router checks before attempting unsupported calls instead of letting them fail silently.

---

### Messaging Everywhere

Every platform normalizes to the same internal message shape. The same assistant responds to Telegram, and later Discord, WhatsApp, and every other configured platform — without duplicated logic.

| Platform | Status |
|---|---|
| Telegram | v1 — full bot integration with long polling |
| Discord | Config ready — module wired |
| WhatsApp | Config ready |
| Email | Config ready |
| Google Chat | Config ready |
| SMS (Twilio) | Config ready |
| Home Assistant | Config ready |

Platforms with "Config ready" are fully wired into the startup sequence and the Wizard. Adding the bot token and enabling them in `config.json` activates them.

---

### Layered Memory

Primus stores conclusions, not raw data. Four layers with distinct lifetimes:

| Layer | Contents | Lifetime |
|---|---|---|
| Short-term | Current conversation turns | Session |
| Long-term | Projects, preferences, goals, interests | Permanent |
| Project | Active repo, current task, stack details | Until task changes |
| Preference | How you like things done | Permanent |

Backed by SQLite. The memory API is the only thing that touches the database — no module accesses it directly.

---

### Context Engine

Instead of dumping the full conversation history and all memories into every prompt, the Context Engine selects only what is relevant to the current query. Keyword-based relevance scoring in v1, with vector-based retrieval planned for v2.

---

### Tool System

Every capability is an independent, self-registering tool. The LLM sees available tools and decides when to call them. Adding a new tool means writing one file — no router edits, no conditional branches.

| Tool | Description |
|---|---|
| `web_search` | DuckDuckGo search — live answers to current-events questions |
| `terminal` | Execute shell commands on the local machine |
| `filesystem` | Read, write, and list local files |
| `python` | Execute Python code locally |
| `git` | Run git commands in local repositories |
| `ollama` | Call a local Ollama model directly as a tool |
| `docker` | Manage Docker containers and images |

Tools are enabled per-user in `config.json`. Disabled tools are never registered and never visible to the LLM.

---

### Desktop Agent

When your machine is on, the Desktop Agent exposes local tools (terminal, filesystem, Git, Python, Docker, Ollama) to the same tool router used by the cloud backend. When your machine is off, the assistant degrades gracefully to cloud-only tools rather than failing.

Capability detection runs at startup: the agent probes for `git`, `ollama`, and `docker` and flags only what is actually available.

---

### Job System & Scheduler

Long-running or recurring tasks become Jobs instead of blocking requests.

- Cron-expression scheduling stored in SQLite
- Worker loop with per-job checkpointing
- Retry with configurable max attempts
- Job completion triggers a notification via configured messaging platforms
- `DailyBriefingJob` ships as a built-in example

---

### Notifications

The `NotificationEngine` stores every sent notification in the database and can dispatch through any configured messaging platform. The Ledger dashboard shows notification history in real time.

---

### HTTP API

A FastAPI server exposes every backend capability over HTTP so the Wizard and Ledger can communicate with it. All endpoints return structured JSON.

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Lightweight health check for Render / load balancers |
| `/api/status` | GET | Full status: provider, model, memory, jobs, health, metrics, uptime |
| `/api/diagnostics` | GET | Startup diagnostics and system info |
| `/api/config` | GET | Current config (secrets stripped) |
| `/api/config/validate` | POST | Validate a config dict without applying it |
| `/api/config/apply` | POST | Write config.json and re-initialise all modules |
| `/api/secrets/set` | POST | Store a secret in the OS keyring or .env |
| `/api/chat` | POST | Send a message and get a response |
| `/api/jobs` | GET | List all jobs |
| `/api/jobs/{job_id}` | GET | Single job by ID |
| `/api/metrics` | GET | Collected metrics (counters, gauges, timers) |
| `/api/logs` | GET | Recent log lines from any log stream |
| `/api/memory` | GET | Memory entries for a user |
| `/api/notifications` | GET | Recent notifications |
| `/api/cron` | GET | Enabled cron schedules |
| `/api/capabilities` | GET | Provider and desktop capability flags |
| `/api/recovery` | GET | Circuit breaker and failure state |

Interactive docs available at `/api/docs` (Swagger) and `/api/redoc`.

---

### Secrets Management

API keys, bot tokens, and every other credential are resolved at runtime and never written to `config.json`. The file stores only a `secret_ref` key.

```
Wizard collects secret
    ↓
Written to OS keyring (desktop) or .env (server/Render)
    ↓
config.json stores only: "secret_ref": "provider.openai.api_key"
    ↓
Backend resolves at boot, in memory only — never logged
```

The logging layer redacts any resolved secret value before it reaches any log file or console output.

---

### Health, Metrics, Diagnostics & Recovery

| Subsystem | What it does |
|---|---|
| `HealthChecker` | Registered health checks per module; overall status is healthy / degraded / unhealthy |
| `MetricsRegistry` | Counters, gauges, and timers collected in memory |
| `DiagnosticsManager` | Startup timeline (which modules loaded), system info, uptime |
| `RecoveryManager` | Failure recording, circuit breaker per component, exponential-backoff retry |

---

### Wizard Dashboard

A browser-based setup flow that walks through every configuration option one question at a time.

- Selects provider, model, and messaging platforms
- Validates the API key format (optional live test)
- Stores secrets via `/api/secrets/set` — never in `config.json`
- Sends the completed config to `/api/config/apply`
- Displays module-by-module initialization progress
- Polls `/health` until `startup_done: true`
- Redirects to the Ledger on success

---

### Ledger Dashboard

A live dashboard that auto-refreshes every 15 seconds from the backend.

- Status banner: provider, model, memory, scheduler, desktop, health, uptime
- Job history table with sorting, pagination, and time-range filtering
- Weekly call volume chart
- Cost-by-provider donut chart
- Calls-by-tool bar chart
- Graceful fallback to empty state when backend is unreachable

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend language | Python 3.13 |
| HTTP server | FastAPI + Uvicorn |
| Database | SQLite via aiosqlite |
| HTTP client | httpx (async) |
| Retry logic | tenacity |
| Secrets store | keyring (OS keyring) + python-dotenv (.env fallback) |
| System info | psutil |
| Frontend | Vanilla HTML/CSS/JS — no build step, no framework |
| Charts | Chart.js (CDN) |
| Fonts | Google Fonts (Fraunces, Public Sans, IBM Plex Mono) |
| Deployment | Render (render.yaml included) |

---

## Installation

### Prerequisites

- Python 3.13
- pip

### Local setup

```bash
# 1. Clone the repo
git clone https://github.com/Ashutosh3021/Primus
cd Primus

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your provider secret
#    Option A — .env file (server / headless)
echo PROVIDER_OLLAMA_API_KEY=not-required > .env

#    Option B — OS keyring (desktop)
python -c "import keyring; keyring.set_password('primus', 'provider.ollama.api_key', 'not-required')"

# 5. Start the backend
python main.py
# Server starts at http://localhost:8000

# 6. Open the Wizard to configure (first run)
#    Open pages/Wizard/wizard.html in your browser

# 7. After setup, open the Ledger dashboard
#    Open pages/ledger/index.html in your browser
```

### Render deployment

```bash
# Push to GitHub, then connect to render.com
# render.yaml is already configured — no manual setup needed
# Add your secret env vars in the Render dashboard (see Docs/ENV_VARS.md)
```

Full instructions: [Docs/DEPLOY.md](./Docs/DEPLOY.md)

---

## Project Structure

```
Primus/
├── main.py                     # Entry point — starts uvicorn
├── config.json                 # Runtime configuration (no secrets)
├── requirements.txt            # Pinned dependencies
├── render.yaml                 # Render deployment config
├── runtime.txt                 # Python 3.13
│
├── backend/
│   ├── server.py               # FastAPI HTTP server (integration layer)
│   ├── startup.py              # Async startup / shutdown sequence
│   ├── config.py               # config.json loader and validator
│   ├── constants.py            # Paths, version, log stream names
│   ├── secrets.py              # Secret resolution (keyring → .env)
│   ├── validators.py           # Config validation rules
│   ├── exceptions.py           # Custom exception hierarchy
│   ├── helpers.py              # Signal handler setup
│   ├── logger.py               # Structured JSON logging with redaction
│   ├── health.py               # Health checker
│   ├── diagnostics.py          # Startup diagnostics and system info
│   ├── metrics.py              # Counters, gauges, timers
│   ├── recovery.py             # Circuit breaker and retry logic
│   │
│   ├── api/                    # Internal service layer
│   ├── db/                     # SQLite schema + async stores
│   ├── memory/                 # Context engine + prompt builder
│   ├── providers/              # One file per AI provider
│   ├── messaging/              # One file per platform
│   ├── tools/                  # Tool interface + web search
│   ├── desktop/                # Desktop connector + local tools
│   ├── jobs/                   # Job manager + worker loop
│   ├── context_engine/         # Scheduler + notification engine
│   └── router/                 # AI request router
│
├── pages/
│   ├── Wizard/wizard.html      # Setup wizard
│   ├── ledger/index.html       # Live dashboard
│   └── Dashbord/index.html     # Promotional / marketing page
│
├── Docs/
│   ├── ARCHITECTURE.md         # System design
│   ├── ROADMAP.md              # Build sequence and milestones
│   ├── DEPLOY.md               # Deployment instructions
│   └── ENV_VARS.md             # Environment variable reference
│
└── test/
    ├── verify_project.py       # 171-check project verification script
    ├── test_ai_core.py
    ├── test_phase3.py
    └── test_phase7.py
```

---

## Verification

Run the full project verification at any time:

```bash
python test/verify_project.py
```

```
✓ All checks passed. Project is production-ready.
171 / 171
```

Checks cover: folder structure, all Python imports, config validity, provider registry, messaging platforms, tool registry, memory and database, jobs and scheduler, desktop agent, health/metrics/diagnostics/recovery, every HTTP endpoint, database initialisation, deployment files, code quality (no TODOs, no hardcoded keys), and frontend-backend integration.

---

## Roadmap

| Phase | Status | Description |
|---|---|---|
| 0 — Scaffolding | ✅ Complete | Repo structure, secrets, logging, DB schema |
| 1 — AI Routing | ✅ Complete | 8-provider registry behind a single interface |
| 2 — Backend Core | ✅ Complete | Boot sequence, error recovery, graceful shutdown |
| 3 — Memory | ✅ Complete | SQLite-backed short-term + long-term memory |
| 4 — Tool System | ✅ Complete | Self-registering tool registry, 7 built-in tools |
| 5 — Messaging | ✅ Complete | Telegram integration, normalization layer |
| 6 — Wizard | ✅ Complete | Full setup flow, backend integration |
| 7 — Production Quality | ✅ Complete | Health, metrics, diagnostics, recovery, HTTP API |
| 8 — Git Learning | 🔜 Planned | Repo → structured memory extraction |
| 9 — Context Engine v2 | 🔜 Planned | Vector-based relevance selection |
| 10 — Desktop Agent Auth | 🔜 Planned | Device pairing and token-scoped tool access |
| 11 — More Platforms | 🔜 Planned | Discord, WhatsApp, Email, Google Chat, SMS |
| 12 — Browser Automation | 🔜 Planned | Headless browsing as a first-class tool |

---

## License

MIT
