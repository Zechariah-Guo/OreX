# Requirements Document

## Introduction

Advanced Mode is a progression-gated prestige layer for OreX that unlocks expanded gameplay mechanics once a player demonstrates sufficient market mastery. It introduces stop loss/take profit orders, shorting capabilities, technical analysis metrics (resistance and support), and a custom visual theme — transforming the experience into a more sophisticated trading simulation for experienced players.

## Glossary

- **Advanced_Mode**: A purchasable feature flag on a player account that, when activated, enables expanded trading mechanics and a distinct visual theme
- **Net_Worth**: The sum of a player's free cash balance and the current market value of all ore holdings (balance + SUM(holdings.quantity * ore.current_price))
- **Free_Cash**: The player's uninvested liquid wallet balance stored in the users.balance column
- **Eligibility_Threshold**: The net worth value of $100,000 that a player must reach to become eligible to purchase Advanced Mode
- **Purchase_Cost**: The one-time fee of $50,000 deducted from Free_Cash to unlock Advanced Mode
- **Stop_Loss**: An automated sell order that triggers when an ore's price drops to a player-defined floor, limiting downside risk
- **Take_Profit**: An automated sell order that triggers when an ore's price rises to a player-defined ceiling, securing gains
- **Resistance_Level**: A calculated price point above the current price where selling pressure has historically prevented further upward movement
- **Support_Level**: A calculated price point below the current price where buying pressure has historically prevented further downward movement
- **OreX_Advanced_Theme**: A distinct UI presentation mode featuring advanced-specific layouts, expanded interface elements, and the OreX Advanced logo — focused on functional UI changes rather than purely cosmetic color schemes
- **Leaderboard_Indicator**: A red-colored username display on the leaderboard denoting a player with Advanced Mode active
- **Settings_Page**: The existing user settings interface where Advanced Mode activation controls reside
- **Tick_Engine**: The background market engine that updates ore prices every 20-30 seconds

## Requirements

### Requirement 1: Eligibility Detection

**User Story:** As a player, I want the game to detect when my net worth reaches $100,000, so that I become permanently eligible to purchase Advanced Mode.

#### Acceptance Criteria

1. WHEN a player's Net_Worth reaches or exceeds the Eligibility_Threshold of $100,000, THE Advanced_Mode_System SHALL mark the player as permanently eligible for purchase
2. WHEN a player's Net_Worth subsequently falls below the Eligibility_Threshold after having previously reached the Eligibility_Threshold, THE Advanced_Mode_System SHALL retain the player's eligibility status without revoking access
3. THE Advanced_Mode_System SHALL calculate Net_Worth as the sum of Free_Cash and the total current market value of all ore holdings

### Requirement 2: Settings UI Visibility

**User Story:** As a player, I want to always see the Advanced Mode activation box in my Settings page, so that I know the feature exists and understand what is required to unlock it.

#### Acceptance Criteria

1. THE Settings_Page SHALL display the Advanced Mode activation box as a dedicated element within the existing "Themes" section (alongside the light/dark mode controls) for all players regardless of eligibility or purchase status
2. WHILE a player has not reached the Eligibility_Threshold, THE Settings_Page SHALL render the Advanced Mode activation box in a disabled (greyed-out) state with a message indicating the $100,000 net worth requirement
3. WHILE a player is eligible but has not purchased Advanced Mode, THE Settings_Page SHALL render the activation box as enabled with a purchase button showing the $50,000 cost
4. WHILE a player has purchased Advanced Mode, THE Settings_Page SHALL render the activation box as a toggle switch allowing the player to enable or disable Advanced Mode freely

### Requirement 3: Purchase Transaction

**User Story:** As an eligible player, I want to purchase Advanced Mode for $50,000 from my free cash, so that I can access the expanded gameplay mechanics.

#### Acceptance Criteria

1. WHEN an eligible player confirms the Advanced Mode purchase, THE Advanced_Mode_System SHALL deduct the Purchase_Cost of $50,000 from the player's Free_Cash balance
2. IF a player attempts to purchase Advanced Mode with a Free_Cash balance below $50,000, THEN THE Advanced_Mode_System SHALL reject the purchase and display an insufficient funds message
3. IF a player who has not reached the Eligibility_Threshold attempts to purchase Advanced Mode, THEN THE Advanced_Mode_System SHALL reject the purchase and display an ineligibility message
4. WHEN the purchase is successfully completed, THE Advanced_Mode_System SHALL persist the purchased status on the player's account permanently
5. THE Advanced_Mode_System SHALL process the purchase as a one-time transaction that is not reversible or refundable

### Requirement 4: Toggle Activation

**User Story:** As a player who has purchased Advanced Mode, I want to toggle it on or off with confirmation, so that I can switch between the standard and advanced experience deliberately.

#### Acceptance Criteria

1. WHEN a player who has purchased Advanced Mode requests to toggle the mode, THE Advanced_Mode_System SHALL display a confirmation popup listing the specific changes between standard and advanced modes before applying the switch
2. WHEN the player confirms the toggle action, THE Advanced_Mode_System SHALL enable or disable all advanced features for that player immediately
3. WHEN a player toggles Advanced Mode, THE Advanced_Mode_System SHALL enforce a 5-minute cooldown before the player can toggle again
4. WHILE the 5-minute cooldown is active, THE Settings_Page SHALL disable the toggle switch and display the remaining cooldown time
5. THE Advanced_Mode_System SHALL persist the player's current toggle state across browser sessions and logins

### Requirement 5: Feature Gating

**User Story:** As a player, I want advanced features to be completely hidden when Advanced Mode is not active, so that the standard interface remains clean and uncluttered.

