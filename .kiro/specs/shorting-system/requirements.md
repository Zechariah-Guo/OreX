# Requirements Document

## Introduction

The Shorting System is an Advanced Mode feature for OreX that allows players to profit from declining ore prices by borrowing and selling shares, then buying them back later at a lower price. The system is modeled as a "reverse long position with a fuse" — players lock collateral, pay continuous time-bleed fees from their FreeCash, and face forced liquidation if FreeCash is exhausted. The feature integrates with the existing tick engine and introduces dynamic collateral management, crowding penalties, and automated stop loss/take profit triggers.

## Glossary

- **Tick_Engine**: The background thread that processes market price updates and short position calculations at a configurable interval (default 20 seconds, 180 ticks per hour).
- **FreeCash**: The player's liquid wallet balance (the existing `balance` field on the users table), used to pay fees and fund margin calls.
- **Short_Position**: A database record representing an active short trade, tracking the borrowed shares, entry price, locked collateral, and associated metadata.
- **Locked_Collateral**: The escrow amount frozen by the game engine when a short is opened. This capital is unavailable for other trades until the position is resolved.
- **Short_Value**: The live cost to buy back all borrowed shares at the current market price (Shares × Current_Price).
- **Short_Ratio**: A global crowdedness metric per ore: Total_Short_Positions / Total_Positions (Long + Short). Defaults to 0.0 when total positions equal zero.
- **Collateral_Multiplier**: A computed value determining total collateral requirements: Base_Requirement + (Max_Penalty × Short_Ratio^Steepness).
- **Margin_Call_Transfer**: An automatic per-tick operation that pulls funds from FreeCash into Locked_Collateral when the required collateral exceeds the currently locked amount.
- **Time_Bleed_Fee**: A per-tick cost deducted from FreeCash, calculated from the Short_Value, base hourly rate, max hourly fee, and ore volatility.
- **Squeeze_Price**: The calculated ore price at which a short position would exhaust the player's FreeCash and trigger forced liquidation.
- **Stop_Loss**: An optional automated trigger price that closes a short position when the ore price rises to that level.
- **Take_Profit**: An optional automated trigger price that closes a short position when the ore price drops to that level.
- **Advanced_Mode**: A gated feature tier unlocked at $100,000 net worth or purchasable for $50,000, granting access to shorting and other advanced tools.
- **Net_Worth**: The sum of a player's FreeCash plus the current market value of all long holdings plus short position equity.
- **Volatility**: The ore-specific metric (σ, scale 0.0 to 1.5) representing price fluctuation intensity, used in fee calculations.
- **Shorting_Engine**: The subsystem within the Tick_Engine responsible for processing all active Short_Positions each tick.

## Requirements

### Requirement 1: Advanced Mode Unlock

**User Story:** As a player, I want to unlock Advanced Mode when I reach sufficient net worth, so that I can access shorting and other advanced trading features.

#### Acceptance Criteria

1. WHEN a player's Net_Worth reaches or exceeds $100,000, THE Advanced_Mode SHALL mark the player as permanently eligible for purchase, and subsequent drops below $100,000 SHALL NOT revoke eligibility.
2. WHILE a player is eligible and has not yet purchased Advanced_Mode, THE Advanced_Mode SHALL be purchasable for $50,000 deducted from the player's FreeCash.
3. IF an eligible player attempts to purchase Advanced_Mode with a FreeCash balance below $50,000, THEN THE System SHALL reject the purchase and display an error message indicating insufficient funds.
4. WHILE Advanced_Mode is not active for a player (either not purchased, or purchased but toggled off), THE UI_System SHALL NOT render any shorting-related controls, forms, or navigation elements — making it impossible for the player to initiate a short position request.
5. WHEN Advanced_Mode is purchased, THE System SHALL persist the purchased status permanently so it remains available across browser sessions and logins.

### Requirement 2: Opening a Short Position

**User Story:** As an advanced player, I want to open a short position on an ore, so that I can profit when the ore price declines.

#### Acceptance Criteria

