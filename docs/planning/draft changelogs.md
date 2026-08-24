# OreX Changelogs (Draft)

> These notes will be displayed in the About section of the app once the changelog feature is built.

---

## Alpha - "The Foundation"

*The foundation of OreX — core trading experience.*

- **Live ore market** — 9 unique ores with real-time price movements every 20 seconds
- **Portfolio management** — Buy and sell ores, track your holdings, and monitor profit/loss
- **Dynamic price charts** — View price history across multiple timeframes (5m to 5 days)
- **Competitive leaderboard** — Compete with other players and bot traders for the top spot
- **Bot traders** — 9 simulated traders creating realistic market activity
- **Market events** — Rare price surges and crashes that shake up the market
- **Transaction history** — Full trade log with pagination and archiving
- **Account management** — Register, login, reset, or delete your account
- **Responsive design** — Play on desktop or mobile with light and dark themes

---

## Beta 1 — "The Advanced Update"

*Advanced trading mechanics, risk management, and account security.*

### Advanced Mode
- **Advanced Mode** — Unlock a prestige tier with expanded trading mechanics at high net worth
- **Short selling** — Bet against ores and profit when prices fall
- **Stop Loss & Take Profit** — Set automated price triggers to manage risk hands-free
- **Resistance & Support levels** — See key price boundaries on charts to inform your trades
- **Finances dashboard** — A dedicated breakdown of where your capital is allocated
- **Leaderboard indicators** — Advanced players stand out with a red name

### Security
- **Two-Factor Authentication** — Optional TOTP-based login security via Google Authenticator

### Quality of Life
- **Buy limits in standard mode** — Encourages strategic trading over bulk purchases

---

## Beta 2 — "The Progression Update"

*Player identity, progression, and notifications.*

### Progression & Rewards
- **9 Achievements** — Earn badges for milestones like reaching $1M, completing 100 trades, hitting #1 on the leaderboard, and more
- **Exclusive themes** — Unlock the Money theme and Gold theme through prestigious achievements
- **3-Day Welcome Bonus** — Collect rewards across your first 3 logins to jumpstart your portfolio

### Player Identity
- **Profile page** — Your personal hub with stats, achievements, and avatar
- **Custom profile pictures** — Upload and crop a personalized avatar

### Notifications
- **Notification system** — Bell icon, toast notifications, notification tray with history

---

## Version 1.0 (Release)

*Full production deployment with guided onboarding and polish.*

> Beta features plus changes to accommodate a full production deployment

### Onboarding & Guidance
- **Interactive tutorials** — Guided walkthroughs for new players and advanced mechanics
- **Help section** — Reorganized for easier access from the profile menu
- **In-app changelogs** — Major version notes displayed in the About section

### Quality of Life
- TBC (additional QoL changes bundled with the release)

## Version 1.1 

*QoL update including mobile support*

### Mobile Support
- TBC

### QoL
- Allow "forgot password" functionality by leveraging the existing 2fa system
- Optimise leaderboard and other pages' SQL with CTE
- Implement celery and redis for background profile picture processing and storage
- Migrate all images to avif with webp fallback
- Migrate sqlite3 to postgres (for practice --> say its for "scalability") (and potententially switch from rawSQL to SQLAlchemy) (on further considerations, probably not useful at all)
<blockquote> 
How to Prepare for Migration

1. Dump the Data: Export your SQLite database into an SQL text file using the .dump
command in your terminal.

2. Convert Syntax: SQLite and PostgreSQL have slight syntax differences (e.g., SQLite
uses AUTOINCREMENT , PostgreSQL uses SERIAL or GENERATED ALWAYS AS IDENTITY ).
Tools like pgloader can automate this conversion.

3. Update Code: Replace import sqlite3 with import psycopg2, update your
connection credentials, and swap ? placeholders to %s 
<blockquote/>