# Implementation Plan: Shorting System

## Overview

Implement a "reverse long position with a fuse" shorting mechanic for Advanced Mode players. The implementation proceeds bottom-up: database schema → config constants → core shorting engine (collateral, fees, liquidation) → tick integration → trade routes → bot extension → dashboard/UI → net worth update → account reset handling. Each step builds incrementally so the system is testable at every stage.

## Tasks

- [x] 1. Database schema and configuration
  - [x] 1.1 Create `short_positions` table in `src/schema.sql` and write migration
    - Add `short_positions` table with columns: id (PK), user_id (FK NOT NULL), ore_id (FK NOT NULL), share_quantity (INTEGER NOT NULL CHECK 1–10000), entry_price (REAL NOT NULL CHECK > 0), locked_collateral (REAL NOT NULL CHECK > 0), stop_loss_price (REAL nullable), take_profit_price (REAL nullable), cumulative_fees_paid (REAL NOT NULL DEFAULT 0.0), opened_at (TEXT NOT NULL DEFAULT datetime('now')), closed_at (TEXT nullable), status (TEXT NOT NULL DEFAULT 'active' CHECK IN ('active','closed'))
    - Add FOREIGN KEY constraints with RESTRICT on delete for user_id and ore_id
    - Create indexes: `idx_short_positions_user` on user_id, `idx_short_positions_status` on status, `idx_short_positions_ore_status` on (ore_id, status)
    - Create a migration file `migrations/add_short_positions.sql` to apply changes to existing databases
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 1.2 Add shorting configuration constants to `src/app/config.py`
    - Add `SHORT_BASE_REQUIREMENT = 0.50`
    - Add `SHORT_MAX_PENALTY = 2.0`
    - Add `SHORT_STEEPNESS = 3`
    - Add `SHORT_BASE_HOURLY_RATE = 0.005`
    - Add `SHORT_MAX_HOURLY_FEE = 0.10`
    - Add `SHORT_MAX_QUANTITY = 10000`
    - Add `SHORT_MIN_QUANTITY = 1`
    - Add bot shorting config: `BOT_SHORT_TREND_THRESHOLD = 4`, `BOT_SHORT_SUSTAIN_TICKS = 30`, `BOT_SHORT_CAPITAL_CAP = 0.30`, `BOT_SHORT_SL_PERCENT = 0.05`
    - _Requirements: 2.1, 2.2, 2.7, 4.1, 8.1, 13.5, 13.6, 13.7_

  - [x] 1.3 Add new transaction types to the existing transaction system
    - Ensure the transactions table supports type values: `"short_open"`, `"short_close"`, `"short_liquidated"`
    - Document the `total_value` field semantics: locked collateral for opens, P/L amount for closes/liquidations
    - _Requirements: 2.6, 5.4, 6.5_

- [x] 2. Implement core shorting engine calculations (`src/app/market/shorting.py`)
  - [x] 2.1 Create `src/app/market/shorting.py` with collateral calculation functions
    - Implement `_calculate_short_ratio(db, ore_id)` → shorts / (shorts + longs), returning 0.0 when both are zero
    - Implement `_calculate_collateral_multiplier(short_ratio)` → 0.50 + 2.0 × short_ratio³, clamped to [0.50, 2.50]
    - Implement helper to compute Total_Locked_Collateral as (shares × price) × collateral_multiplier
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 2.2 Add tick fee calculation function to `src/app/market/shorting.py`
    - Implement `_calculate_tick_fee(short_value, volatility, ticks_per_hour)` → round(short_value × ((0.005 + 0.10 × volatility²) / ticks_per_hour), 2)
    - Derive `ticks_per_hour` from `Config.TICK_INTERVAL` (3600 / TICK_INTERVAL)
    - _Requirements: 4.1, 8.1, 8.2_

  - [x] 2.3 Add squeeze price estimation function to `src/app/market/shorting.py`
    - Implement `_calculate_squeeze_price(position, user_balance, volatility, ticks_per_hour)` to estimate the ore price at which FreeCash would be exhausted
    - _Requirements: 10.5, 11.3_

  - [x] 2.4 Add shared position close logic to `src/app/market/shorting.py`
    - Implement `_close_position(db, position, close_type, current_price)` handling: calculate P/L, update status to 'closed', set closed_at, record transaction, release collateral to FreeCash
    - Handle both profit (SV < locked) and loss (SV > locked) scenarios
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.6_

  - [x] 2.5 Write property test for collateral calculation pipeline
    - **Property 1: Collateral Calculation Pipeline**
    - Test that for any valid share quantity (1–10000), ore price (> 0), and position counts: Short_Ratio = shorts/(shorts+longs) or 0.0, Collateral_Multiplier = 0.50 + 2.0 × Short_Ratio³, Total_Locked_Collateral = (shares × price) × Collateral_Multiplier
    - **Validates: Requirements 2.1, 2.2, 2.3**

  - [x] 2.6 Write property test for tick fee calculation
    - **Property 7: Tick Fee Calculation**
    - Test that for any Short_Value (> 0), Volatility (0.0–1.5), and Ticks_Per_Hour (derived from TICK_INTERVAL > 0): Tick_Fee_Cost = round(Short_Value × ((0.005 + 0.10 × Volatility²) / Ticks_Per_Hour), 2)
    - **Validates: Requirements 4.1, 8.1**

  - [x] 2.7 Write property test for voluntary close settlement
    - **Property 9: Voluntary Close Settlement**
    - Test that for any active short position with Locked_Collateral L and Short_Value SV: after close, FreeCash increases by (L − SV), which may be negative when SV > L
    - **Validates: Requirements 5.2, 5.3**