1. WHEN a player submits a short order, THE Shorting_Engine SHALL calculate the Short_Ratio for the target ore as Total_Short_Positions divided by Total_Positions, defaulting to 0.0 when Total_Positions equals zero.
2. WHEN a player submits a short order, THE Shorting_Engine SHALL calculate the Collateral_Multiplier as Base_Requirement (0.50) + (Max_Penalty (2.0) × Short_Ratio^Steepness (3)).
3. WHEN a player submits a short order, THE Shorting_Engine SHALL calculate Total_Locked_Collateral as (Shares × Current_Ore_Price at time of order submission) × Collateral_Multiplier.
4. IF a player submits a short order and the player's FreeCash is less than the calculated Total_Locked_Collateral, THEN THE Shorting_Engine SHALL reject the order and display an insufficient funds message indicating the required collateral amount and the player's available FreeCash.
5. WHEN a player submits a valid short order, THE Shorting_Engine SHALL deduct Total_Locked_Collateral from FreeCash and create a Short_Position record with entry price, share quantity, and locked collateral amount.
6. WHEN a short order is successfully opened, THE System SHALL record a transaction entry of type "short_open" including the ore identifier, share quantity, entry price, and locked collateral amount.
7. IF a player submits a short order with a share quantity less than 1 or greater than 10,000, THEN THE Shorting_Engine SHALL reject the order and display a validation error indicating the allowed range of 1 to 10,000 shares.
8. IF a player submits a short order with a non-integer share quantity, THEN THE Shorting_Engine SHALL reject the order and display a validation error indicating that share quantity must be a whole number.

### Requirement 3: Per-Tick Collateral Rebalancing

**User Story:** As a game system, I want to dynamically adjust locked collateral each tick, so that short positions remain adequately backed as prices change.

#### Acceptance Criteria

1. WHEN a tick occurs, THE Shorting_Engine SHALL recalculate Short_Value for each active Short_Position as Shares × Current_Ore_Price.
2. WHEN a tick occurs, THE Shorting_Engine SHALL recalculate the Collateral_Multiplier for each ore using the current Short_Ratio, then compute Required_Collateral for each active Short_Position as Short_Value × Collateral_Multiplier.
3. WHEN Required_Collateral exceeds the currently Locked_Collateral for a Short_Position, THE Shorting_Engine SHALL transfer the deficit amount from the player's FreeCash to Locked_Collateral (Margin_Call_Transfer).
4. WHEN Required_Collateral is less than the currently Locked_Collateral for a Short_Position, THE Shorting_Engine SHALL release the surplus amount from Locked_Collateral back to the player's FreeCash.
5. IF a Margin_Call_Transfer would reduce FreeCash below zero, THEN THE Shorting_Engine SHALL transfer all remaining FreeCash into Locked_Collateral and immediately trigger forced liquidation for that Short_Position.
6. WHEN a player holds multiple active Short_Positions, THE Shorting_Engine SHALL process Margin_Call_Transfers in order of descending Required_Collateral (largest position first) within a single tick.
7. THE Shorting_Engine SHALL complete all Margin_Call_Transfers and surplus releases for a tick before any Time_Bleed_Fee deductions are applied in that same tick.

### Requirement 4: Per-Tick Time-Bleed Fee

**User Story:** As a game system, I want to charge continuous borrowing fees on short positions, so that holding shorts indefinitely carries a cost and creates urgency.

#### Acceptance Criteria

1. WHEN a tick occurs, THE Shorting_Engine SHALL calculate the Tick_Fee_Cost for each active Short_Position as: Short_Value × ((Base_Hourly_Rate (0.005) + (Max_Hourly_Fee (0.10) × Volatility²)) / Ticks_Per_Hour), rounding the result to 2 decimal places.
2. WHEN a tick occurs and a player has multiple active Short_Positions, THE Shorting_Engine SHALL deduct each position's calculated Tick_Fee_Cost from the player's FreeCash in order of position opened_at timestamp (oldest first).
3. IF a Time_Bleed_Fee deduction would reduce FreeCash below zero, THEN THE Shorting_Engine SHALL deduct only the amount that brings FreeCash to exactly zero and trigger forced liquidation for that Short_Position, skipping fee processing for any remaining positions of that player.
4. THE Shorting_Engine SHALL apply Time_Bleed_Fees after completing all Margin_Call_Transfers within the same tick.

### Requirement 5: Voluntary Position Close

**User Story:** As an advanced player, I want to close my short position at any time, so that I can lock in profits or cut losses on my own terms.

#### Acceptance Criteria

