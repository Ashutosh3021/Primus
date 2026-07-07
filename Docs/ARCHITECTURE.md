# Architecture

This document describes how Primus is structured internally: the three top-level systems, how data flows between them, and how each of the 10 features maps to concrete modules.

---

## 1. System Overview

```
┌─────────────────────┐   ┌──────────────────────┐   ┌────────────────────┐
│ Promotional          │   │ Wizard Dashboard      │   │ Backend Engine      │
│ Dashboard             │   │ (Setup / Config)      │   │ (The Assistant)     │
│                       │   │                        │   │                     │
│ - Marketing only      │   │ - One question at a    │   │ - Loads config.json │
│ - No AI connection    │   │   time                 │   │ - Wires providers,  │
│ - Docs, features,     │──▶│ - Produces config.json │──▶│   memory, messaging,│
│   install guide       │   │                        │   │   tools             │
└─────────────────────┘   └──────────────────────┘   └────────────────────┘
```

These three systems do **not** share runtime state. The only contract between the Wizard and the Backend is `config.json`. The Promotional Dashboard never talks to the backend at all.

---

## 1a. Canonical Request Flow

The earlier per-system diagrams (§4 routing, §5 messaging) are simplified. This is the actual end-to-end path a message takes once every subsystem exists:

```
Telegram (or any platform)
   ↓
Messaging Normalizer
   ↓
Router (auth, rate limit, platform → internal request)
   ↓
Memory (load relevant short/long-term entries)
   ↓
Context Engine (select only relevant slices — see §9)
   ↓
Provider (selected AI model, via §4 routing)
   ↓
Tools (invoked by the LLM as needed — see §8)
   ↓
Response
   ↓
Memory (write back any new conclusions)
   ↓
Messaging Normalizer
   ↓
Reply to originating platform
```

Every box in this chain is a separately testable module (see §12). Early phases (v1) skip the Context Engine box and go straight from Memory to Provider — it's only inserted once §9 is built.

---

## 2. Configuration Flow

The Wizard asks a linear sequence of questions and writes each answer into a growing config object:

```
Choose Provider → Enter API Key → Choose Model → Select Messaging Platform(s)
→ Configure Platform Credentials → Configure Memory → Configure Tools → Write config.json
```

Example shape of `config.json`:

```json
{
  "version": 1,
  "provider": {
    "name": "openrouter",
    "secret_ref": "provider.openrouter.api_key",
    "model": "anthropic/claude-sonnet"
  },
  "messaging": {
    "telegram": { "enabled": true, "secret_ref": "messaging.telegram.bot_token" },
    "discord": { "enabled": false }
  },
  "memory": {
    "enabled": true,
    "backend": "sqlite"
  },
  "tools": {
    "web_search": true,
    "browser": true,
    "terminal": false
  }
}
```

Note there is no raw secret in this file — `secret_ref` is a lookup key into the secrets store described in §2a. `config.json` is safe to commit to a private dotfile backup or sync across machines; the secrets store is not.

The Backend Engine treats this file as its **only** source of truth for structure and behavior at boot. It never asks setup questions itself — if a required field is missing, it fails fast with a clear error pointing back to the Wizard.

---

## 2a. Secrets Management

API keys, bot tokens, and any other credential **never** live in `config.json` or in plain text long-term. This is a v1 requirement, not a later hardening pass — a leaked `config.json` on a public repo is the single most likely security incident for this project.

**v1 approach:** OS keyring (via a library like `keytar`/`keyring`) as the primary store, with a `.env`-based fallback for headless/server deployments where no OS keyring is available (e.g. a VPS).

```
Wizard collects secret
   ↓
Written to OS Keyring (desktop) or .env (server), never to config.json
   ↓
config.json stores only a secret_ref key
   ↓
Backend resolves secret_ref → actual value at runtime, in-memory only
```