- [x] 3. Implement tick-phase processing functions in `src/app/market/shorting.py`
  - [x] 3.1 Implement Phase 1: SL/TP evaluation (`_evaluate_sltp_triggers`)
    - Query active positions that have SL or TP set
    - For each position: if current_price >= stop_loss_price OR current_price <= take_profit_price, close via `_close_position` with close_type "sl_triggered" or "tp_triggered"
    - Return set of closed position IDs to skip in later phases
    - No time-bleed fee applied for triggered positions in that tick
    - _Requirements: 7.4, 7.5, 7.6, 7.7_

  - [x] 3.2 Implement Phase 2: Margin call rebalancing (`_rebalance_margin`)
    - For each active position (excluding closed_ids), recalculate Required_Collateral
    - If Required > Locked: transfer deficit from FreeCash (Margin_Call_Transfer)
    - If Required < Locked: release surplus to FreeCash
    - Process positions per user in descending Required_Collateral order
    - If deficit > FreeCash: transfer all remaining FreeCash, trigger forced liquidation
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 3.3 Implement Phase 3: Time-bleed fee deduction (`_apply_time_bleed_fees`)
    - For each active position (excluding closed_ids), calculate and deduct tick fee from FreeCash
    - Process per user in ascending opened_at order (oldest first)
    - Increment cumulative_fees_paid on the position
    - If deduction would reduce FreeCash below 0: deduct only amount to bring FreeCash to 0, trigger forced liquidation, skip remaining positions for that player
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 9.5_

  - [x] 3.4 Implement Phase 4: Forced liquidation check (`_check_forced_liquidation`)
    - For users with FreeCash == 0 and remaining active positions, liquidate one at a time (highest Short_Value first)
    - Buyback cost = shares × current_price; credit remaining = locked - buyback to FreeCash
    - Use `max(0, locked - buyback)` to prevent negative credit
    - Record transaction type "short_liquidated", create notification, mark position closed
    - Stop liquidating once FreeCash > 0
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [x] 3.5 Implement main entry point `process_short_positions(db)`
    - Fetch current ore prices into ores_map
    - Call phases in strict order: _evaluate_sltp_triggers → _rebalance_margin → _apply_time_bleed_fees → _check_forced_liquidation
    - Wrap each user's processing in try/except for resilience
    - _Requirements: 3.7, 4.4, 7.6_

  - [x] 3.6 Write property test for collateral rebalancing conservation of money
    - **Property 4: Collateral Rebalancing Conservation of Money**
    - Test that FreeCash + Locked_Collateral remains constant through rebalancing (money is neither created nor destroyed)
    - **Validates: Requirements 3.3, 3.4**

  - [x] 3.7 Write property test for margin call liquidation trigger
    - **Property 5: Margin Call Liquidation Trigger**
    - Test that when deficit > FreeCash, all remaining FreeCash is transferred and forced liquidation triggers
    - **Validates: Requirements 3.5**

  - [x] 3.8 Write property test for margin call processing order
    - **Property 6: Margin Call Processing Order**
    - Test that multiple positions are processed in descending Required_Collateral order
    - **Validates: Requirements 3.6**

  - [x] 3.9 Write property test for fee processing order and exhaustion
    - **Property 8: Fee Processing Order and Liquidation on Exhaustion**
    - Test that fees are deducted oldest-first and if FreeCash would go negative, only the amount to bring it to zero is deducted, triggering liquidation
    - **Validates: Requirements 4.2, 4.3**

  - [x] 3.10 Write property test for no negative FreeCash after forced liquidation
    - **Property 10: No Negative FreeCash After Forced Liquidation**
    - Test that after the complete tick processing cycle, FreeCash >= 0 for any combination of positions and prices
    - **Validates: Requirements 6.4**

  - [x] 3.11 Write property test for forced liquidation mechanics
    - **Property 11: Forced Liquidation Mechanics**
    - Test that buyback cost = SV, remainder = L − SV is credited to FreeCash, and remainder is non-negative (since margin calls ensure L >= SV)
    - **Validates: Requirements 6.2, 6.3**

  - [x] 3.12 Write property test for SL/TP trigger execution
    - **Property 13: SL/TP Trigger Execution**
    - Test that when price >= SL or price <= TP, the position is closed without applying Time_Bleed_Fee for that tick
    - **Validates: Requirements 7.4, 7.5**

  - [x] 3.13 Write property test for SL/TP priority over forced liquidation
    - **Property 14: SL/TP Priority Over Forced Liquidation**
    - Test that when both SL trigger and FreeCash exhaustion apply, the SL close executes and forced liquidation is suppressed
    - **Validates: Requirements 7.7**

