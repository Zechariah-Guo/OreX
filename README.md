![OreX Logo](docs/assets/OreX-logo.png)

# OreX

A Minecraft-themed stock market simulation built with Python and Flask. Trade ores like stocks: buy low, sell high, and grow your fortune as prices move every 20 seconds alongside a cast of bot traders.

![OreX Features](docs/assets/Feature-Display.png)

## Status

OreX is in active development. Features, balancing, and the database schema may change between versions.

## Features

- **9 tradeable ores**: Coal, Copper, Redstone, Iron, Lapis Lazuli, Gold, Emerald, Diamond, and Netherite, each with its own price range and volatility.
- **Live market**: Prices update every 20 seconds, driven by trends, support/resistance levels, player and bot influence, and rare market events that cause price shocks.
- **Trading**: Buy and sell with confirmation steps and atomic transactions. Standard mode caps each holding at 500 units.
- **Stop-loss and take-profit**: Set SL/TP levels on holdings and let the market engine close them automatically.
- **Advanced Mode**: An unlockable prestige layer (reach $100,000 net worth, then buy it for $50,000) that removes the holding cap and enables short selling with margin, collateral, tick fees, and squeeze prices.
- **Price charts**: Interactive ore charts with time range filters.
- **Dashboard, Portfolio and Finances**: Balance, top movers, holdings, profit/loss, capital breakdown, short exposure, and cash flow.
- **Leaderboard and public profiles**: Compete against other players and 9 bot traders, and view any player's public profile.
- **Daily login bonus**: A three-day bonus ladder to help new players get started.
- **Inbox and notifications**: Trade fills, SL/TP triggers, bonus reminders, and advancements arrive as toasts and inbox messages.
- **Advancements**: Minecraft-style achievements for trading milestones.
- **Interactive tutorials**: Guided tours for new players and for Advanced Mode.
- **Accounts**: Registration, login, avatars, password changes, account reset and deletion, and optional TOTP two-factor authentication with backup codes.
- **Live updates**: HTMX refreshes market prices, dashboard, portfolio, and leaderboard without page reloads.
- **Themes**: Light and dark themes, plus unlockable themes.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask 3.1 |
| Database | SQLite3 (built-in) |
| Templating | Jinja2 |
| Auth | Flask-Login, Werkzeug password hashing, PyOTP (2FA) |
| CSRF | Flask-WTF |
| Frontend | HTML5, CSS3 (custom properties), vanilla JavaScript, HTMX, Alpine.js |
| Charts | ApexCharts |
| Testing | Pytest, Hypothesis |
| Security scanning | Bandit, pip-audit |
| Deployment | Gunicorn, Nginx, Docker Compose |

## Project Structure

```
OreX/
├── requirements.txt         # Python dependencies
├── requirements-dev.txt     # Testing and security scanning dependencies
├── Dockerfile               # App image (Gunicorn, 1 worker)
├── docker-compose.yml       # Local Nginx -> Gunicorn -> SQLite stack
├── .env.example             # Environment variable template
├── docker/
│   └── nginx/               # Nginx image and config
├── src/
│   ├── run.py               # Development entry point
│   ├── schema.sql           # Database schema
│   ├── seed.sql             # Initial ore data
│   ├── app/
│   │   ├── __init__.py      # Flask app factory and security headers
│   │   ├── config.py        # Game and app configuration
│   │   ├── database.py      # SQLite connection and initialisation
│   │   ├── models.py        # Data access functions
│   │   ├── advanced.py      # Advanced Mode eligibility, purchase, and toggle
│   │   ├── advancements.py  # Achievement logic
│   │   ├── bonus.py         # Daily login bonus
│   │   ├── finances.py      # Finances page calculations
│   │   ├── totp.py          # Two-factor authentication
│   │   ├── routes/          # Flask blueprints (auth, market, trade, portfolio, etc.)
│   │   ├── market/          # Market engine (algorithm, bots, events, influence, levels, shorting)
│   │   ├── tutorial/        # Tutorial tracks and state
│   │   └── utils/           # Validation and formatting helpers
│   ├── templates/
│   │   ├── base.html        # Base template
│   │   ├── pages/           # Full page templates
│   │   └── partials/        # HTMX fragments and shared components
│   ├── static/              # CSS, JS, images, audio, tutorial data
│   └── data/                # SQLite database (auto-created)
├── migrations/              # Database migrations
├── scripts/                 # Developer utilities (screenshots, user cleanup)
├── tests/                   # Pytest test suite
└── docs/                    # Planning documents and assets
```

