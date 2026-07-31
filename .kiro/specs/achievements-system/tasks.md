# Implementation Plan: Advancements System

## Overview

Implement the Advancements System progression layer for OreX. This involves schema migration (new `advancements` table, new columns on `users`), config additions, core advancement engine module, play time tracker, login streak logic, tick engine integration, trade/auth/settings route integrations, theme context processor, advancements display page, notification support, and template updates. All nine advancements are evaluated at specific trigger points and awarded permanently via `INSERT OR IGNORE` idempotency.

## Tasks

- [x] 1. Database schema and configuration
  - [x] 1.1 Create migration file `migrations/add_advancements.sql`
    - Create `advancements` table with columns: id (PRIMARY KEY), user_id (INTEGER NOT NULL), advancement_key (TEXT NOT NULL), earned_at (TEXT NOT NULL DEFAULT datetime)
    - Add UNIQUE constraint on (user_id, advancement_key)
    - Add FOREIGN KEY on user_id referencing users(id) with ON DELETE CASCADE
    - Create index `idx_advancements_user` on advancements(user_id)
    - Add `play_time` INTEGER NOT NULL DEFAULT 0 column to `users`
    - Add `login_streak` INTEGER NOT NULL DEFAULT 0 column to `users`
    - Add `last_streak_date` TEXT DEFAULT NULL column to `users`
    - Add `money_theme_unlocked` INTEGER NOT NULL DEFAULT 0 column to `users`
    - Add `gold_theme_unlocked` INTEGER NOT NULL DEFAULT 0 column to `users`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 3.1, 13.4_

  - [x] 1.2 Add advancement constants to `src/app/config.py`
    - Add `ADVANCEMENT_MILLIONAIRE_THRESHOLD = 1_000_000`
    - Add `ADVANCEMENT_MULTIMILLIONAIRE_THRESHOLD = 10_000_000`
    - Add `ADVANCEMENT_WHAT_A_DEAL_TRADES = 100`
    - Add `ADVANCEMENT_SUIT_UP_MINUTES = 20`
    - Add `ADVANCEMENT_DEDICATED_STREAK = 3`
    - Add `ADVANCEMENT_POST_MORTEM_THRESHOLD = 10_000`
    - Add `PLAYTIME_HEARTBEAT_INTERVAL = 60`
    - Add `PLAYTIME_MAX_INCREMENT = 5`
    - _Requirements: 4.1, 5.1, 7.1, 8.1, 9.1, 11.1_

  - [x] 1.3 Apply migration to the database
    - Update `src/schema.sql` to include the new table and columns for fresh installs
    - Create and run the migration script against the existing `src/data/orex.db`
    - _Requirements: 1.1, 1.4_