1. WHEN a player requests to close a Short_Position that has a status of "active", THE Shorting_Engine SHALL calculate the current Short_Value as Shares × Current_Ore_Price.
2. WHEN a player closes a Short_Position and the Short_Value is less than or equal to Locked_Collateral, THE Shorting_Engine SHALL deduct Short_Value from Locked_Collateral and credit the remaining balance to the player's FreeCash.
3. IF a player closes a Short_Position and the Short_Value exceeds the Locked_Collateral, THEN THE Shorting_Engine SHALL deduct the deficit (Short_Value minus Locked_Collateral) from the player's FreeCash and credit zero from collateral.
4. WHEN a player closes a Short_Position, THE System SHALL record a transaction entry of type "short_close" with the profit or loss amount calculated as (Locked_Collateral returned to FreeCash) minus (the original margin deducted from FreeCash at position open).
5. WHEN a player closes a Short_Position, THE System SHALL set the Short_Position record status to "closed".
6. WHEN a player closes a Short_Position that has associated Stop_Loss or Take_Profit triggers, THE System SHALL remove those triggers so they no longer fire on subsequent ticks.
7. IF a player requests to close a Short_Position whose status is not "active" (e.g., already being liquidated or already closed), THEN THE Shorting_Engine SHALL reject the close request and indicate that the position is not eligible for voluntary close.

### Requirement 6: Forced Liquidation

**User Story:** As a game system, I want to automatically liquidate short positions when a player's FreeCash is exhausted, so that the game prevents negative balances and unbacked debt.

#### Acceptance Criteria

1. WHEN a player's FreeCash reaches zero during tick processing and the player has multiple active Short_Positions, THE Shorting_Engine SHALL initiate forced liquidation of Short_Positions one at a time in order of highest Short_Value first, stopping once FreeCash is no longer zero.
2. WHEN forced liquidation is triggered, THE Shorting_Engine SHALL calculate the buyback cost as Shares × Current_Ore_Price and deduct that amount from the position's Locked_Collateral.
3. WHEN forced liquidation is triggered, THE Shorting_Engine SHALL credit any remaining Locked_Collateral (Locked_Collateral minus buyback cost) to the player's FreeCash after the buyback.
4. THE Shorting_Engine SHALL guarantee that forced liquidation never produces a negative FreeCash balance.
5. WHEN forced liquidation occurs, THE System SHALL record a transaction entry of type "short_liquidated" with the loss amount calculated as Short_Value at liquidation minus Short_Value at entry (Shares × Entry_Price).
6. IF forced liquidation is caused by Time_Bleed_Fee deductions exhausting FreeCash, THEN THE System SHALL generate a notification to the player indicating the cause was ongoing fee costs depleting free cash reserves.
7. IF forced liquidation is caused by a Margin_Call_Transfer exhausting FreeCash, THEN THE System SHALL generate a notification to the player indicating the cause was rising ore price requiring additional collateral beyond available funds.
8. WHEN forced liquidation completes, THE System SHALL mark the affected Short_Position record as closed.

### Requirement 7: Stop Loss and Take Profit Triggers

**User Story:** As an advanced player, I want to set automated stop loss and take profit levels on my short positions, so that I can manage risk without constant monitoring.

#### Acceptance Criteria

1. WHEN a player opens or edits a Short_Position, THE System SHALL allow the player to set an optional Stop_Loss price (above current ore price) and an optional Take_Profit price (below current ore price).
2. IF a player sets a Stop_Loss price at or below the ore's current market price, THEN THE System SHALL reject the value with a validation error indicating Stop_Loss must be above current price.
3. IF a player sets a Take_Profit price at or above the ore's current market price, THEN THE System SHALL reject the value with a validation error indicating Take_Profit must be below current price.
4. WHEN a tick occurs and the ore's new price meets or exceeds a Short_Position's Stop_Loss price, THE Shorting_Engine SHALL close the position using the voluntary close procedure without deducting any final Time_Bleed_Fee for that tick.
5. WHEN a tick occurs and the ore's new price meets or falls below a Short_Position's Take_Profit price, THE Shorting_Engine SHALL close the position using the voluntary close procedure without deducting any final Time_Bleed_Fee for that tick.
6. THE Shorting_Engine SHALL evaluate Stop_Loss and Take_Profit triggers at the start of each tick, after the price update but before Margin_Call_Transfers and Time_Bleed_Fees.
7. WHEN both a Stop_Loss trigger and a FreeCash exhaustion condition occur in the same tick, THE Shorting_Engine SHALL execute the Stop_Loss close and suppress the forced liquidation.

### Requirement 8: Dynamic Tick Rate Integration

