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
- **Responsive design** — Play on desktop with light and dark themes

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
- **Holding limits in standard mode** — Caps total units held per ore to encourage strategic trading and progression to advanced mode (unlocks limits)

---

## Beta 2 — "The Identity Update"

*Player identity, progression, and notifications.*

### Progression & Rewards
- **9 Achievements** — Earn badges for milestones like reaching $1M, completing 100 trades, hitting #1 on the leaderboard, and more
- **Exclusive themes** — Unlock the Money theme and Gold theme through prestigious achievements
- **3-Day Welcome Bonus** — Collect rewards across your first 3 logins to jumpstart your portfolio

### Player Identity
- **Profile page** — Your personal hub with stats, achievements, and avatar
- **Custom profile pictures** — Upload and crop a personalized avatar

### Notifications
- **Notification system** — Inbox system, interactive toast notifications

### Other
- **Relocate Help page** — Move to profile dropdown for easier and more obvious access, add tutorial place holder (coming soon)

---

## Version 1.0 (Release)

*Full production deployment with guided onboarding, mobile support and polish.*

> Beta features plus changes to accommodate a full production deployment

### Onboarding & Guidance
- **Interactive tutorials** — Step-by-step spotlight walkthroughs for beginners and for Advanced Mode
- **Replay from Help** — Restart any tutorial you have access to, or resume one you left midway
- **New landing page** — A live ore ticker and screenshots for visitors who haven't signed in

### Profiles & Community
- **Public player profiles** — Click any player on the leaderboard to see their stats and advancements
- **Bonus countdown** — See exactly when your next welcome bonus unlocks

### Finances & Trading
- **Capital Breakdown** — See cash, holdings, and short collateral at a glance, with short exposure and cash flow
- **Portfolio summary** — A summary header and tabs for holdings and shorts
- **Fairer margin calls** — A short's collateral factor is fixed when it opens, so topping up your vault no longer shifts it

### Quality of Life
- **Smarter notifications** — Inbox messages now link to the page they refer to
- **Smoother updates** — Live pages refresh without flicker
- **Chart fixes** — Switching time ranges is reliable and axis labels are no longer cut off

### Mobile Support
- Change UI for mobile sized screens
- Turn into PWA (add option in settings to download)
- Maybe get push notifications working on the PWA (bit more complex)

### QoL
- Allow "forgot password" functionality: optional one-time recovery key system
- Modfiy the whole system to use a pyproject.toml instead of scattered config files (e.g. requirements.txt, .pytest.ini etc) (use python uv library)
- UI improvements
- Bug fixes and Performance improvements

## Version 1.1

*Big gamemode update introducing additional "fun" ways to experience the game. (Also likely the last big update)*

### Challenge Modes (maybe)
- Race to the Bottom: Time how long it takes to go from 100k to < 100$
- Go for Broke: Start with 10k and advanced mode. make money, spend it on slots (a screen of stone + random ores appear) + maybe other modes
- Versus mode: 10 mins, 1 sec ticks, either blank or some set starting .db, who has the most money at the end wins. leaderboard for wins (+2), draws (+1 both), losses (0) which kinda forces you to play more if you want to be #1
- All 3 will introduce a new state or badge on the profile page: Profit for gamble mode (can be negative), Best time for race to the bottom, rank for versus
- Must unlock advanced then buy each game mode for a price (maybe 50k for versus, 100k for race to bottom, 150k for gamble)
- Might all need their own tutorial? just 1 or 2 steps for new stuff. 