- [x] 2. Implement core advancement engine module
  - [x] 2.1 Create `src/app/advancements.py` with constants and metadata
    - Define `ADVANCEMENT_KEYS` list with all 9 advancement key strings
    - Define `ADVANCEMENT_METADATA` dictionary with name, description, and threshold for each advancement
    - Advancement names: "Millionaire", "Multimillionaire", "The Big Short", "Dedicated", "What a Deal!", "Suit Up", "Completionist", "Post-mortem", "Go for Diamond!"
    - _Requirements: 1.3_

  - [x] 2.2 Implement `award_advancement()` and `has_advancement()` in `src/app/advancements.py`
    - Implement `award_advancement(db, user_id, key)` using `INSERT OR IGNORE` for idempotency; return True if newly awarded, False if already owned
    - On new award: handle theme unlock (multimillionaire → money_theme_unlocked=1, completionist → gold_theme_unlocked=1)
    - On new award: emit notification via `create_notification()`
    - On new award: call `evaluate_completionist(db, user_id)`
    - Implement `has_advancement(db, user_id, key)` to check if player already has a specific advancement
    - _Requirements: 1.2, 5.4, 10.2, 10.3, 13.1, 13.2, 15.1, 15.2_

  - [x] 2.3 Implement `get_user_advancements()` and `get_advancement_progress()` in `src/app/advancements.py`
    - Implement `get_user_advancements(db, user_id)` returning all earned advancements with earned_at timestamps
    - Implement `get_advancement_progress(db, user_id)` returning progress dict: trade_count, play_time, login_streak, net_worth
    - _Requirements: 14.1, 14.4_

  - [x] 2.4 Implement net-worth advancement evaluation in `src/app/advancements.py`
    - Implement `evaluate_tick_advancements(db)` that evaluates millionaire, multimillionaire, and go_for_diamond for all players who don't already have them
    - Use batch net worth query (balance + holdings value + short position equity)
    - Award millionaire when net_worth >= $1,000,000; award multimillionaire when net_worth >= $10,000,000
    - Award go_for_diamond to all players tied at rank 1 (highest net worth)
    - Short-circuit players who already have all three advancements
    - _Requirements: 4.1, 4.2, 5.1, 5.2, 12.1, 12.2, 12.4_

  - [x] 2.5 Implement remaining evaluation functions in `src/app/advancements.py`
    - Implement `evaluate_trade_advancement(db, user_id)`: count all transactions (buy, sell, short_open, short_close, short_liquidated) including archived; award what_a_deal if >= 100
    - Implement `evaluate_login_advancements(db, user_id)`: award dedicated if login_streak >= 3
    - Implement `evaluate_playtime_advancement(db, user_id)`: award suit_up if play_time >= 20
    - Implement `evaluate_short_advancement(db, user_id)`: award the_big_short (called only when profit > 0 and close_type is voluntary/take_profit and advanced mode active)
    - Implement `evaluate_post_mortem(db, user_id, net_worth)`: award post_mortem if net_worth < $10,000
    - Implement `evaluate_completionist(db, user_id)`: count earned advancements excluding completionist; award if count == 8
    - _Requirements: 6.1, 6.2, 6.3, 7.1, 7.2, 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 10.1, 10.2, 11.1, 11.2, 11.3_

  - [x] 2.6 Write property tests for advancement award idempotency
    - **Property 1: Advancement Award Idempotency** — Calling `award_advancement(db, user_id, key)` multiple times results in exactly one row in the advancements table for that (user_id, key) pair
    - **Validates: Requirements 1.2, 4.3, 5.3, 6.4, 7.3, 9.3, 10.4, 11.4, 12.3**

  - [x] 2.7 Write property tests for net worth threshold advancements
    - **Property 3: Net Worth Threshold Advancement Awards** — millionaire awarded if net_worth >= 1,000,000; multimillionaire awarded if net_worth >= 10,000,000
    - **Validates: Requirements 4.1, 5.1**

  - [x] 2.8 Write property tests for The Big Short preconditions
    - **Property 4: The Big Short Preconditions** — the_big_short awarded if profit > 0 AND advanced_mode_active AND close_type in {voluntary, take_profit}
    - **Validates: Requirements 6.1, 6.2, 6.3**

  - [x] 2.9 Write property tests for trade count and completionist
    - **Property 5: What a Deal! Trade Count** — what_a_deal awarded if total transactions (all types, including archived) >= 100
    - **Property 10: Completionist Requires All Eight** — completionist awarded if player has earned all 8 other advancements
    - **Validates: Requirements 8.1, 8.2, 8.3, 10.1**

  - [x] 2.10 Write property tests for threshold advancements (playtime, streak, post-mortem)
    - **Property 6: Suit Up Threshold** — suit_up awarded if play_time >= 20
    - **Property 7: Dedicated Streak Threshold** — dedicated awarded if login_streak >= 3
    - **Property 8: Post-mortem Threshold** — post_mortem awarded if net_worth < 10,000
    - **Validates: Requirements 7.1, 9.1, 11.1, 11.3**

  - [x] 2.11 Write property tests for Go for Diamond! rank and theme unlocks
    - **Property 9: Go for Diamond! Rank Determination** — go_for_diamond awarded to all players with net_worth equal to maximum in set
    - **Property 11: Theme Unlock on Advancement Award** — money_theme_unlocked set to 1 only on multimillionaire; gold_theme_unlocked set to 1 only on completionist
    - **Validates: Requirements 5.4, 10.3, 12.1, 12.4, 13.1, 13.2**