**User Story:** As a developer, I want the Shorting Engine to respect the existing configurable tick interval from config.py, so that fee calculations remain correct regardless of tick speed tuning.

#### Acceptance Criteria

1. THE Shorting_Engine SHALL derive Ticks_Per_Hour dynamically from the application's configured TICK_INTERVAL value (3600 / TICK_INTERVAL seconds) for all fee and collateral calculations.
2. THE Shorting_Engine SHALL NOT use a hardcoded value of 180 for Ticks_Per_Hour in any fee or collateral calculation.

### Requirement 9: Short Position Data Model

**User Story:** As a developer, I want a well-defined data model for short positions, so that the system can track all necessary state for each active short.

#### Acceptance Criteria

1. THE System SHALL store each Short_Position with: user_id (INTEGER NOT NULL), ore_id (INTEGER NOT NULL), share_quantity (INTEGER NOT NULL, minimum 1), entry_price (REAL NOT NULL, greater than 0), locked_collateral (REAL NOT NULL, greater than 0), stop_loss_price (REAL, nullable), take_profit_price (REAL, nullable), cumulative_fees_paid (REAL NOT NULL, default 0.0), opened_at (TEXT NOT NULL, default current timestamp), closed_at (TEXT, nullable), and status (TEXT NOT NULL, default 'active').
2. THE System SHALL restrict the status field of Short_Positions to the values 'active' or 'closed'.
3. THE System SHALL maintain referential integrity between Short_Positions and the users table (user_id) and ores table (ore_id) using foreign key constraints with RESTRICT on delete.
4. THE System SHALL index Short_Positions by user_id, by status, and by the combination of ore_id and status to support tick processing, dashboard, and market influence queries.
5. WHEN a Time_Bleed_Fee is deducted from a player's FreeCash for a Short_Position, THE Shorting_Engine SHALL increment the cumulative_fees_paid field on that Short_Position by the fee amount.
6. WHEN a Short_Position is closed (voluntary, forced liquidation, or stop loss/take profit trigger), THE System SHALL set the closed_at timestamp to the current time and update the status to 'closed'.

### Requirement 10: Transaction Preview

**User Story:** As an advanced player, I want to see a clear breakdown of costs before opening a short position, so that I understand the capital requirements and ongoing fees.

#### Acceptance Criteria

1. WHEN a player enters or adjusts a share quantity on the short order form, THE System SHALL display the calculated Position Size as Shares × Current_Price, formatted as a currency value with 2 decimal places.
2. WHEN a player enters or adjusts a share quantity on the short order form, THE System SHALL display the Total_Locked_Collateral amount that will be frozen, calculated as Position Size × Collateral_Multiplier.
3. WHEN a player enters or adjusts a share quantity on the short order form, THE System SHALL display the Crowding Surcharge as a percentage value derived from the current Short_Ratio penalty for that ore, rounded to 1 decimal place.
4. WHEN a player enters or adjusts a share quantity on the short order form, THE System SHALL display the estimated Tick Fee Cost per tick at current volatility, formatted as a currency value per tick interval (e.g., "-$X.XX / Every 20s").
5. WHEN a player enters or adjusts a share quantity on the short order form, THE System SHALL display the estimated Squeeze_Price at which the player's FreeCash would reach zero and forced liquidation would trigger.
6. WHEN a player adjusts the share quantity on the short order form, THE System SHALL update all displayed preview values within 500 milliseconds of the input change using htmx partial updates without a full page reload.
7. IF the Total_Locked_Collateral displayed in the preview exceeds the player's current FreeCash, THEN THE System SHALL visually indicate insufficient funds on the collateral line item and disable the order submission button.

### Requirement 11: Short Position Dashboard Display

**User Story:** As an advanced player, I want to monitor my active short positions with clear visual indicators, so that I can make timely trading decisions.

#### Acceptance Criteria

1. WHILE a player has active Short_Positions, THE System SHALL display a Threat Horizon Meter showing FreeCash runway as a color-coded horizontal bar (green when FreeCash covers more than 60 ticks of fees at current rate, amber between 20-60 ticks, red below 20 ticks).
2. WHILE a player has active Short_Positions, THE System SHALL display the current unrealized profit or loss for each position, calculated as (Entry_Price × Shares) - Short_Value, displayed green when positive (price fell) and red when negative (price rose).
3. WHILE a player has active Short_Positions, THE System SHALL display the Squeeze_Price as a bold dashed crimson line labeled "Squeeze Zone" on the ore price chart.
4. WHILE a player has active Short_Positions, THE System SHALL display a countdown estimate beneath the Threat Horizon Meter showing remaining ticks before liquidation, calculated as FreeCash divided by (aggregate Tick_Fee_Cost + estimated per-tick margin call based on recent price movement).
5. THE System SHALL update all dashboard short position displays each tick via htmx partial page updates without requiring a full page refresh.

