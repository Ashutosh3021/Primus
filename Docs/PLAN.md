# Execution Plan

This is the tactical, week-by-week plan for building Primus. It maps directly onto ROADMAP.md's phases but breaks each into concrete daily/weekly deliverables so progress is trackable and stalling is visible early.

Assumption: solo build, part-time around coursework — adjust pace, not order, if actual availability differs.

---

## Week 1 — Phase 0 + Phase 1 (Scaffolding + AI Routing)

| Day | Deliverable |
|---|---|
| 1 | Repo created, folder structure from ARCHITECTURE.md §12, `config.schema.json` drafted with `version: 1` field, DB schema sketch (§14) committed as a doc |
| 2 | Secrets module (§2a): OS keyring client + `.env` fallback, `secret_ref` resolution — done **before** any real API key is entered anywhere. Logging module (§13): structured JSON, per-stream files, redaction of any `secret_ref`-resolved value |
| 3 | `AIProvider` interface (behind `api.provider.*`, §15), capabilities flags (§4a), Ollama adapter (no API key needed, fastest to test) |
| 4 | Anthropic adapter + OpenRouter adapter, both resolving keys via `secret_ref` only |
| 5 | Router: selects provider from config, checks capabilities before unsupported calls. Unit tests for router + adapters + secrets redaction |

**End-of-week check:** can I swap `provider.name` in config.json between ollama/anthropic/openrouter and get a real response each time, with zero other code changes — and does grepping the logs for my API key come back empty?

---

## Week 2 — Phase 2 (Backend Engine Core)

| Day | Deliverable |
|---|---|
| 1–2 | Boot sequence skeleton: config load → version migration chain (no-op for v1) → provider load → stub listener |
| 3 | Structured error handling — bad/missing config fails with a clear message, not a stack trace. Error recovery baseline (§5a): failed provider call retries once, then surfaces clearly |
| 4 | CLI interface: `send` a message via stdin, get response via stdout |
| 5 | Wire boot sequence into the logging module from Week 1, integration test for full boot → response → shutdown cycle, plus a test for the retry-then-fail path |

**End-of-week check:** backend runs as a persistent process, survives a full session of manual CLI testing without crashing — and surviving a deliberately broken API key without hanging or crashing.

---

## Week 3 — Phase 3 (Memory)

| Day | Deliverable |
|---|---|
| 1 | Short-term memory: in-process conversation buffer |
| 2 | Long-term memory: SQLite implementing the `users` + `memories` tables from ARCHITECTURE.md §14, exposed only via `api.memory.*` |
| 3 | Write path — extraction logic that turns a conversation into a stored "conclusion," not raw transcript |
| 4 | Read path — inject relevant long-term memory into next request |
| 5 | Test: state a preference, restart process, confirm it's recalled. Confirm no memory write ever contains a `secret_ref`-resolved value |

**End-of-week check:** two separate CLI sessions, second one correctly recalls something from the first.

---

## Week 4 — Phase 4 (Tool System v1)

| Day | Deliverable |
|---|---|
| 1 | `Tool` interface + Plugin Registry (§8a) — tools self-register a descriptor, no `if tool == "x"` branching anywhere |
| 2 | Web Search tool |
| 3 | Memory tool (explicit read/write calls the LLM can invoke, via `api.memory.*`) |
| 4 | File Operations tool (read/write local files in a sandboxed dir) |
| 5 | Test: ask a live-info question (search triggers), ask a "what did I tell you" question (memory triggers). Add a throwaway 4th tool to confirm it registers with zero router changes |

**End-of-week check:** LLM correctly picks the right tool without being told which one to use, and a new tool can be dropped in as a single file.

---

## Week 5 — Phase 5 (Messaging: Telegram)

| Day | Deliverable |
|---|---|
| 1 | Message normalizer: platform-agnostic shape |
| 2 | Telegram bot registration + webhook/polling setup |
| 3 | Wire Telegram → normalizer → backend → normalizer → Telegram reply |
| 4 | Error recovery (§5a): retry-with-backoff on connection drop, isolated so it can't take down the rest of the backend; malformed message and rate-limit handling |
| 5 | End-to-end test with real Telegram account, including killing the connection mid-session and confirming auto-reconnect |

**End-of-week check:** message the bot from your phone, get a memory-aware, tool-capable response back.

**🎯 Portfolio checkpoint #1:** Phases 0–5 alone are a legitimate, demoable, deployable project — "provider-agnostic AI backend with memory, tools, and Telegram integration." If nothing else gets built, this is already a strong repo. Deploy it, write a demo GIF, ship it.