- [x] 3. Implement play time tracker
  - [x] 3.1 Create `src/app/playtime.py` with heartbeat logic
    - Implement `record_heartbeat(user_id)`: check `session['last_heartbeat']`; if >= 60s elapsed, compute `min(floor(elapsed/60), 5)` minutes; increment play_time in DB; update session timestamp
    - Implement `flush_playtime(db, user_id, minutes)`: atomically increment play_time column
    - Implement `reset_playtime(db, user_id)`: set play_time to 0
    - After incrementing play_time, call `evaluate_playtime_advancement(db, user_id)` when play_time crosses 20 min
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 9.2_

  - [x] 3.2 Write property test for heartbeat increment calculation
    - **Property 15: Play Time Heartbeat Increment Calculation** — increment equals min(floor(elapsed_seconds / 60), 5); if elapsed < 60, increment is 0
    - **Validates: Requirements 2.2, 2.4**

- [x] 4. Implement login streak logic
  - [x] 4.1 Add `update_login_streak(db, user_id)` function to `src/app/advancements.py`
    - Compare today's date with last_streak_date: same day → no change; yesterday → increment streak by 1; older/NULL → reset streak to 1
    - Update last_streak_date accordingly
    - After update, call `evaluate_login_advancements(db, user_id)`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 7.2_

  - [x] 4.2 Write property test for login streak state machine
    - **Property 2: Login Streak State Machine** — streak unchanged if same day; streak = S+1 if T == D+1; streak = 1 if T > D+1 or D is NULL
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5**

- [x] 5. Checkpoint - Core modules verified
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Integrate advancement evaluation into trigger points
  - [x] 6.1 Integrate tick engine advancements in `src/app/market/engine.py`
    - After `process_tick(db)` completes (and after `process_short_positions(db)` if active), call `evaluate_tick_advancements(db)`
    - Wrap in try/except so advancement evaluation failures don't block price updates
    - _Requirements: 4.2, 5.2, 12.2_

  - [x] 6.2 Integrate trade advancements in `src/app/routes/trade.py`
    - After successful buy/sell transaction commit, call `evaluate_trade_advancement(db, current_user.id)`
    - _Requirements: 8.4_

  - [x] 6.3 Integrate short advancement in shorting route
    - After a profitable short close (profit > 0 and close_type is voluntary or take_profit), call `evaluate_short_advancement(db, current_user.id)`
    - Verify player has Advanced_Mode active before calling
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 6.4 Integrate login streak and advancements in `src/app/routes/auth.py`
    - After successful login (after `update_last_login`), call `update_login_streak(db, user_id)`
    - _Requirements: 3.2, 7.2_

  - [x] 6.5 Integrate play time heartbeat into authenticated requests
    - Register a `before_request` hook (or equivalent) that calls `record_heartbeat(current_user.id)` for authenticated users
    - Throttle to once per 60 seconds via session timestamp check
    - _Requirements: 2.2, 9.2_

  - [x] 6.6 Integrate post-mortem evaluation in `src/app/routes/settings.py`
    - Before `reset_account()` executes, calculate net_worth and call `evaluate_post_mortem(db, user_id, net_worth)`
    - Inside reset logic, set play_time=0, login_streak=0, last_streak_date=NULL but do NOT touch advancements or theme columns
    - _Requirements: 11.1, 11.2, 11.3, 16.1, 16.2, 16.3, 16.4_

- [x] 7. Implement theme context processor and advancements testing page
  - [x] 7.1 Register theme context processor in `src/app/__init__.py`
    - Add `inject_advancement_themes` context processor that injects `money_theme_unlocked` and `gold_theme_unlocked` into all templates
    - Only query DB when user is authenticated
    - _Requirements: 13.3, 13.4, 13.6_

  - [x] 7.2 Create advancements testing page (developer tool)
    - Add `GET /advancements` route (login required) — a hidden, no-frills testing page with NO navigation links anywhere in the app (only accessible by manually typing the URL)
    - Create `src/templates/pages/advancements_test.html` with:
      - List of all 9 advancements with their keys and display names
      - For each advancement: a true/false indicator showing whether the current player has earned it
      - A "Reset" button per advancement that strips that entry from the player's advancements data (DELETE from advancements table for that user+key)
      - A "Reset All" button that strips all advancements for the current player
      - A "Trigger Money Theme" button that sets money_theme_unlocked=1 for the current player (for visual testing)
      - A "Trigger Gold Theme" button that sets gold_theme_unlocked=1 for the current player (for visual testing)
      - A "Reset Themes" button that sets both theme flags back to 0
    - This page is purely for development/testing before the profile-stage advancements display is built
    - _Requirements: N/A (developer testing utility)_

  - [x] 7.3 Implement advancement notification delivery
    - When `award_advancement()` awards a new advancement, call `create_notification(user_id, 'advancement', message, '/advancements')`
    - Use yellow styling for advancement toasts; include theme mention for multimillionaire and completionist
    - Notifications delivered via htmx partial updates without full page reload
    - Notifications persist longer than standard and are clickable (navigate to advancements page)
    - **Note:** This is a placeholder implementation. The full notification system (polling, tray, bell, etc.) is defined in the `notification-system` spec and will refactor/replace parts of what was built here. See that spec's "Existing Placeholder" section for details.
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

