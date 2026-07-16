# Requirements Document

## Introduction

The Finances Page is an Advanced Mode-exclusive financial dashboard for OreX that provides advanced players with a comprehensive breakdown of their capital allocation. It surfaces where money is tied up — free cash, locked collateral across short positions, long holdings value, and short position equity — enabling players to understand their total financial exposure at a glance. The page also presents active short position details, real-time fee burn rate projections, and a visual cash runway indicator, making the complex shorting mechanics transparent and actionable. The page is accessible by clicking the green money pill (balance display) in the navigation header when Advanced Mode is active, and optionally from the portfolio section.

## Glossary

- **Finances_Page**: A dedicated authenticated page at `/finances` displaying a player's complete financial breakdown, accessible only when Advanced_Mode is active
- **Free_Cash**: The player's liquid wallet balance stored in the users.balance column, available for trading and fee payments
- **Locked_Collateral**: The sum of all escrow amounts frozen across the player's active Short_Positions, unavailable for other trades
- **Short_Equity**: The calculated value of a single short position's collateral surplus or deficit: Locked_Collateral minus Short_Value (Shares × Current_Ore_Price)
- **Total_Short_Equity**: The aggregate Short_Equity across all of a player's active Short_Positions
- **Long_Holdings_Value**: The total current market value of all long ore holdings (SUM(holdings.quantity × ore.current_price))
- **Net_Worth**: The sum of Free_Cash + Long_Holdings_Value + Total_Short_Equity
- **Green_Money_Pill**: The balance display element in the navigation header that shows the player's Free_Cash, which becomes a clickable link to the Finances_Page when Advanced_Mode is active
- **Fee_Burn_Rate**: The total Time_Bleed_Fee cost per tick aggregated across all active Short_Positions
- **Cash_Runway**: The estimated number of ticks (or formatted time duration) until Free_Cash reaches zero at the current Fee_Burn_Rate, assuming no other balance changes
- **Cash_Runway_Indicator**: A color-coded visual bar displaying the Cash_Runway with green (safe), amber (caution), and red (danger) zones
- **Short_Value**: The live buyback cost of a short position calculated as Shares × Current_Ore_Price
- **Unrealized_PnL**: The profit or loss on an active short position calculated as (Entry_Price × Shares) minus Short_Value
- **Tick_Engine**: The background market engine that updates ore prices every 20 seconds
- **Advanced_Mode**: A gated feature tier that must be purchased and active to access the Finances_Page
- **Short_Position**: A database record representing an active short trade with entry price, share quantity, locked collateral, and associated metadata

## Requirements

### Requirement 1: Page Route and Access Control

**User Story:** As an advanced player, I want a dedicated finances page that is only accessible when Advanced Mode is active, so that the feature remains hidden from standard-mode players.

#### Acceptance Criteria

1. THE Finances_Page SHALL be accessible at the `/finances` URL path for authenticated players with Advanced_Mode active
2. WHEN an unauthenticated user attempts to access the Finances_Page, THE Finances_Page SHALL redirect the user to the login page
3. WHEN an authenticated player without Advanced_Mode active attempts to access the Finances_Page, THE Finances_Page SHALL return a 403 Forbidden response and display a message indicating the page requires Advanced Mode
4. WHILE Advanced_Mode is not active for a player, THE UI_System SHALL NOT render any navigation links or elements that reference the Finances_Page
5. WHILE Advanced_Mode is active for a player, THE Green_Money_Pill in the navigation header SHALL function as a clickable link navigating to the Finances_Page

### Requirement 2: Navigation and Entry Points

**User Story:** As an advanced player, I want to reach the finances page by clicking the green money pill or from the portfolio section, so that access is intuitive from contexts where I am thinking about money.

#### Acceptance Criteria

