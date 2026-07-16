# Implementation Plan: Advanced Mode

## Overview

Implement the Advanced Mode prestige layer for OreX. This involves schema migration (4 new columns on `users`, new `stop_loss_take_profit` table), config additions, core helper module, decorator, context processor, route extensions (settings, trade, market), tick engine SL/TP evaluation, resistance/support calculator, leaderboard indicator, template conditionals, and the OreX Advanced theme. All advanced UI elements are feature-gated behind the `is_advanced_active` context variable.

## Tasks

- [ ] 1. Database schema and configuration
  - [ ] 1.1 Create migration file `migrations/add_advanced_mode.sql`
    - Add `advanced_eligible`, `advanced_purchased`, `advanced_active` INTEGER columns (default 0) to `users`
    - Add `advanced_toggled_at` TEXT column (default NULL) to `users`
    - Create `stop_loss_take_profit` table with columns: id, holding_id (FK), stop_loss, take_profit, active, created_at, triggered_at
    - Create indexes: `idx_sltp_holding` on holding_id, `idx_sltp_active` on active
    - _Requirements: 6.1, 6.2, 4.5, 3.4_

  - [ ] 1.2 Add Advanced Mode constants to `src/app/config.py`
    - Add `ADVANCED_MODE_THRESHOLD = 100_000`
    - Add `ADVANCED_MODE_COST = 50_000`
    - Add `ADVANCED_TOGGLE_COOLDOWN = 300`
    - Add `RS_LOOKBACK_WINDOW = 50`
    - _Requirements: 1.1, 3.1, 4.3, 7.6_

  - [ ] 1.3 Apply migration to the database
    - Update `src/schema.sql` to include the new columns and table for fresh installs
    - Create and run the migration script against the existing `src/data/orex.db`
    - _Requirements: 6.1, 3.4_

- [ ] 2. Core helpers and decorator
  - [ ] 2.1 Create `src/app/advanced.py` with core utility functions
    - Implement `check_eligibility(user_id)`: compute net worth (balance + Σ(qty × price)), return True if ≥ threshold; also set `advanced_eligible=1` in DB if newly eligible
    - Implement `purchase_advanced_mode(user_id)`: validate eligibility + balance ≥ $50,000, deduct cost, set `advanced_purchased=1`; return (success, message)
    - Implement `toggle_advanced_mode(user_id)`: check purchased, enforce 5-min cooldown from `advanced_toggled_at`, flip `advanced_active`, update `advanced_toggled_at`; return (success, message)
    - Implement `is_advanced_active(user_id)`: return True if `advanced_purchased=1 AND advanced_active=1`
    - Implement `get_advanced_status(user_id)`: return dict with {eligible, purchased, active, cooldown_remaining}
    - _Requirements: 1.1, 1.2, 1.3, 3.1, 3.2, 3.3, 3.4, 4.2, 4.3, 4.5_

  - [ ] 2.2 Create `src/app/decorators.py` with `advanced_required` decorator
    - Abort 401 if not authenticated
    - Abort 403 if `is_advanced_active` returns False for current user
    - Use `functools.wraps` to preserve function metadata
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ] 2.3 Register the context processor in `src/app/__init__.py`
    - Add `inject_advanced_mode` context processor that injects `is_advanced_active`, `has_advanced_purchased`, and `advanced_eligible` into all templates
    - Import from `app.advanced` only when user is authenticated
    - _Requirements: 5.1, 5.4, 8.1, 8.2_

  - [ ] 2.4 Write property tests for eligibility, purchase, and toggle logic
    - **Property 1: Net Worth Calculation Identity** — net worth = balance + Σ(qty × price)
    - **Property 2: Eligibility Monotonicity** — once eligible flag is set, check returns True regardless of net worth
    - **Property 3: Purchase Balance Deduction** — successful purchase deducts exactly $50,000
    - **Property 4: Purchase Precondition Rejection** — purchase rejected when ineligible or insufficient funds, balance unchanged
    - **Property 5: Toggle State Inversion** — toggle flips active from 0→1 or 1→0
    - **Property 6: Cooldown Enforcement** — toggle rejected if elapsed < 300s, accepted if ≥ 300s
    - **Validates: Requirements 1.1, 1.2, 1.3, 3.1, 3.2, 3.3, 4.2, 4.3**

