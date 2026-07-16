# OreX Future Features Roadmap

## Legend
- ✅ Requirements spec'd
- 🔲 Not yet started
- 🚧 Partially explored

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
| 🔲 | Finances Page (Advanced) | Breakdown of free cash, locked collateral, short equity — accessible via green money pill or portfolio |
| 🔲 | Resistance & Support Metrics | Chart overlays, lookback window calculation |
| 🔲 | Bot Shorting AI | Bots react to advanced players, risk-managed short entries |

---

## Phase 3: Social & Identity

| Status | Feature | Notes |
|--------|---------|-------|
| ✅ | Custom PFP | Cropper.js, Oracle-compatible storage, leaderboard integration |
| ✅ | Leaderboard Indicators | Red name (advanced), bot icons |
| ✅ | Money & Gold Themes | Multimillionaire → Money theme, Completionist → Gold theme |
| ✅ | 2FA (Google Authenticator) | TOTP setup, backup codes, login challenge, rate limited — **IMPLEMENTED** |

---

## Phase 4: Engagement & Retention

| Status | Feature | Notes |
|--------|---------|-------|
| ✅ | 3-Day Welcome Bonus | One-time $1k/$10k/$100k, no streak required |
| ✅ | Login Streak Tracking | For Dedicated badge |
| ✅ | Play Time Tracking | For Budding Enthusiast badge |
| 🔲 | Tutorial System | Beginner + Advanced tutorials, notification system |
| 🔲 | Changelogs | Major version notes, in-app display |

---

## Phase 5: Technical & Deployment

| Status | Feature | Notes |
|--------|---------|-------|
| 🔲 | Oracle Cloud Deployment | Free tier, object storage for PFPs, see deployment/ folder |
| 🔲 | Alpine.js / Morphdom | Better animations with htmx, React-like transitions |
| 🔲 | Help/FAQ Relocation | Move FAQ into profile dropdown help section |

---

## Specs Completed (Requirements Phase)
1. `.kiro/specs/advanced-mode/` — 10 requirements
2. `.kiro/specs/shorting-system/` — 14 requirements
3. `.kiro/specs/achievements-system/` — 16 requirements
4. `.kiro/specs/profile-page/` — 10 requirements
5. `.kiro/specs/finances-page/` — 9 requirements
6. `.kiro/specs/tutorial-system/` — 12 requirements
7. `.kiro/specs/two-factor-auth/` — 10 requirements

## Fully Implemented
- Hard cap on buy quantity in standard mode (500 max) — config.py + trade route + template
- Two-Factor Authentication — TOTP + backup codes, login challenge, setup/disable flows, 122 tests passing

---

## Manual Tasks / Prerequisites (Before or During Implementation)

Things you need to do manually that Kiro can't handle:

### Dependencies to Install
- [x] `pip install pyotp==2.9.0` — TOTP generation/verification for 2FA
- [x] `pip install qrcode==8.0` — QR code generation for 2FA setup (uses Pillow which is already installed)
- [x] Update `requirements.txt` with pyotp and qrcode after install
- [ ] Alpine.js will be loaded from CDN (no pip install needed, already allowed in CSP)

### Assets to Create/Source
- [ ] **OreX Advanced logo** — SVG or PNG for the Advanced Mode theme (replaces standard logo when active)
- [ ] **Default avatar image** — `static/images/default-avatar.png` (generic user silhouette, used when no PFP uploaded)
- [ ] **Bot icon** — `static/images/bot-icon.png` (displayed on leaderboard for bot accounts instead of PFP)
- [ ] **Achievement badge icons** — 9 badge images (one per achievement), both locked (greyed) and unlocked versions
- [ ] **Money theme CSS** — Gold/cash-inspired color palette for Multimillionaire unlock
- [ ] **Gold theme CSS** — Gold/prestige color palette for Completionist unlock
- [ ] **Notification bell icon** — SVG icon for the nav bar notification bell
- [ ] **Tutorial step content** — Write the actual text for each tutorial step (beginner 7 steps, advanced 7 steps) in `static/data/tutorials.json`

### Oracle Cloud Setup (When Ready for Deployment)
- [ ] Create Oracle Cloud Free Tier account
- [ ] Set up Object Storage bucket (`orex-avatars`)
- [ ] Configure OCI SDK credentials (`~/.oci/config`)
- [ ] Set environment variables: `STORAGE_BACKEND=oci`, `OCI_NAMESPACE`, `OCI_BUCKET`

### Design Decisions Still Needed
- [ ] Exact colors/gradients for Money theme and Gold theme
- [ ] Achievement badge visual style (pixel art? flat icons? illustrated?)
- [ ] Advanced Mode logo design direction
- [ ] Tutorial step targeting (need to add `id` attributes to key DOM elements for tutorial selectors)

---

## Implementation Order (Dependency-Based)

1. ~~**2FA** — Isolated (auth + settings only)~~ ✅ Done
2. **Advanced Mode** — Foundation for feature gating ← NEXT
3. **Shorting System** — Depends on advanced mode
4. **Finances Page** — Depends on advanced mode + shorting
5. **Achievements** — Depends on advanced mode + shorting
6. **Profile Page** — Depends on achievements
7. **Notification System** — Depends on achievements + shorting (emitters)
8. **Tutorial System** — Depends on everything being in place
9. **Changelog** — Vibe at the end
