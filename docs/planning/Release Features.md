# OreX Release Roadmap (Beta 1 - v1.0)

## Legend
- ✅ Completed
- 🔲 Not started (Spec completed)
- 🚧 In progress

---

## Phase 1: Core Progression System

| Status | Feature | Notes |
|--------|---------|-------|
| ✅ | Advanced Mode | Unlock at 100k NW, purchase for 50k, feature flags, theme/logo swap |
| ✅ | Achievements (9 badges) | Millionaire, Multimillionaire, The Big Short, Dedicated, Day Trader, Budding Enthusiast, Completionist, Tragedy, Best of the Rest |
| ✅ | Profile Page | PFP, stats, daily bonus, achievement display, help relocation |
| ✅ | Hard cap on stocks (simple mode) | Max 500 per buy order in standard mode, implemented |

---

## Phase 2: Advanced Trading Mechanics

| Status | Feature | Notes |
|--------|---------|-------|
| ✅ | Shorting System | Full collateral/fee engine, forced liquidation, SL/TP for shorts |
| ✅ | Stop Loss / Take Profit | Covered in both advanced-mode and shorting-system specs |
| ✅ | Finances Page (Advanced) | Breakdown of free cash, locked collateral, short equity — accessible via green money pill or portfolio |
| ✅ | Resistance & Support Metrics | Chart overlays, lookback window calculation |
| ✅ | Bot Shorting AI | Bots react to advanced players, risk-managed short entries |

---

## Phase 3: Social & Identity

| Status | Feature | Notes |
|--------|---------|-------|
| ✅ | Custom PFP | WebP conversion, Oracle-compatible storage, leaderboard integration |
| ✅ | Leaderboard Indicators | Red name (advanced), bot icons |
| ✅ | Money & Gold Themes | Multimillionaire → Money theme, Completionist → Gold theme |
| ✅ | 2FA (Google Authenticator) | TOTP setup, backup codes, login challenge, rate limited |

---

## Phase 4: Engagement & Retention

| Status | Feature | Notes |
|--------|---------|-------|
| ✅ | 3-Day Welcome Bonus | One-time $1k/$10k/$100k, no streak required |
| ✅ | Login Streak Tracking | For Dedicated badge |
| ✅ | Play Time Tracking | For Budding Enthusiast badge |
| ✅ | Notification System | Bell icon, tray, toast delivery, replaces placeholder |
| ✅ | Changelogs | Major version notes, in-app display (moved to v1.0) |

---

## Phase 5: Technical & Deployment

| Status | Feature | Notes |
|--------|---------|-------|
| 🔲 | Oracle Cloud Deployment | Free tier, object storage for PFPs, see deployment/ folder |
| ✅ | Alpine.js / Morphdom | Better animations with htmx, React-like transitions |
| ✅ | Help/FAQ Relocation | Move FAQ into profile dropdown help section |
| ✅ | Tutorial System | Beginner + Advanced tutorials (moved to v1.0). Engine, Help page replay and tests are done; still needs final step wording in `tutorials.json` and `id` attributes on the target elements |

---

## Manual Tasks / Prerequisites (Before or During Implementation)

### Dependencies to Install
- [x] `pip install pyotp==2.9.0` — TOTP generation/verification for 2FA
- [x] `pip install qrcode==8.0` — QR code generation for 2FA setup (uses Pillow which is already installed)
- [x] Update `requirements.txt` with pyotp and qrcode after install
- [x] Alpine.js will be loaded from CDN (no pip install needed, already allowed in CSP)

### Assets to Create/Source
- [x] **Default avatar image** — `static/images/default-avatar.png` (generic user silhouette, used when no PFP uploaded)
- [x] **Bot icon** — `static/images/bot-icon.png` (displayed on leaderboard for bot accounts instead of PFP)
- [x] **Achievement badge icons** — 9 badge images (one per achievement), both locked (greyed) and unlocked versions
- [x] **Money theme CSS** — Gold/cash-inspired color palette for Multimillionaire unlock
- [x] **Gold theme CSS** — Gold/prestige color palette for Completionist unlock
- [x] **Notification bell icon** — SVG icon for the nav bar notification bell
- [x] **Tutorial step content** — Write the actual text for each tutorial step (beginner 7 steps, advanced 7 steps) in `static/data/tutorials.json`

### Oracle Cloud Setup (When Ready for Deployment)
- [ ] Create Oracle Cloud Free Tier account
- [ ] Set up Object Storage bucket (`orex-avatars`)
- [ ] Configure OCI SDK credentials (`~/.oci/config`)
- [ ] Set environment variables: `STORAGE_BACKEND=oci`, `OCI_NAMESPACE`, `OCI_BUCKET`
- [ ] **Remove or lock down the `/testing` dev page before going live.** It only requires a login, so any player who types the URL can grant themselves every advancement/theme and reset their daily bonus. The new free cash buttons (drain / +$100k) already 404 outside debug mode; the rest of the page doesn't. Either delete it (`routes/testing.py` dev routes + `templates/pages/testing.html`) or gate the whole blueprint behind `app.debug`.

### Design Decisions Still Needed
- [x] Exact colors/gradients for Money theme and Gold theme
- [x] Achievement badge visual style (pixel art? flat icons? illustrated?)
- [x] Advanced Mode logo design direction
- [x] Tutorial step targeting (need to add `id` attributes to key DOM elements for tutorial selectors)

---

## Implementation Order (Dependency-Based)

1. ~~**2FA** — Isolated (auth + settings only)~~ ✅ Done
2. ~~**Advanced Mode** — Foundation for feature gating~~ ✅ Done
3. ~~**Shorting System** — Depends on advanced mode~~ ✅ Done
4. ~~**Finances Page** — Depends on advanced mode + shorting~~ ✅ Done
5. ~~**Resistance & Support** — Chart overlays~~ ✅ Done
6. ~~**Achievements** — Depends on advanced mode + shorting~~ ✅ Done
7. ~~**Notification System** — Depends on achievements + shorting (emitters)~~ ✅ Done
8. ~~**Profile Page** — Depends on achievements + notifications~~ ✅ Done
9. ~~**Tutorial System** — Moved to v1.0 (depends on everything being in place)~~ ✅ Done[']
10. ~~**Changelog** — Moved to v1.0, add to revamped about section~~ ✅ Done

---

## Now also including 1.1 features due to delayed deployment

### Mobile Support
- ~~Change UI for mobile sized screens~~ ✅ Done (Basically)
- ~~Turn into PWA (add option in settings to download)~~ ✅ Done
- Maybe get push notifications working on the PWA (bit more complex) (for toasts when the user isnt in the app, like sltp, daily bonus, maybe a login nudge if they want to maintain streak, liquidation, )

### QoL
- ~~Allow "forgot password" functionality with a  one time key system (built without email: optional one-time recovery key chosen at registration, a Forgot password page that takes username + key then a new password, a fresh key issued after each reset, and `scripts/reset_password.py` for admin resets.)~~ ✅ Done
- ~~Modfiy the whole system to use a pyproject.toml instead of scattered config files (e.g. requirements.txt, .pytest.ini etc) (use python uv library)~~ ✅ Done