# Implementation Plan: Finances Page

## Overview

Implement the Finances Page — an Advanced Mode-exclusive financial dashboard that surfaces capital allocation breakdown (free cash, locked collateral, short equity, long holdings value, net worth), active short positions with per-position metrics, and cash flow projections (fee burn rate, cash runway indicator). The page follows the existing htmx polling pattern: a full-page template includes a partial that refreshes every 20 seconds. No new tables or columns are required — all data is read from existing tables.

## Tasks

- [x] 1. Create finances helper module
  - [x] 1.1 Create `src/app/finances.py` with core calculation functions
    - Implement `get_finances_data(user_id)` orchestrator that queries all data and returns the full context dict
    - Implement `get_active_short_positions(user_id)` fetching active positions joined with ore data, computing per-position short_value, unrealized_pnl, tick_fee, ticks_to_liquidation
    - Implement `calculate_fee_burn_per_tick(positions, ores_map)` using formula: `SUM(round(short_value * ((0.005 + 0.10 * volatility^2) / ticks_per_hour), 2))`
    - Implement `calculate_cash_runway(free_cash, fee_burn_per_tick)` returning integer tick count (floor division), or max int when fee_burn is zero
    - Implement `format_runway_duration(ticks, tick_interval)` converting tick count to human-readable string (e.g., "~450 ticks / ~2h 30m")
    - Implement `get_runway_color(ticks)` returning 'green' (>60), 'amber' (20-60 inclusive), or 'red' (<20)
    - Derive `ticks_per_hour` dynamically as `3600 / Config.TICK_INTERVAL`
    - Handle edge cases: no short positions → all aggregates 0.0, fee burn 0 → infinite runway
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.3, 4.5, 5.1, 5.2, 5.3, 5.4, 5.6, 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 1.2 Write property test for net worth formula
    - **Property 1: Net Worth Formula**
    - Generate random balance (≥0), lists of holdings (quantity ≥1, price >0), and short positions (locked_collateral >0, shares ≥1, price >0)
    - Verify computed net_worth = balance + Σ(q_i × p_i) + Σ(L_j − (s_j × cp_j))
    - **Validates: Requirements 3.5**

  - [x] 1.3 Write property test for short position aggregates
    - **Property 2: Short Position Aggregates**
    - Generate random lists of short positions (including empty list)
    - Verify total_locked_collateral = Σ(L_i), total_short_equity = Σ(L_i − s_i × p_i), total_exposure = Σ(s_i × p_i), total_fees_paid = Σ(f_i), position_count = len(list)
    - **Validates: Requirements 3.2, 3.3, 4.5**

  - [x] 1.4 Write property test for fee burn calculation
    - **Property 3: Fee Burn Calculation**
    - Generate random (short_value, volatility) pairs and tick_interval values
    - Verify fee_burn_per_tick = Σ(round(SV_i × ((0.005 + 0.10 × v_i²) / (3600 / T)), 2)) and fee_burn_per_hour = fee_burn_per_tick × (3600 / T)
    - **Validates: Requirements 5.1, 5.2**

  - [x] 1.5 Write property test for cash runway calculation
    - **Property 4: Cash Runway Calculation**
    - Generate random free_cash (≥0) and fee_burn_per_tick (>0)
    - Verify cash_runway_ticks = floor(free_cash / fee_burn_per_tick)
    - Also verify per-position ticks_to_liquidation = floor(free_cash / tick_fee) for tick_fee > 0
    - **Validates: Requirements 4.3, 5.3**

  - [x] 1.6 Write property test for runway indicator classification
    - **Property 5: Runway Indicator Classification**
    - Generate random non-negative integer tick counts
    - Verify: green when >60, amber when 20≤ticks≤60, red when <20
    - Verify bar width = min(ticks / 120, 1.0) × 100%
    - Verify liquidation warning text present iff ticks < 20
    - Verify fee_burn=0 → infinite runway with green color and full bar
    - **Validates: Requirements 5.4, 7.1, 7.2, 7.3, 7.4, 7.5**

  - [x] 1.7 Write property test for currency and percentage formatting
    - **Property 6: Currency and Percentage Formatting**
    - Generate random non-negative floats for currency, verify output matches `$[digits with comma grouping].[2 decimals]`
    - Generate random floats for percentage, verify output has exactly 1 decimal place followed by "%"
    - **Validates: Requirements 3.1, 8.2, 8.3**

- [x] 2. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Create finances route and blueprint
  - [x] 3.1 Create `src/app/routes/finances.py` with the finances blueprint
    - Create `finances_bp` Blueprint
    - Implement `GET /finances` route with `@login_required` and `@advanced_required` decorators
    - Call `get_finances_data(current_user.id)` for context
    - On htmx request (HX-Request header): return `partials/finances_live.html` partial
    - On full request: return `pages/finances.html` full page
    - _Requirements: 1.1, 1.2, 1.3, 6.1, 6.2, 6.3_

  - [x] 3.2 Register finances blueprint in `src/app/routes/__init__.py`
    - Import and register `finances_bp` in the app route registration
    - _Requirements: 1.1_

  - [x] 3.3 Write unit tests for finances route access control
    - Test GET /finances returns 200 for authenticated advanced-mode user
    - Test GET /finances redirects unauthenticated users to login
    - Test GET /finances returns 403 for user without advanced mode
    - Test htmx request returns partial HTML only (no `<html>` wrapper)
    - _Requirements: 1.1, 1.2, 1.3, 6.2_