- [x] 4. Checkpoint - Core engine verification
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Integrate shorting engine into tick loop and add trade routes
  - [x] 5.1 Integrate `process_short_positions` into `src/app/market/engine.py`
    - Import `process_short_positions` from `app.market.shorting`
    - Call `process_short_positions(db)` after `process_tick(db)` in the tick loop
    - Wrap in try/except to prevent shorting errors from blocking the main tick
    - _Requirements: 7.6, 8.1_

  - [x] 5.2 Add short order validation and open route to `src/app/routes/trade.py`
    - Add `POST /trade/short/open/<int:ore_id>` endpoint gated by `@advanced_required`
    - Validate share_quantity (integer, 1–10000), validate ore exists and has price > 0
    - Calculate collateral via shorting engine functions
    - Reject if FreeCash < Total_Locked_Collateral; otherwise deduct and create Short_Position
    - Register sell-type influence via `record_player_trade()`
    - Record "short_open" transaction
    - Accept optional stop_loss and take_profit values with validation (SL > current_price, TP < current_price)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 7.1, 7.2, 7.3, 13.1_

  - [x] 5.3 Add short preview route to `src/app/routes/trade.py`
    - Add `POST /trade/short/preview` endpoint gated by `@advanced_required`
    - Return htmx partial HTML with: Position Size, Total_Locked_Collateral, Crowding Surcharge %, estimated Tick Fee, estimated Squeeze Price
    - Disable submit button if collateral exceeds FreeCash
    - Handle edge case of quantity=0 (return zeroed preview)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [x] 5.4 Add voluntary close route to `src/app/routes/trade.py`
    - Add `POST /trade/short/close/<int:position_id>` endpoint gated by `@advanced_required`
    - Verify position belongs to current user (403 otherwise)
    - Verify position status is 'active' (400 otherwise)
    - Close via `_close_position` with close_type "voluntary"
    - Register buy-type influence via `record_player_trade()`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 13.2_

  - [x] 5.5 Add SL/TP edit route to `src/app/routes/trade.py`
    - Add `POST /trade/short/edit/<int:position_id>` endpoint gated by `@advanced_required`
    - Verify position ownership and active status
    - Validate new SL/TP values against current ore price
    - Allow setting to NULL to remove SL or TP
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 5.6 Write property test for order rejection when FreeCash insufficient
    - **Property 2: Order Rejection When FreeCash Insufficient**
    - Test that when FreeCash < Total_Locked_Collateral, the order is rejected and FreeCash remains unchanged
    - **Validates: Requirements 2.4**

  - [x] 5.7 Write property test for balance deduction on valid short open
    - **Property 3: Balance Deduction on Valid Short Open**
    - Test that after a valid open, new FreeCash = previous FreeCash - Total_Locked_Collateral
    - **Validates: Requirements 2.5**

  - [x] 5.8 Write property test for SL/TP validation
    - **Property 12: SL/TP Validation**
    - Test that SL <= current_price is rejected, TP >= current_price is rejected, valid requires SL > P and TP < P
    - **Validates: Requirements 7.2, 7.3**

  - [x] 5.9 Write property test for market influence registration
    - **Property 16: Short Position Market Influence Registration**
    - Test that opening registers sell-type with quantity Q, closing registers buy-type with quantity Q
    - **Validates: Requirements 13.1, 13.2**