Rules:
- Secrets are never logged (see §6a — logging must redact anything resolved from a `secret_ref`).
- Secrets are never written to Long-term Memory, even indirectly (e.g. a job summary must not quote a token).
- `.env` fallback ships with a `.gitignore` entry from Phase 0, and the Wizard warns explicitly if it's about to fall back to `.env` on a machine where that file could be synced or committed.

**Later:** full encrypted-at-rest secrets store (e.g. age/sops-style file encryption) for teams or multi-device sync, once single-user OS keyring stops being sufficient.

---

## 3. Backend Engine — Boot Sequence

```
config.json
   ↓
Load Provider        (instantiate the correct AI client behind a common interface)
   ↓
Load Memory           (open the configured memory backend)
   ↓
Load Messaging        (start listeners for each enabled platform)
   ↓
Load Tools             (register only the tools enabled in config)
   ↓
Start Listening
```

Each stage is independent and swappable. If Discord is disabled, the Discord module is never imported. If a tool is disabled, it's never registered with the tool router.

---

## 3a. Config Versioning

`config.json` carries a top-level `version` field from day one (see the example in §2), even though v1 only ever produces `version: 1`. This exists so that future feature additions — e.g. a `voice` block in a hypothetical v2 — don't silently break every config generated before that point.

```
Backend reads config.json
   ↓
Reads "version" field
   ↓
version < current? → run migration chain (v1 → v2 → v3 ...) → in-memory upgraded config
version == current? → use as-is
version > current? → fail fast: "config was written by a newer version of Primus"
```

Each migration is a small, pure function: `migrate_v1_to_v2(config) → config`. Migrations are additive and never delete fields the user hasn't asked to remove — a missing new field gets a safe default, not a crash.

---

## 4. AI Routing

The backend never hardcodes a provider. Every provider implements the same interface:

```
interface AIProvider {
  send(messages, tools?) → Response
  stream(messages, tools?) → AsyncIterator<Chunk>
}
```

Flow:

```
Incoming Request → Router → Selected Provider (per config.json) → Normalized Response
```

Adding a new provider means writing one adapter that satisfies `AIProvider` — zero changes to routing logic, memory, or messaging.

**v1 providers:** OpenRouter, Anthropic, Ollama (covers paid, free-tier, and local — proves the abstraction works across all three categories)
**Later providers:** OpenAI, Google AI Studio, Kimi, Z.AI, Groq

### 4a. Provider Capabilities

Providers are not interchangeable in what they support. Rather than the backend discovering this by trial and error (a failed tool call, a rejected image), each adapter declares its capabilities up front:

```json
{
  "name": "openai",
  "supports": {
    "vision": true,
    "streaming": true,
    "function_calling": true,
    "audio": true
  }
}
```

The Router and Tool Registry (§8a) both consult this before attempting a call:

```
Request needs Vision
   ↓
Router checks selected provider's capabilities
   ↓
Supported → proceed
Not supported → fail early with a clear message, or fall back to a capable provider if one is configured
```

This turns "the model silently ignored the image" into "Primus told the user upfront that the configured provider doesn't support vision." Capability flags are stored as static metadata per adapter, not queried live — they change rarely enough that a manual update on provider API changes is acceptable for v1.

---

## 5. Messaging System

Every platform is a doorway into the same backend. Internally, all inbound messages are normalized into one shape before hitting the router:

```
Platform Message → Normalize → { userId, text, attachments, platform } → Backend → LLM → Backend → Normalize Back → Platform Reply
```

```
Telegram  ──┐
Discord   ──┤
WhatsApp  ──┼──▶  Normalizer  ──▶  Backend Core  ──▶  Normalizer  ──▶  Reply to originating platform
Email     ──┤
SMS       ──┘
```

**v1 platform:** Telegram only (smallest integration surface, good docs, free bot API — proves the normalization pattern).
**Later platforms:** Discord, WhatsApp, Email, Google Chat, SMS, Home Assistant.

### 5a. Error Recovery

None of the boot-sequence stages in §3 are allowed to take the whole backend down if they fail. Each stage fails in isolation and the backend degrades rather than crashes:

