# Roadmap

This roadmap sequences all 10 systems by **dependency**, not by preference. Each phase only starts once its dependencies are working and tested — building out of order produces exactly the kind of half-finished sprawl this project is trying to avoid.

Every phase ends with something runnable and demoable, not just code that compiles.

---

## Phase 0 — Repo Scaffolding
**Depends on:** nothing
- Set up module boundaries from ARCHITECTURE.md §12
- `config.schema.json` defining the full eventual config shape, including `version` field (§3a)
- Secrets module: OS keyring client + `.env` fallback, `secret_ref` resolution (§2a) — wired up before any real API key touches the repo
- Logging module: structured JSON, per-stream files, redaction of anything resolved via `secret_ref` (§13)
- Database schema sketch committed as a doc (§14) — not yet implemented, just agreed
- Internal API layer skeleton: empty `api.*` namespace that later modules will fill in (§15)
- CI: lint + basic test runner wired up (unit tier from §16)
- **Milestone:** empty backend boots, reads a stub `config.json` (with `version: 1`), resolves a dummy secret from the keyring without ever printing it to a log, exits cleanly

---

## Phase 1 — AI Routing
**Depends on:** Phase 0
- `AIProvider` interface, exposed only through `api.provider.*` (§15)
- Adapters: OpenRouter, Anthropic, Ollama — each declares a capabilities flag set (§4a)
- Router selects provider from config, checks capabilities before attempting unsupported calls
- API keys resolved exclusively via `secret_ref` (§2a) — never read from `config.json` directly
- **Milestone:** `send("hello")` returns a real response from any of the 3 providers by flipping a config value — zero code changes between them. A request requiring vision against a non-vision provider fails with a clear message instead of a silent error

---

## Phase 2 — Backend Engine Core
**Depends on:** Phase 1
- Boot sequence: load config → run version migration chain (§3a) → load provider → start listening (stub for messaging)
- Structured logging (§13) + error handling for missing/invalid config
- Error recovery baseline (§5a): a failing provider call retries once, then surfaces a clear error instead of hanging
- Unit + integration tests for the boot sequence (§16)
- **Milestone:** backend runs as a long-lived process, accepts a message via CLI/stdin, returns an LLM response end-to-end, and survives an intentionally broken provider call without taking the whole process down

---

## Phase 3 — Memory (Short-term + Long-term)
**Depends on:** Phase 2
- Short-term: in-memory conversation buffer per session
- Long-term: persistent store (SQLite) implementing the schema sketch from ARCHITECTURE.md §14 (`memories` table with `layer` column, `users` table)
- Store-conclusions-not-raw-data principle enforced at write time
- Exposed only through `api.memory.*` (§15) — no other module touches the SQLite file directly
- **Milestone:** backend remembers a stated preference across two separate CLI sessions

---

## Phase 4 — Tool System (v1 tools)
**Depends on:** Phase 2 (can run parallel to Phase 3)
- `Tool` interface + Plugin Registry (§8a) — tools self-register, no `if tool == "x"` branching
- v1 tools: Web Search, Memory read/write, File Operations
- **Milestone:** LLM correctly decides to call Web Search for a live-info question and Memory for a "what did I tell you" question, and a new tool can be added by dropping in one file with no router changes

---

## Phase 5 — Messaging (Telegram only)
**Depends on:** Phase 2, Phase 3, Phase 4
- Message normalizer (platform → common shape → platform)
- Telegram bot integration
- Retry-with-backoff on connection drop, isolated so it can't take down the rest of the backend (§5a)
- **Milestone:** full round trip — message the Telegram bot, backend uses memory + tools, replies in Telegram. Killing the network connection mid-session and restoring it results in an automatic reconnect, not a crash

---