- [x] 6. Checkpoint - Trade routes and tick integration
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement net worth update and bot shorting extension
  - [x] 7.1 Update net worth calculation in `src/app/models.py`
    - Modify `get_net_worth()` to include short position equity: FreeCash + Σ(qty × price) + Σ(Locked_Collateral − Short_Value)
    - Ensure the formula returns the same result as the legacy formula when no active shorts exist
    - Update `get_portfolio_value()` if needed to keep long-only semantics
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 7.2 Extend bot trading in `src/app/market/bots.py` with shorting logic
    - Implement `_bot_short_decision(db, bot_id, ore)`: check 4/5 trend_log entries are "fall" AND FreeCash can sustain >= 30 ticks of fees after lockup AND total short capital < 30% of balance
    - Implement `_bot_open_short(db, bot_id, ore_id, quantity, price)`: open short with mandatory SL at entry_price × 1.05
    - Implement `_bot_close_short(db, bot_id, position_id, price)`: close bot short position
    - Integrate calls into the existing bot trade execution flow (`execute_bot_trades`)
    - Register bot influence via bot influence queue
    - _Requirements: 13.4, 13.5, 13.6, 13.7_

  - [x] 7.3 Write property test for net worth formula with shorts
    - **Property 15: Net Worth Formula with Shorts**
    - Test that Net_Worth = FreeCash + Σ(q_i × p_i) + Σ(Lj − SVj) for any combination of holdings and short positions
    - **Validates: Requirements 12.1, 12.2**

  - [x] 7.4 Write property test for bot short decision constraints
    - **Property 17: Bot Short Decision Constraints**
    - Test that bots only short when 4/5 trend entries are "fall" AND FreeCash can sustain >= 30 ticks of fees
    - **Validates: Requirements 13.5**

  - [x] 7.5 Write property test for bot short safety invariants
    - **Property 18: Bot Short Safety Invariants**
    - Test that bot SL = entry_price × 1.05 and total short capital <= 30% of bot balance
    - **Validates: Requirements 13.6, 13.7**

- [x] 8. Implement dashboard and UI extensions
  - [x] 8.1 Add short position dashboard data to `src/app/routes/dashboard.py`
    - Implement `_get_short_position_cards(user_id)`: build display data for each active short (P/L, squeeze price, fee rate, entry price, current value)
    - Implement `_get_threat_horizon_data(user_id)`: calculate FreeCash runway color code (green > 60 ticks, amber 20–60, red < 20), tick countdown, aggregate fee rate
    - Pass short position data to dashboard template
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 8.2 Create short order form template (htmx partial)
    - Create template for the short order form with share quantity input
    - Wire htmx to call `/trade/short/preview` on input change for live cost breakdown
    - Display Position Size, Total Collateral, Crowding Surcharge %, Tick Fee, Squeeze Price
    - Include optional SL/TP input fields
    - Show insufficient funds indicator and disabled submit when collateral > FreeCash
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [x] 8.3 Create short position cards template for dashboard
    - Display active positions with: ore name, entry price, current price, unrealized P/L (green for profit, red for loss), squeeze price
    - Add Threat Horizon Meter (color-coded bar with tick countdown)
    - Add "Close Position" button per card, SL/TP edit controls
    - Wire htmx partial updates for tick-by-tick refresh
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 8.4 Add Squeeze Zone line to ore price chart
    - Add crimson dashed line labeled "Squeeze Zone" on the ore price chart when a player has an active short on that ore
    - Fetch squeeze price from dashboard data
    - _Requirements: 11.3_

  - [x] 8.5 Update leaderboard to use updated net worth formula
    - Ensure `src/app/routes/leaderboard.py` uses the updated `get_net_worth()` that includes short equity
    - Display net worth values inclusive of short position equity for all players
    - _Requirements: 12.3_