#### Acceptance Criteria

1. WHILE Advanced Mode is not active for a player, THE UI_System SHALL hide all Stop_Loss and Take_Profit controls from the trading interface
2. WHILE Advanced Mode is not active for a player, THE UI_System SHALL hide all shorting-related controls and displays from the trading interface
3. WHILE Advanced Mode is not active for a player, THE UI_System SHALL hide Resistance_Level and Support_Level metrics from all chart displays
4. WHILE Advanced Mode is active for a player, THE UI_System SHALL display Stop_Loss and Take_Profit controls on all trade order forms
5. WHILE Advanced Mode is active for a player, THE UI_System SHALL display Resistance_Level and Support_Level metrics on all ore price charts
6. WHILE Advanced Mode is active for a player, THE UI_System SHALL display shorting controls on the trading interface

### Requirement 6: Stop Loss and Take Profit Orders

**User Story:** As an advanced player, I want to set stop loss and take profit prices on my trades, so that positions are automatically closed when price targets are hit.

#### Acceptance Criteria

1. WHILE Advanced Mode is active, THE Trading_System SHALL allow the player to set an optional Stop_Loss price on any buy order
2. WHILE Advanced Mode is active, THE Trading_System SHALL allow the player to set an optional Take_Profit price on any buy order
3. WHEN the Tick_Engine updates an ore's price to at or below a holding's Stop_Loss price, THE Trading_System SHALL automatically sell the entire holding at the current market price
4. WHEN the Tick_Engine updates an ore's price to at or above a holding's Take_Profit price, THE Trading_System SHALL automatically sell the entire holding at the current market price
5. IF a player sets a Stop_Loss price at or above the ore's current market price, THEN THE Trading_System SHALL reject the order with a validation error
6. IF a player sets a Take_Profit price at or below the ore's current market price, THEN THE Trading_System SHALL reject the order with a validation error
7. THE Trading_System SHALL allow a player to modify or remove Stop_Loss and Take_Profit prices on existing holdings while Advanced Mode is active

### Requirement 7: Resistance and Support Metrics

**User Story:** As an advanced player, I want to see resistance and support levels on ore price charts, so that I can make more informed trading decisions.

#### Acceptance Criteria

1. WHILE Advanced Mode is active, THE Chart_System SHALL calculate and display a Resistance_Level as a dotted line on each ore's price chart on the ore detail page
2. WHILE Advanced Mode is active, THE Chart_System SHALL calculate and display a Support_Level as a dotted line on each ore's price chart on the ore detail page
3. WHEN the Tick_Engine updates an ore's price, THE Chart_System SHALL recalculate the Resistance_Level and Support_Level based on a rolling lookback window of the most recent price history entries
4. THE Chart_System SHALL calculate Resistance_Level as the highest price reached within the lookback window, representing the price ceiling where historical selling pressure prevented further upward movement
5. THE Chart_System SHALL calculate Support_Level as the lowest price reached within the lookback window, representing the price floor where historical buying pressure prevented further downward movement
6. THE Chart_System SHALL use a configurable lookback window (default: 50 most recent price ticks) for resistance and support calculations
7. THE Chart_System SHALL optionally display resistance and support values as an info box alongside the existing ore statistics on the ore detail page, in addition to the chart overlay lines
8. WHILE Advanced Mode is not active, THE Chart_System SHALL NOT display resistance or support indicators in any form (no lines, no info box)

### Requirement 8: OreX Advanced Theme

**User Story:** As an advanced player, I want a distinct UI presentation when Advanced Mode is active, so that the experience feels like a prestige layer with layouts tailored to the expanded feature set.

#### Acceptance Criteria

1. WHEN a player activates Advanced Mode, THE Theme_System SHALL apply the OreX_Advanced_Theme to all pages and UI components for that player
2. WHEN a player deactivates Advanced Mode, THE Theme_System SHALL revert all pages and UI components to the standard presentation
3. THE OreX_Advanced_Theme SHALL feature advanced-specific UI layouts accommodating the expanded trading controls (stop loss, take profit, shorting panels, resistance/support overlays)
4. THE OreX_Advanced_Theme SHALL replace the standard OreX logo with the OreX Advanced logo throughout the interface
5. THE Theme_System SHALL apply the presentation change without requiring a full page refresh (using htmx partial updates or CSS class toggling)

### Requirement 9: Leaderboard Indicator

**User Story:** As a player, I want to see which leaderboard players have Advanced Mode active, so that I can identify experienced and prestigious players.

#### Acceptance Criteria

1. WHILE a player has Advanced Mode active, THE Leaderboard_System SHALL render that player's username in red on the leaderboard
2. WHILE a player has Advanced Mode purchased but inactive, THE Leaderboard_System SHALL render that player's username in the standard color on the leaderboard
3. THE Leaderboard_System SHALL display the red indicator to all players viewing the leaderboard, regardless of their own Advanced Mode status

### Requirement 10: Account Reset Interaction

**User Story:** As a player who resets their account, I want clarity on how Advanced Mode status is affected, so that there are no surprises about my progression.

#### Acceptance Criteria

1. WHEN a player resets their account, THE Advanced_Mode_System SHALL revoke the purchased status and revert the player to an unpurchased, ineligible state
2. WHEN a player resets their account while Advanced Mode is active, THE Advanced_Mode_System SHALL deactivate Advanced Mode and remove all associated Stop_Loss and Take_Profit orders
3. WHEN a player resets their account, THE Advanced_Mode_System SHALL require the player to re-reach the Eligibility_Threshold and re-purchase Advanced Mode to regain access
