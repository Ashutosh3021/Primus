# Deployment Instructions

## Local Development

### Prerequisites
- Python 3.13
- pip

### Setup

```bash
# 1. Clone / enter the project
cd Primus

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure secrets (.env or OS keyring)
#    Create .env in the project root:
echo PROVIDER_OLLAMA_API_KEY=not-required > .env

# 5. Verify config.json exists (default ships with the repo)
#    Or run the Wizard to generate one:
#    Open pages/Wizard/wizard.html in a browser

# 6. Start the backend
python main.py
```

The server starts at http://localhost:8000.

### Useful endpoints

| URL | Purpose |
|---|---|
| `http://localhost:8000/health` | Quick health check |
| `http://localhost:8000/api/status` | Full status (Ledger uses this) |
| `http://localhost:8000/api/dashboard` | Aggregated metrics (uptime, jobs, AI, Telegram, errors, memory) |
| `http://localhost:8000/api/git-learning/scan` | Scan repo and save to Project memory |
| `http://localhost:8000/api/automation/workflows` | List built-in automation workflows |
| `http://localhost:8000/api/providers` | Configured providers + state |
| `http://localhost:8000/api/models` | Available models for the active provider |
| `http://localhost:8000/api/personas` | Persona presets + active persona |
| `http://localhost:8000/api/skills` | List skills |
| `http://localhost:8000/api/context` | Constructed context for a conversation |
| `http://localhost:8000/api/recovery` | Circuit-breaker / failure state |
| `http://localhost:8000/api/trigger/status` | Trigger/keepalive status |
| `http://localhost:8000/api/docs` | Interactive API docs (Swagger) |
| `http://localhost:8000/api/redoc` | API docs (ReDoc) |

Full endpoint reference: [Docs/API.md](./API.md). Slash-command reference:
[Docs/COMMANDS.md](./COMMANDS.md).

### Opening the frontend pages

The HTML pages are static files. Open them directly in a browser:

- `pages/Wizard/index.html` — first-time setup
- `pages/ledger/index.html` — live dashboard (backend must be running)
- `pages/Dashbord/index.html` — promotional / marketing page with metrics panel

The Wizard and Ledger connect to `window.location.origin` by default.
Set `window.PRIMUS_API_URL` before the page scripts run if the backend
is on a different host/port.

---

## Render Deployment

### One-time setup

1. Push the repository to GitHub / GitLab.
2. On [render.com](https://render.com), click **New → Web Service**.
3. Connect the repository. Render auto-detects `render.yaml`.
4. In the service **Environment** tab, add your secret variables
   (see `Docs/ENV_VARS.md`).
5. Click **Deploy**.

### render.yaml summary

```yaml
buildCommand:  pip install --no-cache-dir -r requirements.txt
startCommand:  python main.py
healthCheckPath: /health
disk:
  mountPath: /opt/render/project/src   # persists primus.db
  sizeGB: 1
```

### Port binding

`main.py` reads `PORT` from the environment via `os.getenv("PORT", "8000")`.
Render sets `PORT` automatically. No manual configuration required.

### Persistent disk

`render.yaml` mounts a 1 GB disk at the project root so `primus.db`
(SQLite database) and log files survive deploys and restarts.

### Health checks

Render polls `GET /health` every 30 seconds. The endpoint returns:

```json
{
  "status": "healthy",
  "startup_done": true,
  "uptime_seconds": 123.4,
  "version": 1
}
```

The service is marked healthy as soon as `startup_done` is `true`.

### Restart behaviour

Render automatically restarts the service on crash (free plan: zero-downtime
restart is not available; paid plan supports zero-downtime deploys).

### Environment variable changes

Any change to environment variables triggers an automatic redeploy.

---

## Startup Sequence

```
python main.py
    ↓
uvicorn starts FastAPI (backend/server.py)
    ↓
lifespan: startup_async()
    ├── Load config.json
    ├── Init SQLite database
    ├── Init memory system
    ├── Init tool manager
    ├── Init job manager + scheduler
    ├── Init AI router (resolves provider secret)
    ├── Init messaging platforms (resolves tokens)
    └── Init desktop connector
    ↓
start_messaging() / start_jobs() / start_desktop()
    ↓
Backend ready — /health returns { startup_done: true }
```

### Graceful shutdown

On SIGTERM (Render stops the service), the lifespan context manager:
1. Stops desktop connector
2. Stops messaging platforms
3. Stops job manager and scheduler
4. Exits cleanly

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `SecretNotFoundError` | Missing env var | Add the variable to `.env` or Render dashboard |
| `ConfigNotFoundError` | `config.json` missing | Run the Wizard or copy the default file |
| `ConfigVersionError` | Config written by newer Primus | Regenerate via the Wizard |
| Port already in use | Another process on 8000 | Set `PORT=8001` in environment |
| Ollama not found | Ollama not running | Run `ollama serve` before starting Primus |
| Database locked | Multiple processes | Only one `python main.py` process at a time |