- [ ] 3. Settings route: purchase and toggle endpoints
  - [ ] 3.1 Add `POST /settings/advanced/purchase` endpoint to `src/app/routes/settings.py`
    - Call `purchase_advanced_mode(current_user.id)`
    - Flash success or error message based on result
    - Redirect back to settings page
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ] 3.2 Add `POST /settings/advanced/toggle` endpoint to `src/app/routes/settings.py`
    - Call `toggle_advanced_mode(current_user.id)`
    - Flash success or error message (including cooldown remaining if rejected)
    - Redirect back to settings page
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 3.3 Update `src/templates/pages/settings.html` with Advanced Mode activation box
    - Add dedicated element in the "Themes" section
    - Show disabled/greyed state with $100,000 requirement message when ineligible
    - Show purchase button with $50,000 cost when eligible but not purchased
    - Show toggle switch with confirmation popup when purchased
    - Show cooldown timer (disabled toggle + remaining time) when cooldown active
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 4.1, 4.4_

  - [ ] 3.4 Write unit tests for settings purchase and toggle routes
    - Test purchase success, insufficient funds rejection, ineligibility rejection, double-purchase no-op
    - Test toggle success, cooldown rejection, confirmation flow
    - _Requirements: 3.1, 3.2, 3.3, 4.2, 4.3_

- [ ] 4. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Trade route: stop loss and take profit
  - [ ] 5.1 Extend buy order in `src/app/routes/trade.py` to accept optional `stop_loss` and `take_profit` parameters
    - Only process SL/TP params when `is_advanced_active` for current user
    - Validate: `stop_loss < current_price` and `take_profit > current_price`
    - On successful buy, insert row into `stop_loss_take_profit` table linking to the new holding
    - Return validation errors for invalid SL/TP values
    - _Requirements: 6.1, 6.2, 6.5, 6.6_

  - [ ] 5.2 Add `POST /trade/sltp/<int:holding_id>` endpoint for modifying/removing SL/TP on existing holdings
    - Gate with `@advanced_required` decorator
    - Verify holding belongs to current user (403 otherwise)
    - Validate new SL/TP values against current ore price
    - Allow setting to NULL to remove SL or TP
    - _Requirements: 6.7_

  - [ ] 5.3 Implement buy cap removal in `_get_buy_cap()` within `src/app/routes/trade.py`
    - Return `None` when advanced mode is active for current user, removing the `MAX_BUY_QUANTITY` limit
    - Retain existing cap for standard mode users
    - _Requirements: 5.4 (expanded trading controls)_

  - [ ] 5.4 Write property tests for SL/TP validation
    - **Property 8: Stop Loss / Take Profit Validation** — reject SL ≥ current price and TP ≤ current price
    - **Validates: Requirements 6.5, 6.6**

  - [ ] 5.5 Write unit tests for trade route SL/TP integration
    - Test buy order with valid SL/TP creates record
    - Test buy order with invalid SL/TP returns validation error
    - Test SL/TP modification on existing holding
    - Test unauthorized modification attempt returns 403
    - _Requirements: 6.1, 6.2, 6.5, 6.6, 6.7_

- [ ] 6. Tick engine: SL/TP evaluation
  - [ ] 6.1 Add `evaluate_stop_loss_take_profit(db)` function to `src/app/market/engine.py`
    - Query all active SL/TP orders joined with holdings and current ore prices
    - For each order: if `current_price <= stop_loss` or `current_price >= take_profit`, execute auto-sell
    - Auto-sell: update user balance, delete holding (or reduce quantity), mark order as triggered with timestamp
    - Wrap each order evaluation in try/except for resilience — log errors, continue processing other orders
    - Call `db.commit()` after all evaluations
    - _Requirements: 6.3, 6.4_

  - [ ] 6.2 Integrate `evaluate_stop_loss_take_profit` into the tick engine cycle
    - Call after `process_tick(db)` completes in the main engine loop
    - _Requirements: 6.3, 6.4_

  - [ ] 6.3 Write property test for SL/TP trigger execution
    - **Property 7: Stop Loss / Take Profit Trigger Execution** — when price ≤ SL or price ≥ TP, order is marked triggered and holding is sold
    - **Validates: Requirements 6.3, 6.4**

- [ ] 7. Market route: resistance and support levels
  - [ ] 7.1 Create `src/app/market/levels.py` with `calculate_levels(ore_id, lookback)` function
    - Query `price_history` for the most recent `lookback` entries for the ore
    - Return `{resistance: max(prices), support: min(prices)}` or `{resistance: None, support: None}` if no history
    - Use `Config.RS_LOOKBACK_WINDOW` as default lookback value
    - _Requirements: 7.3, 7.4, 7.5, 7.6_

  - [ ] 7.2 Add `GET /market/ore/<int:ore_id>/levels` endpoint to `src/app/routes/market.py`
    - Gate with `@advanced_required` decorator
    - Return JSON response with resistance and support values
    - _Requirements: 7.1, 7.2_

  - [ ] 7.3 Write property test for resistance/support calculation
    - **Property 9: Resistance and Support from Rolling Window** — resistance = max(last N prices), support = min(last N prices)
    - **Validates: Requirements 7.4, 7.5, 7.6**

