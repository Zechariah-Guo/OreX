# Implementation Plan: Achievements System

## Overview

Implement the Achievements System progression layer for OreX. This involves schema migration (new `achievements` table, new columns on `users`), config additions, core achievement engine module, play time tracker, login streak logic, tick engine integration, trade/auth/settings route integrations, theme context processor, achievements display page, notification support, and template updates. All nine achievements are evaluated at specific trigger points and awarded permanently via `INSERT OR IGNORE` idempotency.

## Tasks

- [ ] 1. Database schema and configuration
  - [ ] 1.1 Create migration file `migrations/add_achievements.sql`
    - Create `achievements` table with columns: id (PRIMARY KEY), user_id (INTEGER NOT NULL), achievement_key (TEXT NOT NULL), earned_at (TEXT NOT NULL DEFAULT datetime)
    - Add UNIQUE constraint on (user_id, achievement_key)
    - Add FOREIGN KEY on user_id referencing users(id) with ON DELETE CASCADE
    - Create index `idx_achievements_user` on achievements(user_id)
    - Add `play_time` INTEGER NOT NULL DEFAULT 0 column to `users`
    - Add `login_streak` INTEGER NOT NULL DEFAULT 0 column to `users`
    - Add `last_streak_date` TEXT DEFAULT NULL column to `users`
    - Add `money_theme_unlocked` INTEGER NOT NULL DEFAULT 0 column to `users`
    - Add `gold_theme_unlocked` INTEGER NOT NULL DEFAULT 0 column to `users`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 3.1, 13.4_

  - [ ] 1.2 Add achievement constants to `src/app/config.py`
    - Add `ACHIEVEMENT_MILLIONAIRE_THRESHOLD = 1_000_000`
    - Add `ACHIEVEMENT_MULTIMILLIONAIRE_THRESHOLD = 10_000_000`
    - Add `ACHIEVEMENT_DAY_TRADER_TRADES = 100`
    - Add `ACHIEVEMENT_BUDDING_ENTHUSIAST_MINUTES = 20`
    - Add `ACHIEVEMENT_DEDICATED_STREAK = 3`
    - Add `ACHIEVEMENT_TRAGEDY_THRESHOLD = 10_000`
    - Add `PLAYTIME_HEARTBEAT_INTERVAL = 60`
    - Add `PLAYTIME_MAX_INCREMENT = 5`
    - _Requirements: 4.1, 5.1, 7.1, 8.1, 9.1, 11.1_

  - [ ] 1.3 Apply migration to the database
    - Update `src/schema.sql` to include the new table and columns for fresh installs
    - Create and run the migration script against the existing `src/data/orex.db`
    - _Requirements: 1.1, 1.4_