### Requirement 12: Net Worth Calculation Update

**User Story:** As a game system, I want the net worth calculation to account for short positions, so that the leaderboard and unlock thresholds remain accurate.

#### Acceptance Criteria

1. THE System SHALL calculate Net_Worth as: FreeCash + SUM(Long_Holdings_Quantity × Current_Ore_Price) + SUM(Locked_Collateral - Short_Value) across all of the player's active Short_Positions.
2. WHEN a player has no active Short_Positions, THE System SHALL calculate Net_Worth as FreeCash + SUM(Long_Holdings_Quantity × Current_Ore_Price), producing the same result as the legacy formula.
3. WHEN displaying the leaderboard, THE System SHALL rank all players by the updated Net_Worth formula and display each player's Net_Worth value inclusive of short position equity.
4. WHEN evaluating Advanced_Mode unlock eligibility, THE System SHALL compare the player's Net_Worth calculated with the updated formula against the Eligibility_Threshold.
5. WHEN displaying the portfolio summary on the dashboard, THE System SHALL use the updated Net_Worth formula that includes short position equity.

### Requirement 13: Short Position Influence on Market

**User Story:** As a game system, I want short selling activity to influence ore price probabilities, so that the market algorithm responds to player behavior realistically.

#### Acceptance Criteria

1. WHEN a player short position is opened, THE Market_Algorithm SHALL register a sell-type trade in the player influence queue for the target ore with a quantity equal to the shorted share count, applying the same PLAYER_INFLUENCE_RATE (0.0005 probability shift per unit) used for regular player trades.
2. WHEN a player short position is closed voluntarily or via forced liquidation, THE Market_Algorithm SHALL register a buy-type trade in the player influence queue for the target ore with a quantity equal to the bought-back share count, applying the same PLAYER_INFLUENCE_RATE (0.0005 probability shift per unit) used for regular player trades.
3. THE Market_Algorithm SHALL process short-originated influence entries identically to regular player trade entries within the existing consume_player_trades mechanism, requiring no separate queue or influence path.
4. WHEN a bot opens or closes a short position, THE Market_Algorithm SHALL register the corresponding sell or buy pressure in the bot influence queue using the existing BOT_INFLUENCE_RATE (0.0005 probability shift per unit).
5. THE Bot_System SHALL only open short positions when a configurable risk assessment determines the ore's recent trend is strongly bearish (e.g., 4 out of 5 recent trend_log entries are "fall") AND the bot's FreeCash can sustain at least 30 ticks of estimated fees after collateral lockup.
6. THE Bot_System SHALL set a mandatory Stop_Loss on every bot short position at a conservative threshold (e.g., 5% above entry price) to prevent bots from being fully liquidated and losing their market-making capacity.
7. THE Bot_System SHALL limit total bot capital committed to short positions to a maximum of 30% of each bot's total balance, preserving the remaining 70% for long-side market-making activity.

### Requirement 14: Account Reset Handling

**User Story:** As a game system, I want account resets to properly clean up short positions, so that players start fresh without orphaned data.

#### Acceptance Criteria

1. WHEN a player resets their account, THE System SHALL delete all Short_Position records for that player without crediting any Locked_Collateral back to FreeCash and without registering buying pressure in the Market_Algorithm.
2. WHEN a player resets their account, THE System SHALL set archived=1 on all short-related transaction records (types "short_open", "short_close", "short_liquidated") for that player.
3. WHEN a player resets their account, THE System SHALL revoke Advanced_Mode purchased status and eligibility, requiring the player to re-reach the Eligibility_Threshold of $100,000 Net_Worth and re-purchase for $50,000.
4. WHEN a player deletes their account, THE System SHALL permanently delete all Short_Position records and all short-related transaction records for that player.
5. WHEN a player resets their account while holding active Short_Positions, THE System SHALL process the short position cleanup before restoring the default balance, so that no tick processing can act on stale position data during the reset.