- [ ] 8. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Leaderboard indicator
  - [ ] 9.1 Extend leaderboard query in `src/app/models.py` (or `src/app/routes/leaderboard.py`)
    - Join `users.advanced_active` column into leaderboard results
    - _Requirements: 9.1, 9.2_

  - [ ] 9.2 Update `src/templates/pages/leaderboard.html` to render red usernames
    - Apply red color class to usernames where `advanced_active = 1`
    - Standard color for purchased-but-inactive users
    - Visible to all players regardless of their own mode status
    - _Requirements: 9.1, 9.2, 9.3_

- [ ] 10. UI templates and theme
  - [ ] 10.1 Update `src/templates/base.html` for Advanced Mode theme support
    - Add `advanced-theme` CSS class to `<body>` when `is_advanced_active` is True
    - Swap standard OreX logo for OreX Advanced logo when active
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ] 10.2 Update trade templates to conditionally show SL/TP form fields
    - Add stop_loss and take_profit input fields to buy order form, wrapped in `{% if is_advanced_active %}`
    - Add SL/TP management controls on portfolio/holding views for existing positions
    - _Requirements: 5.1, 5.4, 6.1, 6.2_

  - [ ] 10.3 Update `src/templates/pages/ore_detail.html` with resistance/support overlays
    - Add dotted R/S lines to ore price chart (ApexCharts annotations) when advanced is active
    - Add info box alongside existing ore statistics showing R/S values
    - Fetch levels from `/market/ore/<id>/levels` endpoint via JavaScript
    - Hide all R/S indicators when not in advanced mode
    - _Requirements: 7.1, 7.2, 7.7, 7.8_

  - [ ] 10.4 Add Advanced Mode CSS styles to `src/static/css/`
    - Define `.advanced-theme` body styles for the expanded layout
    - Style the SL/TP form controls, R/S dotted lines, and info box
    - Style the settings page activation box states (disabled, enabled, toggle)
    - Style the confirmation popup for toggle action
    - _Requirements: 8.1, 8.2, 8.3, 5.4_

- [ ] 11. Account reset integration
  - [ ] 11.1 Extend account reset logic to clear all Advanced Mode state
    - Set `advanced_eligible=0`, `advanced_purchased=0`, `advanced_active=0`, `advanced_toggled_at=NULL` on the user record
    - Delete all `stop_loss_take_profit` rows associated with the user's holdings (cascades via FK, but explicitly clear if needed)
    - _Requirements: 10.1, 10.2, 10.3_

  - [ ] 11.2 Write property test for account reset
    - **Property 10: Account Reset Clears All Advanced State** — after reset, all flags are 0 and no active SL/TP orders remain
    - **Validates: Requirements 10.1, 10.2**

- [ ] 12. Integration tests and final checkpoint
  - [ ] 12.1 Write integration tests for the full Advanced Mode lifecycle
    - Full purchase flow: create user → accumulate wealth → become eligible → purchase → verify deduction
    - Tick engine SL/TP execution: set up holding with SL → run process_tick → verify auto-sell
    - Account reset: purchase advanced → reset → verify all state cleared
    - Cooldown enforcement: toggle → immediate re-toggle rejected → wait → toggle succeeds
    - _Requirements: 1.1, 3.1, 6.3, 6.4, 10.1, 10.2, 4.3_

  - [ ] 12.2 Final checkpoint
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (10 properties total across tasks 2.4, 5.4, 6.3, 7.3, 11.2)
- Unit tests validate specific examples and edge cases
- The buy cap removal (task 5.3) may already be partially implemented — verify existing `_get_buy_cap()` before writing
- All template changes depend on the context processor (task 2.3) being in place
- The `advanced_required` decorator follows the same pattern as the existing `@login_required`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["2.1", "2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4"] },
    { "id": 4, "tasks": ["3.1", "3.2", "7.1"] },
    { "id": 5, "tasks": ["3.3", "3.4", "5.1", "7.2"] },
    { "id": 6, "tasks": ["5.2", "5.3", "5.4", "7.3"] },
    { "id": 7, "tasks": ["5.5", "6.1"] },
    { "id": 8, "tasks": ["6.2", "6.3"] },
    { "id": 9, "tasks": ["9.1", "10.1"] },
    { "id": 10, "tasks": ["9.2", "10.2", "10.3", "10.4"] },
    { "id": 11, "tasks": ["11.1"] },
    { "id": 12, "tasks": ["11.2", "12.1"] }
  ]
}
```