```
Telegram connection drops
   ↓
Messaging module logs a warning (see §6a) and enters retry-with-backoff
   ↓
Backend core keeps running — other platforms, jobs, and scheduled tasks are unaffected
   ↓
On reconnect, module resumes and logs recovery
```

General rule applied to every subsystem, not just messaging:

| Failure | Behavior |
|---|---|
| A messaging platform is unreachable | Retry with exponential backoff, other platforms unaffected |
| A provider call fails | Retry once, then either fall back to a secondary configured provider or return a clear error to the user — never a silent hang |
| A tool call fails | Return the error to the LLM as a tool result so it can explain or retry, not a hard crash |
| Memory write fails | Log and continue — a failed memory write should never block a response reaching the user |
| A job fails mid-run | Checkpoint is preserved, job is retried on next scheduled trigger or marked failed with a notification, never silently dropped |

---

## 6. Memory

Four layers, each with a distinct purpose and lifetime:

| Layer | Contents | Lifetime |
|---|---|---|
| **Short-term** | Current conversation turns | Session |
| **Long-term** | Projects, preferences, career goals, interests, schedules | Permanent |
| **Context** | Current repo, current files, current task | Until task changes |
| **Knowledge** | Extracted facts from Git, documents, images, past chats | Permanent, append-only |

Storage principle: **store conclusions, not raw data.**

- ❌ Store the image → ✅ Store "user likes strawberries"
- ❌ Store the whole repo → ✅ Store project summary, stack, architecture, goals

**v1 scope:** Short-term + Long-term only, backed by a simple local store (SQLite or JSON, decided during scaffolding). Context and Knowledge layers depend on the Context Engine and Git Learning modules (later phases).

---

## 7. Git Learning

Instead of embedding raw source code, this module extracts:

- Repository purpose (first paragraph of README)
- Programming languages in use (by file extension frequency)
- Frameworks and key dependencies (from `requirements.txt`, `package.json`, etc.)
- Architectural pattern (inferred from folder and file names)
- Open tasks (TODO / FIXME / HACK comments across source files)
- Recent commit messages (last 10 via `git log`)
- Current branch name

Output is written into **Project Memory** as structured key/value entries (`repo.<name>.summary`, `repo.<name>.languages`, `repo.<name>.frameworks`, `repo.<name>.open_tasks`), not raw text. This makes the summaries immediately available to the Context Engine for selective prompt injection.

A `git_learning` job type is registered at startup so scans can be scheduled via the cron system (`POST /api/jobs` with `name: "git_learning"` and `params.repo_path`). Scans can also be triggered directly via `POST /api/git-learning/scan`.

All repo I/O runs via `asyncio.to_thread` so it never blocks the event loop.

---

## 8. Tool System

Every capability is an independent tool behind a common interface:

```
interface Tool {
  name: string
  description: string
  run(input) → Result
}
```

The Tool Router only registers tools enabled in `config.json`. The LLM sees tool descriptions and decides when to call them; the backend executes and returns results.

**v1 tools:** Web Search, Memory (read/write), File Operations
**Later tools:** Browser, Vision, Terminal, Planning, Spotify, Code Execution, Context Engine (as a tool the LLM can explicitly invoke)

### 8a. Plugin Registry

Tools are not wired up with conditional logic (`if tool == "browser"`). Every tool self-registers into a central registry at startup, and the registry — not scattered if/else branches — is what the LLM sees and the router calls:

```
Backend boot
   ↓
Each tool module exports a descriptor: { name, description, inputSchema, run() }
   ↓
Tool Registry collects all descriptors where config.tools[name] == true
   ↓
Registry is handed to the Provider as the available tool list
   ↓
LLM picks a tool by name → Registry looks up run() → executes → returns result
```

Adding a new tool means writing one file that exports a descriptor matching the `Tool` interface (§8) and nothing else changes — no router edits, no provider-specific wiring. This is the same pattern as §4's provider adapters, applied to tools.

---

## 9. Context Engine