1. WHILE Advanced_Mode is active, THE Green_Money_Pill SHALL render as a clickable anchor element linking to the `/finances` route
2. WHILE Advanced_Mode is not active, THE Green_Money_Pill SHALL render as a non-interactive display element with no link behavior
3. WHILE Advanced_Mode is active, THE Portfolio section on the dashboard SHALL include a "View Finances" link navigating to the Finances_Page
4. THE Green_Money_Pill SHALL continue to display the player's current Free_Cash value regardless of Advanced_Mode state (the value is always visible; only the link behavior changes)

### Requirement 3: Capital Breakdown Display

**User Story:** As an advanced player, I want to see how my total net worth is split across free cash, locked collateral, short equity, and long holdings, so that I understand where my capital is allocated.

#### Acceptance Criteria

1. THE Finances_Page SHALL display Free_Cash as a formatted currency value with 2 decimal places
2. THE Finances_Page SHALL display Total Locked_Collateral as a formatted currency value representing the sum of locked_collateral across all active Short_Positions for the player
3. THE Finances_Page SHALL display Total_Short_Equity as a formatted currency value, calculated as SUM(Locked_Collateral minus Short_Value) across all active Short_Positions
4. THE Finances_Page SHALL display Long_Holdings_Value as a formatted currency value, calculated as SUM(holdings.quantity × ore.current_price) across all the player's holdings
5. THE Finances_Page SHALL display Net_Worth as a formatted currency value, calculated as Free_Cash + Long_Holdings_Value + Total_Short_Equity
6. THE Finances_Page SHALL visually distinguish each capital category (Free_Cash, Locked_Collateral, Short_Equity, Long_Holdings_Value) as separate labeled line items that sum to Net_Worth
7. WHEN a player has no active Short_Positions, THE Finances_Page SHALL display Locked_Collateral as $0.00 and Total_Short_Equity as $0.00

### Requirement 4: Active Short Positions Table

**User Story:** As an advanced player, I want a detailed table of my active short positions on the finances page, so that I can monitor each position's health and key metrics in one place.

#### Acceptance Criteria

1. WHILE a player has active Short_Positions, THE Finances_Page SHALL display a table listing each position with: ore name, share quantity, entry price, current Short_Value, locked collateral, Unrealized_PnL, Stop_Loss price (or "None"), and Take_Profit price (or "None")
2. THE Finances_Page SHALL format Unrealized_PnL with a green color when positive (player is profiting) and a red color when negative (player is losing)
3. THE Finances_Page SHALL display the estimated ticks to liquidation for each position, calculated as the player's Free_Cash divided by that position's per-tick fee cost
4. WHEN a player has no active Short_Positions, THE Finances_Page SHALL display an empty state message indicating no active short positions exist
5. THE Finances_Page SHALL display aggregate summary values below the table: total position count, total exposure (sum of all Short_Values), and total cumulative fees paid across all active positions

### Requirement 5: Cash Flow and Fee Burn Projection

**User Story:** As an advanced player, I want to see my current fee burn rate and how long my free cash will last, so that I can plan trades and avoid surprise liquidations.

#### Acceptance Criteria

1. WHILE a player has active Short_Positions, THE Finances_Page SHALL display the Fee_Burn_Rate as a formatted currency value per tick (e.g., "-$X.XX / tick")
2. WHILE a player has active Short_Positions, THE Finances_Page SHALL display the Fee_Burn_Rate converted to an hourly rate (Fee_Burn_Rate × Ticks_Per_Hour) for readability
3. WHILE a player has active Short_Positions, THE Finances_Page SHALL display the Cash_Runway as both a tick count and a formatted time duration (e.g., "~450 ticks / ~25 minutes")
4. WHILE a player has active Short_Positions, THE Finances_Page SHALL display a Cash_Runway_Indicator as a color-coded horizontal bar: green when Cash_Runway exceeds 60 ticks, amber between 20 and 60 ticks, and red below 20 ticks
5. WHEN a player has no active Short_Positions, THE Finances_Page SHALL hide the fee burn projection section entirely
6. THE Finances_Page SHALL derive Ticks_Per_Hour dynamically from the application's configured TICK_INTERVAL value (3600 / TICK_INTERVAL) for all displayed calculations

