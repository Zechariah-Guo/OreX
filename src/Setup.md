# OreX

A Minecraft-themed stock market simulation built with Python and Flask. Trade ores like stocks — buy low, sell high, and build your fortune as prices fluctuate every 20 seconds.

## Features

- **9 tradeable ores** — Coal, Iron, Copper, Gold, Lapis Lazuli, Redstone, Emerald, Diamond, Netherite
- **User accounts** — Register, login, and track your portfolio
- **Live market** — Prices update every 20 seconds with trends, bot traders, and random events
- **Trading** — Buy and sell ores with confirmation steps and atomic transactions
- **Portfolio tracking** — View holdings, profit/loss, and total portfolio value
- **Dashboard** — At-a-glance summary of balance, top movers, and recent activity
- **Leaderboard** — Compete against other players and bot traders
- **Transaction history** — Full trade history with pagination and archived transaction filtering
- **HTMX live updates** — Market prices, dashboard, portfolio, and leaderboard auto-refresh every 20 seconds
- **Bot traders** — 9 AI traders compete alongside you on the leaderboard
- **Rate limiting** — Login endpoint protected against brute force attempts

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (installs the required Python version automatically)
- A modern web browser

No other software is required. No database server, no Docker, no cloud accounts.

## Setup

1. **Clone the repository**

   ```
   git clone <repository-url>
   cd at3-major-project-Zechariah-Guo
   ```

2. **Install dependencies** (creates `.venv` from `uv.lock`)

   ```
   uv sync
   ```

3. **Run the application**

   ```
   cd src
   uv run python run.py
   ```

4. **Open in browser**

   Navigate to [http://localhost:4000](http://localhost:4000)

The SQLite database is created and seeded with ore data automatically on first run.

## Usage

1. Create an account on the registration page
2. Browse the market to see all available ores and their current prices
3. Click an ore to view its details, price chart, and place buy/sell orders
4. Check your portfolio to track holdings and profit/loss
5. View the leaderboard to see how you rank against other traders
6. Visit your dashboard for a summary of your performance

## Project Structure

```
at3-major-project-Zechariah-Guo/
├── pyproject.toml           # Python dependencies (locked in uv.lock)
├── src/
│   ├── app/
│   │   ├── __init__.py      # Flask app factory
│   │   ├── config.py        # Configuration
│   │   ├── database.py      # SQLite connection and initialisation
│   │   ├── models.py        # Data access functions
│   │   ├── routes/          # Flask blueprints (auth, market, trade, portfolio, etc.)
│   │   ├── market/          # Market engine (algorithm, bots, events, influence)
│   │   └── utils/           # Validation and formatting helpers
│   ├── templates/           # Jinja2 templates
│   ├── static/              # CSS, JS, images
│   ├── data/                # SQLite database (auto-created)
│   ├── schema.sql           # Database schema
│   ├── seed.sql             # Initial ore data
│   └── run.py               # Application entry point
└── tests/                   # Pytest test suite
```

## Configuration

All configuration is in `src/app/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| SECRET_KEY | `orex-local-dev-secret...` | Flask session secret key |
| DATABASE_PATH | `data/orex.db` | SQLite database file location |
| DEFAULT_BALANCE | `10000` | Starting balance for new users |
| TICK_INTERVAL | `20` | Seconds between market price updates |
| RATE_LIMIT_WINDOW | `900` | Rate limit window in seconds (15 min) |
| RATE_LIMIT_MAX | `5` | Max login attempts per window |
| VAPID_PUBLIC_KEY | _(empty)_ | Web Push public key (environment variable). Push is off unless all three VAPID settings are set |
| VAPID_PRIVATE_KEY | _(empty)_ | Web Push private key (environment variable, keep secret) |
| VAPID_SUBJECT | _(empty)_ | Contact for push services, `mailto:you@example.com` or an `https://` URL |

### Web Push notifications

Players can opt in under Settings > Notifications. Generate the key pair once with
`.venv\Scripts\python.exe scripts\admin\generate_vapid_keys.py`, then set the three `VAPID_*`
variables in the environment before starting the server (`set VAPID_PUBLIC_KEY=...` in
`cmd`, or in `.env` for Docker). Browsers only allow push on https or localhost.
A push is sent only when the player has had no visible OreX page open for about a minute.

## Resetting the Database

Delete the database file and restart the server:

```
del src\data\orex.db
cd src
python run.py
```

The database will be recreated and reseeded with the 9 default ores.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask 3.1 |
| Database | SQLite3 (built-in) |
| Templating | Jinja2 |
| Auth | Flask-Login + Werkzeug |
| CSRF | Flask-WTF |
| Live updates | HTMX |
| Charts | ApexCharts |
| Styling | Plain CSS with custom properties |
| Testing | Pytest, Hypothesis |