Rather than sending full conversation history and full memory into every prompt, the Context Engine selects only what's relevant per request:

```
Incoming Request
   ↓
Relevance Selection ← [Long-term Memory, Context Memory, Knowledge Memory, Recent Files]
   ↓
Assembled Prompt (only relevant slices)
   ↓
Provider
```

This is a **later-phase system** — it depends on Memory and Git Learning already producing structured, queryable data. Building it before Memory exists means it has nothing to select from.

---

## 10. Job System & Scheduling

Long-running or recurring tasks become Jobs rather than blocking requests:

```
Command ("every Friday, send internship report")
   ↓
Create Job (cron-like schedule stored)
   ↓
Worker picks up Job at trigger time
   ↓
Checkpoint (long jobs save progress)
   ↓
Continue / Retry on failure
   ↓
Finished → Notify User (via Messaging System)
```

Depends on: Backend Engine (stable core), Tools (jobs call tools), Messaging (jobs notify via messaging).

---

## 11. Desktop Agent

When the user's machine is on, an additional local agent process exposes machine-local tools (terminal, Docker, local Git, Ollama, local browser) to the same Tool Router. When the machine is off, the cloud backend continues operating with only cloud-available tools — the assistant degrades gracefully rather than failing.

```
Desktop ON  → Tool Router includes: Terminal, Docker, Local Git, Ollama, Local Browser
Desktop OFF → Tool Router includes: Cloud-only tools (Web Search, hosted Memory, hosted Browser)
```

### 11a. Automation Engine

Built on top of the desktop tool set, the Automation Engine chains tools into multi-step workflows without blocking the event loop:

```
POST /api/automation/run  { "workflow": "git_status" }
   ↓
AutomationEngine.run(workflow)
   ↓
Step 0: GitTool("status")      → output saved as step_0 result
Step 1: GitTool("log -5")      → can reference {step_0} in params
   ↓
WorkflowResult { success, steps[], total_duration_ms }
```

Workflows are either built-in by name (`git_status`, `python_env_info`, `project_health`) or defined inline as JSON. Serialise/deserialise via `AutomationEngine.to_dict()` / `from_dict()` for storage in the job system.

### 10a. Desktop Agent Authentication

The Desktop Agent runs terminal and Docker access on the user's real machine — it must prove it's actually the user's device before the cloud backend grants it those tools. Without this, anything that can reach the backend's network endpoint could impersonate a desktop agent and get local code execution.

**v1 approach:** pairing code, generated once by the Wizard/backend and entered into the desktop agent on first run — same pattern as pairing a smart TV or a CLI tool with a web account.

```
Backend generates short-lived pairing code
   ↓
User enters code into Desktop Agent on first launch
   ↓
Backend issues a long-lived device token, scoped to that one agent
   ↓
Agent stores token via the same secrets mechanism as §2a (OS keyring)
   ↓
Every subsequent connection: Agent presents device token → Backend verifies → grants local tool access
```

Device tokens are revocable individually (lost laptop, compromised machine) without affecting cloud-only operation or other paired devices. **Later:** upgrade to per-device certificates if multiple agents per user becomes a real use case.

---

## 12. Module Boundaries (for repo structure)

```
/promotional-dashboard      # static marketing site (pages/Dashbord/index.html) — connects to /health + /api/dashboard
/wizard-dashboard           # form flow → writes config.json + writes secrets via secrets client (pages/Wizard/index.html)
/ledger-dashboard           # live metrics dashboard (pages/ledger/index.html)
/backend
  /providers                # one file per AI provider, all implement AIProvider + capabilities
  /messaging                # one file per platform, all normalize to common shape
  /memory                   # short-term / long-term / context / knowledge
  /tools                    # one file per tool, all implement Tool interface, self-register (§8a)
  /jobs                     # scheduler + worker + checkpointing
  /context_engine           # relevance selection logic + cron scheduler
  /git-learning             # repo → structured summary extraction, job registration
  /desktop                  # DesktopConnector + local tools + AutomationEngine
  /router                   # provider selection logic, capability checks
  /secrets                  # OS keyring / .env resolution, secret_ref lookups (§2a)
  /logger.py                # structured logger, redaction rules (§13)
  /db                       # schema, async SQLite stores
  /api                      # internal service layer all modules call through (§15)
  server.py                 # FastAPI HTTP server — all endpoints
  startup.py                # async startup / shutdown sequence
```