## Phase 6 — Wizard Dashboard
**Depends on:** Phase 1–5 (needs to know the real config shape)
- One-question-at-a-time flow: provider → key → model → Telegram → memory → tools
- API keys and tokens are written to the secrets store (§2a), never into `config.json` — the wizard writes a `secret_ref`, not the raw value
- Writes valid `config.json` (with `version: 1`) matching the schema from Phase 0
- **Milestone:** a fresh user with zero config can go from "nothing" to "working Telegram bot" through the wizard alone, no manual file editing, and their API key never appears in plain text anywhere on disk

---

## Phase 7 — Job System & Scheduling
**Depends on:** Phase 2, Phase 4, Phase 5
- Recurring command → Job definition
- Worker + checkpointing for long-running jobs
- Job completion triggers a Messaging notification
- **Milestone:** "every day at 9am, summarize my repo commits" runs unattended and delivers a Telegram message

---

## Phase 8 — Git Learning
**Depends on:** Phase 3 (writes into Long-term/Knowledge Memory)
- Repo → structured summary (stack, architecture, purpose, open tasks)
- Feeds Knowledge Memory layer
- **Milestone:** pointing the assistant at a real repo (e.g. PrepIQ) produces an accurate one-paragraph summary of stack and purpose, stored in memory

---

## Phase 9 — Context Engine
**Depends on:** Phase 3, Phase 8
- Relevance selection across Long-term, Context, and Knowledge memory
- Replaces "dump everything into the prompt" with selective retrieval
- **Milestone:** measurable token reduction on a multi-turn conversation vs. Phase 5 baseline, with no loss of relevant context in responses

---

## Phase 10 — Desktop Agent
**Depends on:** Phase 4 (extends the Tool Router with local-only tools), Phase 2a secrets (device token storage)
- Pairing flow: backend generates a code, agent exchanges it for a device token on first run (§10a) — this ships *before* any local tool is enabled, not after
- Local agent process: terminal, Docker, local Git, Ollama, local browser
- Graceful degradation when desktop is offline
- **Milestone:** the same assistant answers a "run this script and tell me the output" request when desktop is on, and gracefully declines with an explanation when it's off. An unpaired process attempting to connect as a desktop agent is rejected

---

## Phase 11 — Additional Messaging Platforms
**Depends on:** Phase 5 (proven normalization pattern)
- Discord, WhatsApp, Email, Google Chat, SMS, Home Assistant — added one at a time, each with its own milestone (round-trip message test)

---

## Phase 12 — Browser Automation
**Depends on:** Phase 4, Phase 10 (can run cloud-only or desktop-assisted)
- Open sites, fill forms, extract data, generate reports as a tool
- **Milestone:** "find the top 3 internship postings on X site and summarize them" completes unattended

---

## Phase 13 — Promotional Dashboard
**Depends on:** everything above having at least a v1 (no point marketing vaporware)
- Static site: features, docs, install guide, screenshots, live demo link
- **Milestone:** a stranger can land on the site, understand the project in under a minute, and follow install instructions successfully

---

## Sequencing Summary

```
0 Scaffolding
1 AI Routing
2 Backend Core
3 Memory ──────────┐
4 Tools ────────────┼──▶ 5 Messaging (Telegram) ──▶ 6 Wizard
                    │
                    └──▶ 7 Jobs
8 Git Learning ──▶ 9 Context Engine
10 Desktop Agent
11 More Messaging Platforms
12 Browser Automation
13 Promotional Dashboard
```

Nothing later in this list should be started before its dependencies hit their milestone. Each milestone is a real, demoable checkpoint — that's what goes in the portfolio incrementally, not just the eventual finished product.

---

## Cross-Cutting: Testing Strategy

Testing is not its own phase — it's applied inside every phase above, per ARCHITECTURE.md §16:

- Every phase's **milestone** doubles as its end-to-end test spec.
- Unit tests for a module are written the same week that module is built (see PLAN.md), not retrofitted afterward.
- Integration tests are added whenever two modules first connect (e.g. Tool Registry + Memory tool in Phase 4, Messaging + Memory + Tools in Phase 5).

If a phase's milestone can't be demonstrated with a passing automated test, the phase isn't actually done — it just looks done.
