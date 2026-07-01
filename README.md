# Primus — An Open-Source Operating System for AI

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
| **Wizard Dashboard** | One-question-at-a-time setup flow that generates `config.json` |
| **Backend Engine** | Loads `config.json`, wires up provider/memory/messaging/tools, runs the assistant |

Full technical breakdown: see [ARCHITECTURE.md](./ARCHITECTURE.md)
Build sequence and milestones: see [ROADMAP.md](./ROADMAP.md)
Week-by-week execution plan: see [PLAN.md](./PLAN.md)

---

## Features

- **Multi-provider AI routing** — OpenRouter, OpenAI, Google AI Studio, Anthropic, Kimi, Z.AI, Groq, Ollama, all behind one interface
- **Messaging everywhere** — Telegram, WhatsApp, Discord, Email, Google Chat, SMS, Home Assistant
- **Layered memory** — short-term, long-term, context, and knowledge memory
- **Git learning** — extracts skills, stack, and architecture from repos instead of memorizing raw code
- **Proactive notifications** — the assistant initiates when something useful happens
- **Scheduling & jobs** — recurring commands become background jobs with checkpointing
- **Desktop agent** — terminal, Python, Docker, Git, browser, local models when your machine is on
- **Browser automation** — search, extract, fill forms, generate reports
- **Pluggable tool system** — every capability (search, vision, memory, terminal, planning) is an independent, swappable tool
- **Context engine** — selects only relevant memories/files/chats per request instead of dumping full history into every prompt

---

## Status

🚧 Early build phase. See [ROADMAP.md](./ROADMAP.md) for what's live vs. planned.

## Tech Stack

_(to be finalized in PLAN.md as each system is scaffolded)_

## Installation

_(added once System 3 — Backend Engine — has a working v1)_

## License

MIT (proposed — confirm before first public release)