- [ ] 2. Implement core achievement engine module
  - [ ] 2.1 Create `src/app/achievements.py` with constants and metadata
    - Define `ACHIEVEMENT_KEYS` list with all 9 achievement key strings
    - Define `ACHIEVEMENT_METADATA` dictionary with name, description, and threshold for each achievement
    - _Requirements: 1.3_

  - [ ] 2.2 Implement `award_achievement()` and `has_achievement()` in `src/app/achievements.py`
    - Implement `award_achievement(db, user_id, key)` using `INSERT OR IGNORE` for idempotency; return True if newly awarded, False if already owned
    - On new award: handle theme unlock (multimillionaire → money_theme_unlocked=1, completionist → gold_theme_unlocked=1)
    - On new award: emit notification via `create_notification()`
    - On new award: call `evaluate_completionist(db, user_id)`
    - Implement `has_achievement(db, user_id, key)` to check if player already has a specific achievement
    - _Requirements: 1.2, 5.4, 10.2, 10.3, 13.1, 13.2, 15.1, 15.2_

  - [ ] 2.3 Implement `get_user_achievements()` and `get_achievement_progress()` in `src/app/achievements.py`
    - Implement `get_user_achievements(db, user_id)` returning all earned achievements with earned_at timestamps
    - Implement `get_achievement_progress(db, user_id)` returning progress dict: trade_count, play_time, login_streak, net_worth
    - _Requirements: 14.1, 14.4_

  - [ ] 2.4 Implement net-worth achievement evaluation in `src/app/achievements.py`
    - Implement `evaluate_tick_achievements(db)` that evaluates millionaire, multimillionaire, and best_of_the_rest for all players who don't already have them
    - Use batch net worth query (balance + holdings value + short position equity)
    - Award millionaire when net_worth >= $1,000,000; award multimillionaire when net_worth >= $10,000,000
    - Award best_of_the_rest to all players tied at rank 1 (highest net worth)
    - Short-circuit players who already have all three achievements
    - _Requirements: 4.1, 4.2, 5.1, 5.2, 12.1, 12.2, 12.4_

  - [ ] 2.5 Implement remaining evaluation functions in `src/app/achievements.py`
    - Implement `evaluate_trade_achievement(db, user_id)`: count all transactions (buy, sell, short_open, short_close, short_liquidated) including archived; award day_trader if >= 100
    - Implement `evaluate_login_achievements(db, user_id)`: award dedicated if login_streak >= 3
    - Implement `evaluate_playtime_achievement(db, user_id)`: award budding_enthusiast if play_time >= 20
    - Implement `evaluate_short_achievement(db, user_id)`: award the_big_short (called only when profit > 0 and close_type is voluntary/take_profit and advanced mode active)
    - Implement `evaluate_tragedy(db, user_id, net_worth)`: award tragedy if net_worth < $10,000
    - Implement `evaluate_completionist(db, user_id)`: count earned achievements excluding completionist; award if count == 8
    - _Requirements: 6.1, 6.2, 6.3, 7.1, 7.2, 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 10.1, 10.2, 11.1, 11.2, 11.3_

  - [ ]* 2.6 Write property tests for achievement award idempotency
    - **Property 1: Achievement Award Idempotency** — Calling `award_achievement(db, user_id, key)` multiple times results in exactly one row in the achievements table for that (user_id, key) pair
    - **Validates: Requirements 1.2, 4.3, 5.3, 6.4, 7.3, 9.3, 10.4, 11.4, 12.3**

  - [ ]* 2.7 Write property tests for net worth threshold achievements
    - **Property 3: Net Worth Threshold Achievement Awards** — millionaire awarded iff net_worth >= 1,000,000; multimillionaire awarded iff net_worth >= 10,000,000
    - **Validates: Requirements 4.1, 5.1**

  - [ ]* 2.8 Write property tests for The Big Short preconditions
    - **Property 4: The Big Short Preconditions** — the_big_short awarded iff profit > 0 AND advanced_mode_active AND close_type in {voluntary, take_profit}
    - **Validates: Requirements 6.1, 6.2, 6.3**

  - [ ]* 2.9 Write property tests for trade count and completionist
    - **Property 5: Day Trader Trade Count** — day_trader awarded iff total transactions (all types, including archived) >= 100
    - **Property 10: Completionist Requires All Eight** — completionist awarded iff player has earned all 8 other achievements
    - **Validates: Requirements 8.1, 8.2, 8.3, 10.1**

  - [ ]* 2.10 Write property tests for threshold achievements (playtime, streak, tragedy)
    - **Property 6: Budding Enthusiast Threshold** — budding_enthusiast awarded iff play_time >= 20
    - **Property 7: Dedicated Streak Threshold** — dedicated awarded iff login_streak >= 3
    - **Property 8: Tragedy Threshold** — tragedy awarded iff net_worth < 10,000
    - **Validates: Requirements 7.1, 9.1, 11.1, 11.3**

  - [ ]* 2.11 Write property tests for best of the rest rank and theme unlocks
    - **Property 9: Best of the Rest Rank Determination** — best_of_the_rest awarded to all players with net_worth equal to maximum in set
    - **Property 11: Theme Unlock on Achievement Award** — money_theme_unlocked set to 1 only on multimillionaire; gold_theme_unlocked set to 1 only on completionist
    - **Validates: Requirements 5.4, 10.3, 12.1, 12.4, 13.1, 13.2**