- [x] 9. Implement account reset and delete handling
  - [x] 9.1 Extend account reset logic to clean up short positions
    - Delete all `short_positions` WHERE user_id = ? (no collateral return, no influence registration)
    - Archive short-related transactions (SET archived=1 WHERE type IN ('short_open','short_close','short_liquidated'))
    - Process short cleanup BEFORE restoring default balance
    - Revoke Advanced Mode state (handled by advanced-mode feature, verify integration)
    - _Requirements: 14.1, 14.2, 14.3, 14.5_

  - [x] 9.2 Extend account delete logic to remove short positions
    - Delete all `short_positions` WHERE user_id = ?
    - Delete all `notifications` WHERE user_id = ?
    - Ensure cascading cleanup with existing holdings/transactions deletion
    - _Requirements: 14.4_

  - [x] 9.3 Write property test for account reset cleans all short state
    - **Property 19: Account Reset Cleans All Short State**
    - Test that after reset, zero short_positions exist for the player, no buying pressure is registered, and FreeCash is set to default balance (not increased by freed collateral)
    - **Validates: Requirements 14.1, 14.5**

- [x] 10. Integration tests and final checkpoint
  - [x] 10.1 Write integration tests for full short lifecycle
    - Open short → tick runs → price drops → voluntary close → verify profit credited
    - Open short → price rises → margin calls transfer FreeCash → eventually liquidation
    - Open short → many ticks → FreeCash exhausted by fees → liquidation triggered
    - Open short with SL → price rises past SL → verify auto-close in tick
    - Player has 3 shorts → tick processes all in correct order → verify final state
    - _Requirements: 2.5, 3.3, 4.2, 5.2, 6.1, 7.4_

  - [x] 10.2 Write integration tests for bot shorting
    - Set up bearish trend → verify bot opens short with SL → price reverses → SL fires
    - Verify bot capital cap (30%) prevents additional shorts
    - _Requirements: 13.5, 13.6, 13.7_

  - [x] 10.3 Write integration tests for net worth and account reset
    - Player with shorts appears with correct net worth on leaderboard
    - Account reset with active shorts → verify clean state, no orphaned records
    - Surplus release: price drops → required collateral decreases → surplus released to FreeCash
    - _Requirements: 12.1, 14.1, 14.5, 3.4_

  - [x] 10.4 Final checkpoint
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 19 universal correctness properties defined in the design document
- Unit tests validate specific examples and edge cases
- The project uses Hypothesis for property-based testing (`.hypothesis/` directory already exists)
- The shorting engine integrates into the existing tick loop after `process_tick()` — single-threaded to avoid SQLite locking
- The notification system is defined in a separate spec (`.kiro/specs/notification-system/`) and assumed to be available
- Bot shorting uses conservative parameters to prevent market destabilization
- All financial calculations use `round(x, 2)` for 2 decimal place precision
- The `@advanced_required` decorator (from the advanced-mode feature) gates all short routes

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["2.4", "2.5", "2.6", "2.7"] },
    { "id": 3, "tasks": ["3.1", "3.2", "3.3", "3.4", "3.5"] },
    { "id": 4, "tasks": ["3.6", "3.7", "3.8", "3.9", "3.10", "3.11", "3.12", "3.13"] },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5"] },
    { "id": 6, "tasks": ["5.6", "5.7", "5.8", "5.9"] },
    { "id": 7, "tasks": ["7.1", "7.2"] },
    { "id": 8, "tasks": ["7.3", "7.4", "7.5", "8.1"] },
    { "id": 9, "tasks": ["8.2", "8.3", "8.4", "8.5"] },
    { "id": 10, "tasks": ["9.1", "9.2"] },
    { "id": 11, "tasks": ["9.3", "10.1", "10.2", "10.3"] }
  ]
}
```
