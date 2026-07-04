# Environment Variable Documentation

All secrets are resolved at runtime by `backend/secrets.py`.
The lookup order is: **OS keyring → .env file**.

The mapping from `secret_ref` (in `config.json`) to environment variable
follows this rule:

```
secret_ref  "provider.openai.api_key"
            ↓  replace dots with underscores, uppercase
ENV KEY     PROVIDER_OPENAI_API_KEY
```

---

## Required Variables

| Variable | Purpose | Example |
|---|---|---|
| `PORT` | HTTP port. **Injected automatically by Render.** Do not set manually on Render. | `8000` |

---

## Optional Runtime Variables

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address for uvicorn |
| `LOG_LEVEL` | `info` | Uvicorn log level (`debug`, `info`, `warning`, `error`) |
| `PRIMUS_RELOAD` | `false` | Set to `true` to enable hot-reload (development only) |

---

## Provider Secrets

Exactly one of the following must be set, matching the provider named in `config.json`.

| Variable | Maps to secret_ref | Required when |
|---|---|---|
| `PROVIDER_OPENAI_API_KEY` | `provider.openai.api_key` | `provider.name == "openai"` |
| `PROVIDER_OPENROUTER_API_KEY` | `provider.openrouter.api_key` | `provider.name == "openrouter"` |
| `PROVIDER_ANTHROPIC_API_KEY` | `provider.anthropic.api_key` | `provider.name == "anthropic"` |
| `PROVIDER_GROQ_API_KEY` | `provider.groq.api_key` | `provider.name == "groq"` |
| `PROVIDER_MOONSHOT_API_KEY` | `provider.moonshot.api_key` | `provider.name == "moonshot"` |
| `PROVIDER_GLM_API_KEY` | `provider.glm.api_key` | `provider.name == "glm"` |
| `PROVIDER_GEMINI_API_KEY` | `provider.gemini.api_key` | `provider.name == "gemini"` |
| `PROVIDER_OLLAMA_API_KEY` | `provider.ollama.api_key` | Not required (Ollama is local) |

---

## Messaging Secrets

Set only the variables for platforms enabled in `config.json`.

| Variable | Maps to secret_ref | Platform |
|---|---|---|
| `MESSAGING_TELEGRAM_BOT_TOKEN` | `messaging.telegram.bot_token` | Telegram |
| `MESSAGING_DISCORD_BOT_TOKEN` | `messaging.discord.bot_token` | Discord |
| `MESSAGING_WHATSAPP_ACCESS_TOKEN` | `messaging.whatsapp.access_token` | WhatsApp |
| `MESSAGING_EMAIL_APP_PASSWORD` | `messaging.email.app_password` | Email |
| `MESSAGING_GCHAT_CREDENTIALS_JSON` | `messaging.gchat.credentials_json` | Google Chat |
| `MESSAGING_SMS_AUTH_TOKEN` | `messaging.sms.auth_token` | SMS / Twilio |
| `MESSAGING_HA_TOKEN` | `messaging.ha.token` | Home Assistant |

---

## Local Development (.env file)

Create a `.env` file in the project root (already in `.gitignore`):

```dotenv
# Provider — only the one matching config.json is needed
PROVIDER_OLLAMA_API_KEY=not-required

# Messaging — only enabled platforms
MESSAGING_TELEGRAM_BOT_TOKEN=your_bot_token_here
```

---

## Render Dashboard Setup

1. Open the Render service → **Environment** tab.
2. Add each required variable as a **secret** (not plaintext).
3. `PORT` is set automatically — do not add it manually.
4. After saving, Render redeploys automatically.

---

## Security Rules

- Secrets are **never** written to `config.json`.
- `config.json` stores only `secret_ref` keys, not values.
- The logging layer (`backend/logger.py`) redacts any resolved secret value
  before it reaches any log file or console output.
- The `/api/config` HTTP endpoint strips `api_key` fields before returning
  the config to the browser.