## Running Locally

### Prerequisites

- Python 3.10 or later
- pip

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Zechariah-Guo/OreX.git
   cd OreX
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS / Linux
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the application:
   ```bash
   cd src
   python run.py
   ```

5. Open your browser and navigate to `http://127.0.0.1:4000`

The SQLite database is created and seeded with the 9 ores on first run. To reset it, stop the server, delete `src/data/orex.db`, and start the server again.

### Running with Docker

The Docker Compose setup runs the production stack locally (Nginx, Gunicorn with one worker, and SQLite):

1. Copy `.env.example` to `.env` and set `SECRET_KEY`. Set `SESSION_COOKIE_SECURE=0` when testing over plain http.
2. Run `docker compose up --build`.
3. Open `http://localhost:8080`.

### Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Some 2FA property tests are slow because they hash many passwords. Skip them with `pytest -m "not slow"`, and skip the real-browser tests with `-m "not browser"`.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Landing page with a live ore ticker |
| `/register`, `/login` | Account creation and sign-in, with a 2FA challenge when enabled |
| `/dashboard` | Balance, top movers, and recent activity |
| `/market` | All ores and their current prices |
| `/market/<ore_id>` | Ore detail with price chart and buy/sell/short forms |
| `/portfolio` | Holdings, short positions, and profit/loss |
| `/finances` | Capital breakdown, short exposure, and cash flow |
| `/history` | Paginated transaction history |
| `/leaderboard` | Rankings of players and bot traders |
| `/profile` | Your profile, avatar, and daily bonus |
| `/player/<username>` | Public player profiles |
| `/inbox` | Notifications |
| `/settings` | Password, 2FA, Advanced Mode, account reset and deletion |
| `/help` | Help and tutorial list |
| `/about` | About the project |

## Configuration

Game settings live in `src/app/config.py`. Key values:

| Setting | Default | Description |
|---------|---------|-------------|
| `DEFAULT_BALANCE` | `10000` | Starting balance for new players |
| `TICK_INTERVAL` | `20` | Seconds between market price updates |
| `MAX_BUY_QUANTITY` | `500` | Holding cap per ore in standard mode |
| `ADVANCED_MODE_THRESHOLD` | `100000` | Net worth required to unlock Advanced Mode |
| `ADVANCED_MODE_COST` | `50000` | Price of Advanced Mode |
| `BONUS_AMOUNTS` | `1000 / 10000 / 50000` | Daily bonus for days 1, 2, and 3 |

Deployment settings are read from environment variables. See [`.env.example`](.env.example) for `SECRET_KEY`, `OREX_TRUST_PROXY`, `SESSION_COOKIE_SECURE`, and avatar storage options.

## Security

- **Password hashing**: Passwords and 2FA backup codes are hashed with Werkzeug.
- **Two-factor authentication**: Optional TOTP with QR code setup and backup codes.
- **CSRF protection**: All forms are protected with Flask-WTF.
- **Rate limiting**: The login endpoint limits repeated attempts.
- **Parameterised queries**: All database access uses bound parameters to prevent SQL injection.
- **Security headers**: `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, and `Permissions-Policy` are set on every response.
- **Session cookies**: `HttpOnly`, `SameSite=Lax`, and `Secure` in production.
- **Secret key enforcement**: The app refuses to start in production without a `SECRET_KEY`.

## Licence

This project is available under the MIT licence. See [LICENSE](LICENSE).
