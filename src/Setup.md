# OreX Setup

How to run OreX locally. For features, pages and security notes, see the [README](../README.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (installs the required Python version automatically)
- A modern web browser

No database server or cloud account is needed. Docker is optional (see below).

## Setup

1. **Clone the repository**

   ```
   git clone https://github.com/Zechariah-Guo/OreX.git
   cd OreX
   ```

2. **Install dependencies** (creates `.venv` from `uv.lock`, including dev tools)

   ```
   uv sync
   ```

3. **Run the application**

   ```
   cd src
   uv run python run.py
   ```

4. **Open in browser**

   Go to [http://127.0.0.1:4000](http://127.0.0.1:4000)

The SQLite database is created and seeded with the 9 ores on first run.

## Running with Docker (optional)

This runs the production stack locally (Nginx, Gunicorn with one worker, SQLite).

1. Copy `.env.example` to `.env` and set `SECRET_KEY`. Set `SESSION_COOKIE_SECURE=0` when testing over plain http.
2. Run `docker compose up --build`.
3. Open [http://localhost:8080](http://localhost:8080).

## Running Tests

```
uv run pytest
```

Skip the slow 2FA property tests with `-m "not slow"` and the real-browser tests with `-m "not browser"`.

## Configuration

Game settings are in `src/app/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `SECRET_KEY` | `orex-local-dev-secret...` | Flask session secret. Read from the `SECRET_KEY` environment variable. The app refuses to start in production without it |
| `DATABASE_PATH` | `src/data/orex.db` | SQLite database file |
| `DEFAULT_BALANCE` | `10000` | Starting balance for new players |
| `TICK_INTERVAL` | `20` | Seconds between market price updates |
| `RATE_LIMIT_WINDOW` | `900` | Login rate limit window in seconds (15 min) |
| `RATE_LIMIT_MAX` | `5` | Max login attempts per window |

Deployment settings (`SECRET_KEY`, `OREX_TRUST_PROXY`, `SESSION_COOKIE_SECURE`, avatar storage, VAPID keys) are environment variables. See `.env.example`.

### Web Push notifications (optional)

Players can opt in under Settings > Notifications. Push is off until the server has VAPID keys:

1. Generate a key pair once: `uv run python scripts/admin/generate_vapid_keys.py`
2. Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT` (a `mailto:` or `https://` contact) in the environment (`set VAPID_PUBLIC_KEY=...` in `cmd`) or in `.env` for Docker.

Browsers only allow push on https or localhost. A push is sent only when the player has had no visible OreX page open for about a minute.

## Resetting the Database

Stop the server, delete the database file, and start it again:

```
del src\data\orex.db
cd src
uv run python run.py
```

The database is recreated and reseeded with the 9 ores.

## Managing Dependencies

| Task | Command |
|------|---------|
| Add a runtime dependency | `uv add <pkg>` |
| Add a dev-only dependency | `uv add --dev <pkg>` |
| Upgrade one package | `uv lock --upgrade-package <pkg>` then `uv sync` |

Commit both `pyproject.toml` and `uv.lock` after any change.

## Project Structure

```
OreX/
├── pyproject.toml           # Dependencies (locked in uv.lock) and pytest config
├── Dockerfile, docker-compose.yml, docker/nginx/
├── .env.example             # Environment variable template
├── src/
│   ├── run.py               # Development entry point
│   ├── schema.sql, seed.sql # Database schema and initial ore data
│   ├── app/                 # Flask app: config, database, models, routes/, market/, tutorial/, utils/
│   ├── templates/           # Jinja2 pages and HTMX partials
│   ├── static/              # CSS, JS, images, audio, vendored libraries
│   └── data/                # SQLite database (auto-created from schema.sql; no migrations, delete it after a schema change)
├── scripts/                 # dev/ tools and admin/ production tools (see scripts/README.md)
├── tests/                   # Pytest test suite
└── docs/                    # Planning documents and assets
```

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, Flask 3.1 |
| Database | SQLite3 |
| Templating | Jinja2 |
| Auth | Flask-Login, Werkzeug, PyOTP (2FA) |
| CSRF | Flask-WTF |
| Frontend | Vanilla JavaScript, HTMX, Alpine.js, Cropper.js |
| Charts | ApexCharts |
| Testing | Pytest, Hypothesis |
| Deployment | Gunicorn, Nginx, Docker Compose |
