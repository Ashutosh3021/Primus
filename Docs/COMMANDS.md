# Command Reference

Primus accepts slash-commands from **every** interface — REST (`POST /api/chat`),
Telegram (bot), and the Chat page. All commands route through the single runtime
`backend.api.handle_message`, so behavior is identical everywhere.

> Commands that need no arguments (e.g. `/list-skills`) still work when sent as
> bare text. A normal message (no leading `/`) is treated as a chat turn.

---

## Provider & Model

### `/provider <name>`
Switch the active provider. Persisted atomically to `config.json`.

```
/provider openai
→ ok: provider switched to openai
/provider            (no arg)
→ error: usage hint, no change
```

### `/model <name>`
Switch the active model for the current provider.

```
/model gpt-4o
```

### `/auto`
Toggle the Auto Router. When enabled, Primus picks the best provider per request
by cost, capability, and recent health instead of using the manually selected
one.

```
/auto
→ ok: auto mode enabled/disabled
```

---

## Persona

### `/persona`
Show the currently active persona (preset name or `custom`).

### `/persona <preset>`
Switch to a built-in preset: `default`, `analyst`, `critic`, `tutor`, `coach`,
`pirate`, `assistant`, `researcher`.

```
/persona analyst
```

### `/persona <free text>`
Any non-preset text becomes a **custom persona** — it is stored as the custom
persona prompt and injected into every subsequent prompt.

```
/persona Act like a friendly, concise pirate
```

Persona architecture: see `Docs/ARCHITECTURE.md` §6a.

---

## Context

### `/compact`
Summarize the current conversation to reclaim context budget. Safe on an empty
session (returns a no-op result).

---

## Skills

### `/skill-maker [name :: instructions]`
Create a skill. With arguments, creates immediately. With **no** arguments,
launches a guided wizard (name → prompt → confirm).

```
/skill-maker greet :: Say hello warmly
/skill-maker            (wizard: name, then prompt, then Yes/No)
```

### `/list-skills`
List all skills, including which are active.

### `/<skill-name> <input>`
Invoke a skill. Its instructions are injected into the prompt automatically.

```
/greet friend
```

### `/<skill-name> delete`
Delete a skill.

```
/greet delete
```

### `/export-skill <name>`
Export a skill as JSON (for sharing / backup).

### `/import-skill <json>`
Import a skill from a JSON string.

```
/import-skill {"name":"gamma","prompt":"Be gamma.","active":false}
```

Skill architecture: see `Docs/ARCHITECTURE.md` §6b.

---

## Other

### `/cancel`
Cancel an in-progress conversational wizard (e.g. the `/skill-maker` wizard).