---

## Week 6 — Phase 6 (Wizard Dashboard)

| Day | Deliverable |
|---|---|
| 1–2 | Frontend scaffold, one-question-at-a-time flow UI |
| 3 | Provider + API key + model selection steps — key is written to the secrets store (§2a) via the wizard's secrets client, `config.json` only ever receives the resulting `secret_ref` |
| 4 | Telegram + memory + tools configuration steps (bot token handled the same way as the API key) |
| 5 | Generates valid config.json (`version: 1`) matching schema; test with a completely fresh install |

**End-of-week check:** someone with zero prior config can go from nothing to a working Telegram bot purely through the wizard, and neither their API key nor their bot token ever lands in `config.json` in plain text.

---

## Week 7 — Phase 7 (Job System & Scheduling)

| Day | Deliverable |
|---|---|
| 1 | Job definition model (cron-like schedule) |
| 2 | Worker + trigger loop |
| 3 | Checkpointing for long jobs |
| 4 | Job completion → Messaging notification |
| 5 | Test: "every day at 9am, summarize commits" runs unattended |

**End-of-week check:** a scheduled job fires and delivers a Telegram notification without any manual trigger.

---

## Week 8 — Phase 8 (Git Learning)

| Day | Deliverable |
|---|---|
| 1–2 | Repo scanner: stack detection, structure analysis |
| 3 | Summary extraction (purpose, architecture, open tasks) |
| 4 | Write extracted summary into Knowledge Memory |
| 5 | Test against one of your real repos (e.g. PrepIQ) — sanity check accuracy |

**End-of-week check:** pointing the assistant at a real repo produces an accurate summary, not hallucinated content.

---

## Week 9 — Phase 9 (Context Engine)

| Day | Deliverable |
|---|---|
| 1–2 | Relevance selection logic across memory layers |
| 3 | Swap Phase 5's "dump everything" prompt assembly for selective retrieval |
| 4 | Token usage benchmark: before vs. after |
| 5 | Regression test — confirm no relevant context is lost |

**End-of-week check:** measurable token reduction with no answer-quality regression on a fixed test conversation set.

**🎯 Portfolio checkpoint #2:** Phases 6–9 add wizard onboarding, scheduling, and a genuinely interesting context engine — strong technical talking points for interviews (token efficiency, relevance retrieval).

---

## Week 10 — Phase 10 (Desktop Agent)

| Day | Deliverable |
|---|---|
| 1 | Pairing flow (§10a): backend generates a pairing code, agent exchanges it for a device token on first run, token stored via the secrets module from Week 1 |
| 2 | Local agent process, separate from cloud backend, authenticates every connection with its device token |
| 3 | Terminal, Docker, local Git tools registered when agent is online and paired |
| 4 | Graceful degradation logic when desktop is offline |
| 5 | Test: same request behaves differently (and correctly) online vs. offline, and an unpaired/spoofed agent connection is rejected |

---

## Weeks 11–13 — Phase 11 (Additional Messaging Platforms)

One platform per few days, each following the Telegram pattern from Week 5:
- Discord
- WhatsApp
- Email
- (Google Chat / SMS / Home Assistant as time allows — lowest priority, cut first if behind schedule)

---

## Week 14 — Phase 12 (Browser Automation)

| Day | Deliverable |
|---|---|
| 1–2 | Browser tool: navigate, extract |
| 3 | Form filling |
| 4 | Report generation from extracted data |
| 5 | Test: unattended multi-step browsing task completes correctly |

---

## Week 15 — Phase 13 (Promotional Dashboard)

| Day | Deliverable |
|---|---|
| 1–2 | Static site scaffold, feature list, screenshots |
| 3 | Docs page, install guide |
| 4 | Live demo embed/link |
| 5 | Final polish pass across README, ARCHITECTURE, ROADMAP for consistency with what's actually built |

---

## Rules to Prevent Drift

1. **No phase starts before its dependency's milestone is met.** If Week 3's memory milestone isn't hit, Week 4 doesn't start on schedule — the plan slips, it doesn't skip.
2. **Every week ends with something runnable**, not just code that compiles. If there's nothing to demo, the week isn't done.
3. **Checkpoint deploys are not optional.** Ship Checkpoint #1 (end of Week 5) even if the rest of the roadmap is still in progress — this is what protects the portfolio if time runs out later.
4. **Cut order if behind schedule:** Home Assistant → SMS → Google Chat → WhatsApp are the lowest-value messaging platforms for a portfolio audience; drop these first, never drop Phases 0–9.