Each top-level backend folder is independently testable and has no reverse dependency on the folders above it in the build order (see ROADMAP.md).

---

## 13. Logging

Logging is a first-class subsystem, not an afterthought bolted onto each module. Every other module writes to it through one shared interface rather than calling `console.log` directly.

Separate log streams, so a specific failure class can be searched without noise from the others:

| Stream | Contents |
|---|---|
| `ai_requests` | Every provider call: model, token counts, latency, success/failure — never the raw prompt if it contains resolved secrets |
| `tool_calls` | Which tool, which input, result summary, duration |
| `errors` | Stack traces, failed stage, retry attempts |
| `jobs` | Job start/checkpoint/completion/failure |
| `notifications` | What was sent, to which platform, delivery status |

Rule inherited from §2a: any value resolved from a `secret_ref` is redacted (`***`) before it reaches any log stream, with no exceptions — this is enforced at the logging interface itself, not left to each caller to remember.

**v1 approach:** structured JSON logs to local files, one file per stream, rotated by size. **Later:** optional shipping to a hosted log viewer for multi-device setups.

---

## 14. Database Schema (Sketch)

`memory` uses SQLite in v1 (§6). Even without writing migrations yet, the entity shape should be settled before Phase 3 starts coding, so later features don't force a schema rewrite.

```
users            (id, created_at)
memories         (id, user_id, layer[short|long|context|knowledge], key, value, created_at, updated_at)
jobs             (id, user_id, schedule_cron, tool_or_command, last_run_at, status)
tools            (id, name, enabled, config_json)
providers        (id, name, model, secret_ref, enabled)
notifications    (id, user_id, platform, message, sent_at, status)
devices          (id, user_id, device_token_hash, paired_at, last_seen_at)  -- desktop agent pairing, §10a
```

`memories.layer` is what separates short-term from long-term from knowledge — one table, not four, keeps queries and the Context Engine's relevance selection (§9) simpler. Real column types and indexes get finalized when Phase 3 starts (see ROADMAP.md), but the entity list itself shouldn't change much after this sketch.

---

## 15. Internal API Layer

Modules do not call each other directly (`memory.js` importing `provider.js` importing `jobs.js`). Every cross-module interaction goes through a thin internal service layer:

```
Tool needs to write memory
   ↓
Tool calls api.memory.write(entry)      NOT: import memory from '../memory'
   ↓
API layer validates, forwards to Memory module, returns result
```

This is deliberately boring — a set of typed functions per module (`api.provider.send()`, `api.memory.read()`, `api.jobs.schedule()`) — not a network-hop microservice layer. The value isn't distribution, it's **enforced independence**: a module can be gutted and rewritten as long as its `api.*` surface stays the same, which is what makes the phase-by-phase build order in ROADMAP.md actually safe to follow without earlier phases breaking as later ones are added.

---

## 16. Testing Strategy

Three tiers, applied consistently across every module from Phase 0 onward:

| Tier | Scope | Example |
|---|---|---|
| **Unit** | One function/module in isolation, dependencies mocked | Router selects the correct provider adapter given a config object |
| **Integration** | Two or more real modules together, external services still mocked | Tool Registry + a real tool + a mocked provider correctly completes a tool-call round trip |
| **End-to-end** | Full stack, real external services where feasible | A real Telegram message triggers a real (sandboxed) provider call and a real reply is received |

Each phase in ROADMAP.md's milestone is, in practice, an end-to-end test for that phase — the milestones were written to double as e2e test specs. Unit and integration tests are written alongside each module in the same week it's built (see PLAN.md), not retrofitted later.