- [x] 4. Create finances page templates
  - [x] 4.1 Create `src/templates/pages/finances.html` full page template
    - Extend `base.html`
    - Set page title to "Finances - OreX"
    - Add page header with "Finances" heading and htmx indicator
    - Add `#finances-live` container with `hx-get`, `hx-trigger="every 20s"`, `hx-swap="innerHTML"`, and `hx-indicator`
    - Include `partials/finances_live.html` for initial render
    - Add htmx error recovery JavaScript: redirect to dashboard on 403 response
    - _Requirements: 6.1, 6.2, 6.3, 9.1, 9.2_

  - [x] 4.2 Create `src/templates/partials/finances_live.html` live partial template
    - **Capital Breakdown section**: Display Free Cash, Locked Collateral, Short Equity, Long Holdings Value, Net Worth as labeled stat cards with formatted currency values ($X,XXX.XX)
    - Display Locked Collateral as $0.00 and Short Equity as $0.00 when no active shorts
    - Visually distinguish each category as separate labeled line items summing to Net Worth
    - **Active Short Positions section** (conditional: only when has_shorts is True):
      - Table with columns: ore name, shares, entry price, short value, locked collateral, unrealized PnL, SL price, TP price, ticks to liquidation
      - Color unrealized PnL green (positive) / red (negative)
      - Show "None" for SL/TP when not set
      - Aggregate summary below table: position count, total exposure, total cumulative fees paid
      - Empty state message when no active positions
    - **Cash Flow Projections section** (conditional: only when has_shorts is True):
      - Fee burn rate per tick (e.g., "-$X.XX / tick")
      - Fee burn rate per hour
      - Cash runway as tick count + formatted time duration (e.g., "~450 ticks / ~25 minutes")
      - Cash Runway Indicator: color-coded horizontal bar (green/amber/red) with width proportional to runway
      - "Liquidation imminent" text warning when runway < 20 ticks
    - Handle zero free cash: display "$0.00" and "0 ticks" with red indicator
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 9.3, 9.4_

- [x] 5. Update navigation and entry points
  - [x] 5.1 Update `src/templates/partials/nav.html` to make green money pill a conditional link
    - When `is_advanced_active` is True: render balance as `<a>` linking to `/finances`and have the pill expand on hover
    - When `is_advanced_active` is False: render balance as non-interactive `<span>`
    - Ensure the displayed Free_Cash value remains visible regardless of mode
    - _Requirements: 1.4, 1.5, 2.1, 2.2, 2.4_

  - [x] 5.2 Update portfolio template to add "View Finances" link
    - Add a "View Finances" button/link in the portfolio section, wrapped in `{% if is_advanced_active %}`
    - Link navigates to `/finances` route
    - _Requirements: 2.3_

- [x] 6. Add finances page CSS styles
  - [x] 6.1 Add CSS styles for the finances page to `src/static/css/`
    - Style the capital breakdown stat cards layout
    - Style the active short positions table with horizontal scroll on narrow viewports
    - Style the cash flow projections section
    - Style the Cash Runway Indicator bar (green/amber/red color classes, proportional width)
    - Style the "Liquidation imminent" warning text
    - Style unrealized PnL color classes (green for positive, red for negative)
    - Apply OreX Advanced Theme styling consistent with other Advanced Mode pages
    - Style empty state messages
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.1, 8.4, 8.5_

- [x] 7. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Integration tests and final verification
  - [x] 8.1 Write integration tests for the full finances page lifecycle
    - Test: open short position → load /finances → verify position appears in table with correct metrics
    - Test: close short position → reload /finances partial → verify position removed
    - Test: fee burn displayed matches actual tick engine formula
    - Test: account reset while on finances → next request returns 403/redirect
    - Test: toggle Advanced Mode off → next request returns 403/redirect
    - Test: multiple positions → verify aggregates (total exposure, total fees, position count) match individual rows
    - Test: zero free cash with active shorts → displays "$0.00" and "0 ticks" with red indicator
    - _Requirements: 1.1, 1.3, 4.1, 4.5, 5.1, 6.4, 6.5, 9.1, 9.2, 9.3, 9.4_

  - [x] 8.2 Final checkpoint
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (6 properties total in tasks 1.2–1.7)
- Unit tests validate specific examples and edge cases
- No new database tables or columns are needed — the page reads from existing `users`, `holdings`, `ores`, and `short_positions` tables
- The htmx polling pattern mirrors the existing portfolio page implementation
- The `@advanced_required` decorator already exists from the Advanced Mode spec
- The `is_advanced_active` context processor is already injected into templates
- All currency formatting uses 2 decimal places with comma-separated thousands ($X,XXX.XX)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "1.6", "1.7"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "4.1", "4.2"] },
    { "id": 4, "tasks": ["5.1", "5.2", "6.1"] },
    { "id": 5, "tasks": ["8.1"] }
  ]
}
```