- [ ] 3. Implement play time tracker
  - [ ] 3.1 Create `src/app/playtime.py` with heartbeat logic
    - Implement `record_heartbeat(user_id)`: check `session['last_heartbeat']`; if >= 60s elapsed, compute `min(floor(elapsed/60), 5)` minutes; increment play_time in DB; update session timestamp
    - Implement `flush_playtime(db, user_id, minutes)`: atomically increment play_time column
    - Implement `reset_playtime(db, user_id)`: set play_time to 0
    - After incrementing play_time, call `evaluate_playtime_achievement(db, user_id)` when play_time crosses 20 min
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 9.2_

  - [ ]* 3.2 Write property test for heartbeat increment calculation
    - **Property 15: Play Time Heartbeat Increment Calculation** — increment equals min(floor(elapsed_seconds / 60), 5); if elapsed < 60, increment is 0
    - **Validates: Requirements 2.2, 2.4**

- [ ] 4. Implement login streak logic
  - [ ] 4.1 Add `update_login_streak(db, user_id)` function to `src/app/achievements.py`
    - Compare today's date with last_streak_date: same day → no change; yesterday → increment streak by 1; older/NULL → reset streak to 1
    - Update last_streak_date accordingly
    - After update, call `evaluate_login_achievements(db, user_id)`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 7.2_

  - [ ]* 4.2 Write property test for login streak state machine
    - **Property 2: Login Streak State Machine** — streak unchanged if same day; streak = S+1 if T == D+1; streak = 1 if T > D+1 or D is NULL
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5**

- [ ] 5. Checkpoint - Core modules verified
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Integrate achievement evaluation into trigger points
  - [ ] 6.1 Integrate tick engine achievements in `src/app/market/engine.py`
    - After `process_tick(db)` completes (and after `process_short_positions(db)` if active), call `evaluate_tick_achievements(db)`
    - Wrap in try/except so achievement evaluation failures don't block price updates
    - _Requirements: 4.2, 5.2, 12.2_

  - [ ] 6.2 Integrate trade achievements in `src/app/routes/trade.py`
    - After successful buy/sell transaction commit, call `evaluate_trade_achievement(db, current_user.id)`
    - _Requirements: 8.4_

  - [ ] 6.3 Integrate short achievement in shorting route
    - After a profitable short close (profit > 0 and close_type is voluntary or take_profit), call `evaluate_short_achievement(db, current_user.id)`
    - Verify player has Advanced_Mode active before calling
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ] 6.4 Integrate login streak and achievements in `src/app/routes/auth.py`
    - After successful login (after `update_last_login`), call `update_login_streak(db, user_id)`
    - _Requirements: 3.2, 7.2_

  - [ ] 6.5 Integrate play time heartbeat into authenticated requests
    - Register a `before_request` hook (or equivalent) that calls `record_heartbeat(current_user.id)` for authenticated users
    - Throttle to once per 60 seconds via session timestamp check
    - _Requirements: 2.2, 9.2_

  - [ ] 6.6 Integrate tragedy evaluation in `src/app/routes/settings.py`
    - Before `reset_account()` executes, calculate net_worth and call `evaluate_tragedy(db, user_id, net_worth)`
    - Inside reset logic, set play_time=0, login_streak=0, last_streak_date=NULL but do NOT touch achievements or theme columns
    - _Requirements: 11.1, 11.2, 11.3, 16.1, 16.2, 16.3, 16.4_

- [ ] 7. Implement theme context processor and achievements display
  - [ ] 7.1 Register theme context processor in `src/app/__init__.py`
    - Add `inject_achievement_themes` context processor that injects `money_theme_unlocked` and `gold_theme_unlocked` into all templates
    - Only query DB when user is authenticated
    - _Requirements: 13.3, 13.4, 13.6_

  - [ ] 7.2 Create achievements display route and template
    - Add `GET /achievements` route (login required) rendering all 9 achievements with earned/locked state and progress bars
    - Create `src/templates/pages/achievements.html` showing achievement cards: locked state with condition visible, unlocked state with earned_at date
    - Display progress indicators for: trade_count/100, play_time/20, login_streak/3, net_worth/$1M and $10M
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [ ] 7.3 Implement achievement notification delivery
    - When `award_achievement()` awards a new achievement, call `create_notification(user_id, 'achievement', message, '/achievements')`
    - Use yellow styling for achievement toasts; include theme mention for multimillionaire and completionist
    - Notifications delivered via htmx partial updates without full page reload
    - Notifications persist longer than standard and are clickable (navigate to achievements page)
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