- [x] 8. Checkpoint - Integration verified
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Template and theme updates
  - [x] 9.1 Update `src/templates/base.html` to support Money and Gold themes
    - Add conditional CSS class to `<body>` based on `money_theme_unlocked`/`gold_theme_unlocked` and user's selected theme
    - _Requirements: 13.5, 13.6_

  - [x] 9.2 Update theme settings to include Money and Gold options
    - In settings template, add Money theme option (only visible when `money_theme_unlocked` is True)
    - Add Gold theme option (only visible when `gold_theme_unlocked` is True)
    - _Requirements: 13.3_

  - [x] 9.3 Add advancement theme CSS and JS to `src/static/css/` and templates
    - Define `.money-theme` styles: slightly darker green color palette, custom cursor (`money-cursor.png`), falling Emerald background effect (reuse landing page `falling-container` pattern but with only `Emerald.webp` image)
    - Define `.gold-theme` styles: slightly darker yellow/gold color palette, custom cursor (`gold-cursor.png`), falling Gold Ingot background effect (reuse landing page `falling-container` pattern but with only `Gold_Ingot.webp` image)
    - Falling ore background JS should be conditionally loaded when the theme is active (similar to landing page script but single-ore variant)
    - Ensure cosmetic-only changes that don't alter UI layout or trading mechanics
    - Page exclusions for the falling background TBD — implement on all pages initially, refine later
    - _Requirements: 13.5, 13.6_

  - [x] 9.4 Implement default avatar background colours
    - For `default-avatar.png` (players) and `bot-icon.png` (bots): render the transparent icon on top of a coloured circle/square background derived from a random ore's primary colour
    - Bots: assign deterministically based on bot name or ID (consistent colour every time)
    - Players: assign randomly at account creation, store as a column on `users` (e.g., `avatar_color TEXT DEFAULT NULL`) so it persists until they upload a custom profile picture
    - Use the 9 ore primary colours as the palette: Coal (dark grey), Iron (beige), Copper (orange-brown), Gold (yellow), Lapis (blue), Redstone (red), Emerald (green), Diamond (cyan), Netherite (dark brown)
    - Render via CSS (background-color on a wrapper element) rather than baking into the image, so it's easy to change
    - Once a player uploads a custom avatar (profile stage, Beta 2), the colour background is no longer shown
    - _Requirements: N/A (visual polish, leaderboard diferentiation)_

- [x] 10. Account lifecycle integration
  - [x] 10.1 Verify account reset preserves advancements and themes
    - Confirm `reset_account()` does NOT delete rows from advancements table
    - Confirm `reset_account()` does NOT reset money_theme_unlocked or gold_theme_unlocked
    - Confirm play_time and login_streak are reset to 0
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [x] 10.2 Verify account delete cascades advancement removal
    - Confirm `ON DELETE CASCADE` on advancements foreign key properly removes all advancement rows when user is deleted
    - _Requirements: 1.4, 16.5_

  - [x] 10.3 Write property tests for account reset and delete
    - **Property 12: Account Reset Preserves Advancements and Themes** — after reset, all advancement rows remain and theme unlocks retain pre-reset values
    - **Property 13: Account Reset Clears Progress Counters** — after reset, play_time=0, login_streak=0, last_streak_date=NULL
    - **Property 14: CASCADE Delete Removes All Advancements** — after user delete, zero advancement records exist for that user_id
    - **Validates: Requirements 1.4, 16.1, 16.2, 16.3, 16.4, 16.5**

  - [x] 10.4 Write property test for display state correctness
    - **Property 16: Advancement Display State Correctness** — display returns "earned" with non-null earned_at for keys in earned set, "locked" for keys not in set, total always 9 entries
    - **Validates: Requirements 14.1, 14.4**