### Requirement 6: Real-Time Updates via Tick Engine

**User Story:** As an advanced player, I want the finances page to update automatically each tick without a full page reload, so that I always see current data reflecting the latest price movements and fee deductions.

#### Acceptance Criteria

1. THE Finances_Page SHALL refresh all displayed financial values (Free_Cash, Locked_Collateral, Short_Equity, Long_Holdings_Value, Net_Worth, position table, fee projections) each tick via htmx partial page updates
2. THE Finances_Page SHALL NOT require a full page reload to display updated financial data after a tick occurs
3. THE Finances_Page SHALL use the existing Tick_Engine interval (default 20 seconds) as the refresh cadence for htmx polling
4. WHEN a Short_Position is closed (voluntarily, via Stop_Loss/Take_Profit trigger, or via forced liquidation) between page loads, THE Finances_Page SHALL remove that position from the active positions table on the next tick update
5. WHEN a new Short_Position is opened between page loads, THE Finances_Page SHALL add that position to the active positions table on the next tick update

### Requirement 7: Cash Runway Indicator Thresholds

**User Story:** As an advanced player, I want clear visual danger signals when my free cash is running low relative to my fee obligations, so that I can act before forced liquidation occurs.

#### Acceptance Criteria

1. WHILE Cash_Runway exceeds 60 ticks, THE Cash_Runway_Indicator SHALL render the bar in green with a width proportional to remaining runway (capped at full width for 120 or more ticks)
2. WHILE Cash_Runway is between 20 and 60 ticks inclusive, THE Cash_Runway_Indicator SHALL render the bar in amber
3. WHILE Cash_Runway is below 20 ticks, THE Cash_Runway_Indicator SHALL render the bar in red
4. WHILE Cash_Runway is below 20 ticks, THE Cash_Runway_Indicator SHALL display an additional text warning: "Liquidation imminent"
5. THE Cash_Runway_Indicator SHALL calculate Cash_Runway as Free_Cash divided by Fee_Burn_Rate, treating a Fee_Burn_Rate of zero as infinite runway (green, full bar)

### Requirement 8: Responsive Layout and Formatting

**User Story:** As an advanced player, I want the finances page to present complex data in a readable, well-organized layout, so that I can quickly parse my financial state without confusion.

#### Acceptance Criteria

1. THE Finances_Page SHALL organize content into clearly labeled sections: Capital Breakdown, Active Short Positions, and Cash Flow Projections
2. THE Finances_Page SHALL format all currency values with a dollar sign prefix, comma-separated thousands, and exactly 2 decimal places (e.g., "$1,234,567.89")
3. THE Finances_Page SHALL format percentage values with 1 decimal place and a percent suffix (e.g., "12.5%")
4. THE Finances_Page SHALL render the active short positions table with horizontal scrolling on viewports narrower than the table's natural width, preserving all columns without truncation
5. THE Finances_Page SHALL apply the OreX_Advanced_Theme styling consistent with other Advanced Mode pages

### Requirement 9: Account Reset and State Handling

**User Story:** As a game system, I want the finances page to handle edge cases gracefully, so that players never see stale or broken data.

#### Acceptance Criteria

1. WHEN a player resets their account while on the Finances_Page, THE Finances_Page SHALL redirect the player away from the page (since Advanced_Mode is revoked on reset) on the next navigation or tick update
2. WHEN a player toggles Advanced_Mode off while on the Finances_Page, THE Finances_Page SHALL redirect the player to the dashboard on the next navigation action
3. WHEN all active Short_Positions are closed or liquidated, THE Finances_Page SHALL transition to display only the Capital Breakdown section (with Locked_Collateral and Short_Equity at $0.00), hiding the positions table and fee projections
4. THE Finances_Page SHALL handle the case where the player has zero Free_Cash by displaying $0.00 in the Free_Cash field and showing Cash_Runway as "0 ticks" with a red indicator