- [ ] 8. Checkpoint - Integration verified
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Template and theme updates
  - [ ] 9.1 Update `src/templates/base.html` to support Money and Gold themes
    - Add conditional CSS class to `<body>` based on `money_theme_unlocked`/`gold_theme_unlocked` and user's selected theme
    - _Requirements: 13.5, 13.6_

  - [ ] 9.2 Update theme settings to include Money and Gold options
    - In settings template, add Money theme option (only visible when `money_theme_unlocked` is True)
    - Add Gold theme option (only visible when `gold_theme_unlocked` is True)
    - _Requirements: 13.3_

  - [ ] 9.3 Add achievement theme CSS styles to `src/static/css/`
    - Define `.money-theme` styles with green/cash aesthetic color palette
    - Define `.gold-theme` styles with gold/prestige aesthetic color palette
    - Ensure cosmetic-only changes that don't alter UI layout or trading mechanics
    - _Requirements: 13.5, 13.6_

- [ ] 10. Account lifecycle integration
  - [ ] 10.1 Verify account reset preserves achievements and themes
    - Confirm `reset_account()` does NOT delete rows from achievements table
    - Confirm `reset_account()` does NOT reset money_theme_unlocked or gold_theme_unlocked
    - Confirm play_time and login_streak are reset to 0
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [ ] 10.2 Verify account delete cascades achievement removal
    - Confirm `ON DELETE CASCADE` on achievements foreign key properly removes all achievement rows when user is deleted
    - _Requirements: 1.4, 16.5_

  - [ ]* 10.3 Write property tests for account reset and delete
    - **Property 12: Account Reset Preserves Achievements and Themes** — after reset, all achievement rows remain and theme unlocks retain pre-reset values
    - **Property 13: Account Reset Clears Progress Counters** — after reset, play_time=0, login_streak=0, last_streak_date=NULL
    - **Property 14: CASCADE Delete Removes All Achievements** — after user delete, zero achievement records exist for that user_id
    - **Validates: Requirements 1.4, 16.1, 16.2, 16.3, 16.4, 16.5**

  - [ ]* 10.4 Write property test for display state correctness
    - **Property 16: Achievement Display State Correctness** — display returns "earned" with non-null earned_at for keys in earned set, "locked" for keys not in set, total always 9 entries
    - **Validates: Requirements 14.1, 14.4**

- [ ] 11. Integration tests and final checkpoint
  - [ ]* 11.1 Write integration tests for achievement lifecycle
    - Full award lifecycle: create user → trigger condition → verify achievement row + notification
    - Tick engine evaluation: set user at $1M net worth → run process_tick → verify millionaire awarded
    - Completionist cascade: award 8 achievements sequentially → verify completionist auto-awarded on 8th
    - Account reset preservation: earn achievements → reset → verify achievements intact, play_time/streak zeroed
    - Account delete cleanup: earn achievements → delete → verify zero rows in achievements table
    - _Requirements: 4.1, 5.1, 10.1, 16.1, 16.5_

  - [ ]* 11.2 Write integration tests for play time and login streak
    - Play time accumulation: simulate heartbeats → verify play_time increments → verify budding_enthusiast at 20 min
    - Login streak transitions: simulate multi-day logins → verify streak increment → verify dedicated at 3 days
    - _Requirements: 2.2, 3.2, 7.1, 9.1_

  - [ ]* 11.3 Write integration tests for edge cases
    - Tragedy before reset: set user below $10K → trigger reset → verify tragedy awarded before data cleared
    - Best of the rest tie: create multiple users at same max net worth → run tick → verify all get achievement
    - The Big Short with forced liquidation (profit > 0) → verify NOT awarded
    - The Big Short with voluntary close (profit > 0) → verify awarded
    - _Requirements: 6.1, 6.3, 11.1, 12.4_

  - [ ] 11.4 Final checkpoint
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (16 properties total)
- Unit tests validate specific examples and edge cases
- The project uses Hypothesis for property-based testing (already configured in `.hypothesis/`)
- Achievement awards use `INSERT OR IGNORE` semantics — safe to call repeatedly without duplication
- Net worth calculation reuses `get_net_worth()` from the shorting-system spec
- The existing notification system (`create_notification()`) is leveraged for achievement toasts
- Theme unlocks are write-once (set to 1, never reverted to 0) except on account delete
- Login streak uses server-local date to prevent client manipulation

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