- [x] 11. Integration tests and final checkpoint
  - [x] 11.1 Write integration tests for advancement lifecycle
    - Full award lifecycle: create user → trigger condition → verify advancement row + notification
    - Tick engine evaluation: set user at $1M net worth → run process_tick → verify millionaire awarded
    - Completionist cascade: award 8 advancements sequentially → verify completionist auto-awarded on 8th
    - Account reset preservation: earn advancements → reset → verify advancements intact, play_time/streak zeroed
    - Account delete cleanup: earn advancements → delete → verify zero rows in advancements table
    - _Requirements: 4.1, 5.1, 10.1, 16.1, 16.5_

  - [x] 11.2 Write integration tests for play time and login streak
    - Play time accumulation: simulate heartbeats → verify play_time increments → verify suit_up at 20 min
    - Login streak transitions: simulate multi-day logins → verify streak increment → verify dedicated at 3 days
    - _Requirements: 2.2, 3.2, 7.1, 9.1_

  - [x] 11.3 Write integration tests for edge cases
    - Post-mortem before reset: set user below $10K → trigger reset → verify post_mortem awarded before data cleared
    - Go for Diamond! tie: create multiple users at same max net worth → run tick → verify all get advancement
    - The Big Short with forced liquidation (profit > 0) → verify NOT awarded
    - The Big Short with voluntary close (profit > 0) → verify awarded
    - _Requirements: 6.1, 6.3, 11.1, 12.4_

  - [x] 11.4 Final checkpoint
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (16 properties total)
- Unit tests validate specific examples and edge cases
- The project uses Hypothesis for property-based testing (already configured in `.hypothesis/`)
- Advancement awards use `INSERT OR IGNORE` semantics — safe to call repeatedly without duplication
- Net worth calculation reuses `get_net_worth()` from the shorting-system spec
- The existing notification system (`create_notification()`) is leveraged for advancement toasts
- Theme unlocks are write-once (set to 1, never reverted to 0) except on account delete
- Login streak uses server-local date to prevent client manipulation
- The `/advancements` testing page is a temporary developer tool — it will be superseded by the profile-stage advancements display later

## Assets and Manual Work Required

Before starting implementation, the following assets and manual setup are needed:

1. **Advancement icon/badge images** — 9 icons (one per advancement). Minecraft-style pixel art or stylized badges. Format: `.webp` or `.png`, stored at `src/static/images/advancements/`. Filenames: `millionaire.webp`, `multimillionaire.webp`, `the_big_short.webp`, `dedicated.webp`, `what_a_deal.webp`, `suit_up.webp`, `completionist.webp`, `post_mortem.webp`, `go_for_diamond.webp`
2. **Money theme design** — Slightly darker green color palette. Background uses the same falling-ore effect as the landing page (`falling-container` with JS animation) but restricted to only Emerald images. Custom cursor via `src/static/images/Money_cursor.png` (already exists). Decide which pages should NOT have the falling background (e.g., charts, modals — work out exclusions later).
3. **Gold theme design** — Slightly darker yellow/gold color palette. Background uses the same falling-ore effect as the landing page but restricted to only Gold Ingot images. Custom cursor via `src/static/images/Gold_Cursor.png` (already exists). Same page exclusion decisions as Money theme.
4. **Toast notification sound (optional)** — If you want an audio cue when an advancement is earned, provide an `.mp3` or `.ogg` file at `src/static/audio/advancement.mp3`.
5. **Database backup** — Back up `src/data/orex.db` before running the migration in case of issues.
6. **Test accounts** — Ensure you have at least 2-3 test accounts available for leaderboard rank testing (Go for Diamond! tie scenarios).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2", "2.3"] },
    { "id": 4, "tasks": ["2.4", "2.5"] },
    { "id": 5, "tasks": ["2.6", "2.7", "2.8", "2.9", "2.10", "2.11", "3.1", "4.1"] },
    { "id": 6, "tasks": ["3.2", "4.2"] },
    { "id": 7, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.5", "6.6"] },
    { "id": 8, "tasks": ["7.1", "7.2", "7.3"] },
    { "id": 9, "tasks": ["9.1", "9.2", "9.3"] },
    { "id": 10, "tasks": ["10.1", "10.2"] },
    { "id": 11, "tasks": ["10.3", "10.4", "11.1", "11.2", "11.3"] }
  ]
}
```
