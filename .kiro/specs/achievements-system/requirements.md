# Requirements Document

## Introduction

The Achievements System is a progression and engagement layer for OreX that rewards players with badges for reaching milestones across trading performance, account longevity, and gameplay engagement. Nine distinct achievements track net worth thresholds, trading volume, login streaks, play time, leaderboard ranking, short selling success, and account reset events. Two premium achievements (Multimillionaire and Completionist) unlock a cosmetic "Money and Gold" theme as an additional reward. The system requires new infrastructure for tracking play time and login streaks, while integrating with existing transaction records, leaderboard calculations, account reset logic, and the separately-spec'd Advanced Mode and Shorting System features.

## Glossary

- **Achievement**: A named milestone badge that a player earns by satisfying a specific condition, persisted permanently on the player's account once awarded
- **Achievement_System**: The subsystem responsible for evaluating achievement conditions, awarding badges, and managing theme unlock state
- **Net_Worth**: The sum of a player's Free_Cash balance, the current market value of all long ore holdings, and short position equity (Locked_Collateral minus Short_Value for each active short position)
- **Free_Cash**: The player's liquid wallet balance (the existing `balance` field on the users table)
- **Play_Time**: The cumulative duration in minutes a player has spent with an active authenticated session in the application
- **Login_Streak**: The count of consecutive calendar days on which a player has authenticated at least once
- **Trade_Count**: The total number of completed trade transactions (buy, sell, short_open, short_close, short_liquidated) recorded for a player across all time, including archived transactions
- **Leaderboard_Rank**: A player's position on the global leaderboard ordered by Net_Worth descending, where rank 1 is the highest Net_Worth
- **Profitable_Short**: A short position closed (voluntarily or via Take_Profit trigger) where the profit amount is greater than zero (the player received more Free_Cash back than the original collateral deducted at open)
- **Money_Theme**: A cosmetic visual theme featuring money-inspired styling (green/cash aesthetic), unlocked by earning the Multimillionaire achievement
- **Gold_Theme**: A cosmetic visual theme featuring gold-inspired styling (gold/prestige aesthetic), unlocked by earning the Completionist achievement
- **Advanced_Mode**: The separately-spec'd prestige feature tier unlocked at $100,000 net worth; referenced by the "The Big Short" achievement as a prerequisite
- **Shorting_System**: The separately-spec'd trading feature allowing players to profit from declining ore prices; referenced by the "The Big Short" achievement condition
- **Account_Reset**: The existing `reset_account()` operation that restores default balance, clears holdings, and archives transactions

## Requirements

### Requirement 1: Achievement Data Model

**User Story:** As a developer, I want a well-defined data model for achievements, so that the system can track which achievements each player has earned and when.

#### Acceptance Criteria

1. THE Achievement_System SHALL store each earned achievement with: user_id (INTEGER NOT NULL), achievement_key (TEXT NOT NULL), earned_at (TEXT NOT NULL, ISO 8601 timestamp)
2. THE Achievement_System SHALL enforce a unique constraint on the combination of user_id and achievement_key, preventing duplicate awards of the same achievement
3. THE Achievement_System SHALL define exactly nine achievement_key values: "millionaire", "multimillionaire", "the_big_short", "dedicated", "day_trader", "budding_enthusiast", "completionist", "tragedy", "best_of_the_rest"
4. THE Achievement_System SHALL maintain referential integrity between earned achievements and the users table using a foreign key constraint on user_id with CASCADE on delete

### Requirement 2: Play Time Tracking

**User Story:** As a player, I want the game to track my cumulative play time, so that I can earn the "Budding Enthusiast" achievement.

#### Acceptance Criteria

1. THE Achievement_System SHALL track cumulative Play_Time for each player in minutes, stored as an integer field on the users table
2. WHEN a player has an active authenticated session, THE Achievement_System SHALL increment the player's Play_Time by 1 for each elapsed minute of session activity
3. WHEN a player's session ends (logout or session expiry), THE Achievement_System SHALL persist the accumulated Play_Time up to the point of session termination
4. IF a player has multiple browser tabs open simultaneously, THEN THE Achievement_System SHALL count the overlapping duration only once (no double-counting of concurrent sessions)
5. THE Achievement_System SHALL persist Play_Time across browser sessions so that cumulative time is never lost

### Requirement 3: Login Streak Tracking

**User Story:** As a player, I want the game to track my consecutive login days, so that I can earn the "Dedicated" achievement.

#### Acceptance Criteria

1. THE Achievement_System SHALL store the current Login_Streak count and the date of the last streak-qualifying login for each player
2. WHEN a player authenticates and the current calendar date (server local time) differs from the player's last streak-qualifying login date by exactly one day, THE Achievement_System SHALL increment the Login_Streak by 1 and update the last streak-qualifying login date
3. WHEN a player authenticates and the current calendar date equals the player's last streak-qualifying login date, THE Achievement_System SHALL maintain the current Login_Streak without modification
4. WHEN a player authenticates and the current calendar date differs from the player's last streak-qualifying login date by more than one day, THE Achievement_System SHALL reset the Login_Streak to 1 and update the last streak-qualifying login date
5. WHEN a player authenticates for the first time (no prior streak-qualifying login date exists), THE Achievement_System SHALL initialize the Login_Streak to 1

### Requirement 4: Millionaire Achievement

**User Story:** As a player, I want to earn the "Millionaire" badge when my net worth reaches $1,000,000, so that I receive recognition for growing my portfolio.

#### Acceptance Criteria

1. WHEN a player's Net_Worth reaches or exceeds $1,000,000, THE Achievement_System SHALL award the "millionaire" achievement to the player
2. THE Achievement_System SHALL evaluate the Millionaire condition after any event that changes Net_Worth: trade execution, price tick update, or short position state change
3. WHEN the "millionaire" achievement is awarded, THE Achievement_System SHALL persist the award permanently regardless of subsequent Net_Worth changes

### Requirement 5: Multimillionaire Achievement

**User Story:** As a player, I want to earn the "Multimillionaire" badge when my net worth reaches $10,000,000, so that I receive recognition for exceptional portfolio growth and unlock the Money theme.

#### Acceptance Criteria

1. WHEN a player's Net_Worth reaches or exceeds $10,000,000, THE Achievement_System SHALL award the "multimillionaire" achievement to the player
2. THE Achievement_System SHALL evaluate the Multimillionaire condition after any event that changes Net_Worth: trade execution, price tick update, or short position state change
3. WHEN the "multimillionaire" achievement is awarded, THE Achievement_System SHALL persist the award permanently regardless of subsequent Net_Worth changes
4. WHEN the "multimillionaire" achievement is awarded, THE Achievement_System SHALL unlock the Money_Theme for that player

### Requirement 6: The Big Short Achievement

**User Story:** As an advanced player, I want to earn "The Big Short" badge when I complete a profitable short, so that I receive recognition for mastering the shorting mechanic.

#### Acceptance Criteria

1. WHEN a player closes a short position with a profit amount greater than zero, THE Achievement_System SHALL award the "the_big_short" achievement to the player
2. THE Achievement_System SHALL only evaluate the "the_big_short" condition for players who have Advanced_Mode active at the time of the short close
3. THE Achievement_System SHALL recognize a Profitable_Short from both voluntary close and Take_Profit trigger close events, but not from forced liquidation events
4. WHEN the "the_big_short" achievement is awarded, THE Achievement_System SHALL persist the award permanently regardless of subsequent Advanced_Mode status changes

### Requirement 7: Dedicated Achievement

**User Story:** As a player, I want to earn the "Dedicated" badge after logging in for 3 consecutive days, so that I receive recognition for consistent engagement.

#### Acceptance Criteria

1. WHEN a player's Login_Streak reaches or exceeds 3, THE Achievement_System SHALL award the "dedicated" achievement to the player
2. THE Achievement_System SHALL evaluate the Dedicated condition immediately after updating the Login_Streak during authentication
3. WHEN the "dedicated" achievement is awarded, THE Achievement_System SHALL persist the award permanently regardless of subsequent streak resets

### Requirement 8: Day Trader Achievement

**User Story:** As a player, I want to earn the "Day Trader" badge after completing 100 trades, so that I receive recognition for active market participation.

#### Acceptance Criteria

1. WHEN a player's Trade_Count reaches or exceeds 100, THE Achievement_System SHALL award the "day_trader" achievement to the player
2. THE Achievement_System SHALL count all trade transaction types toward Trade_Count: buy, sell, short_open, short_close, and short_liquidated
3. THE Achievement_System SHALL include archived transactions in the Trade_Count so that account resets do not erase trade history progress toward this achievement
4. THE Achievement_System SHALL evaluate the Day Trader condition after each completed trade transaction is recorded

### Requirement 9: Budding Enthusiast Achievement

**User Story:** As a player, I want to earn the "Budding Enthusiast" badge after spending 20 minutes playing, so that I receive recognition for investing time in the game.

#### Acceptance Criteria

1. WHEN a player's cumulative Play_Time reaches or exceeds 20 minutes, THE Achievement_System SHALL award the "budding_enthusiast" achievement to the player
2. THE Achievement_System SHALL evaluate the Budding Enthusiast condition each time Play_Time is incremented
3. WHEN the "budding_enthusiast" achievement is awarded, THE Achievement_System SHALL persist the award permanently

### Requirement 10: Completionist Achievement

**User Story:** As a player, I want to earn the "Completionist" badge after earning all other 8 achievements, so that I receive recognition for full mastery and unlock the Gold theme.

#### Acceptance Criteria

1. WHEN a player has earned all eight other achievements ("millionaire", "multimillionaire", "the_big_short", "dedicated", "day_trader", "budding_enthusiast", "tragedy", "best_of_the_rest"), THE Achievement_System SHALL award the "completionist" achievement to the player
2. THE Achievement_System SHALL evaluate the Completionist condition each time any other achievement is awarded to the player
3. WHEN the "completionist" achievement is awarded, THE Achievement_System SHALL unlock the Gold_Theme for that player
4. WHEN the "completionist" achievement is awarded, THE Achievement_System SHALL persist the award permanently

### Requirement 11: Tragedy Achievement

**User Story:** As a player, I want to earn the "Tragedy" badge when I reset my account after my balance drops below $10,000, so that the game acknowledges my misfortune with dark humor.

#### Acceptance Criteria

1. WHEN a player triggers an Account_Reset and the player's Net_Worth at the time of reset is below $10,000, THE Achievement_System SHALL award the "tragedy" achievement to the player
2. THE Achievement_System SHALL evaluate the Tragedy condition immediately before the Account_Reset operation clears account data
3. IF a player triggers an Account_Reset with a Net_Worth at or above $10,000, THEN THE Achievement_System SHALL NOT award the "tragedy" achievement
4. WHEN the "tragedy" achievement is awarded, THE Achievement_System SHALL persist the award permanently so it survives the account reset

### Requirement 12: Best of the Rest Achievement

**User Story:** As a player, I want to earn the "Best of the Rest" badge when I reach rank 1 on the leaderboard, so that I receive recognition for outperforming all other players.

#### Acceptance Criteria

1. WHEN a player's Leaderboard_Rank equals 1, THE Achievement_System SHALL award the "best_of_the_rest" achievement to the player
2. THE Achievement_System SHALL evaluate the Best of the Rest condition after any event that may change leaderboard rankings: trade execution, price tick update, or short position state change
3. WHEN the "best_of_the_rest" achievement is awarded, THE Achievement_System SHALL persist the award permanently regardless of subsequent ranking changes
4. IF multiple players are tied for the highest Net_Worth, THEN THE Achievement_System SHALL award the achievement to all tied players

### Requirement 13: Achievement Theme Unlocks

**User Story:** As a player who earns Multimillionaire or Completionist, I want to unlock a cosmetic theme, so that I receive a visible prestige reward.

#### Acceptance Criteria

1. WHEN a player earns the "multimillionaire" achievement, THE Achievement_System SHALL unlock the Money_Theme for that player
2. WHEN a player earns the "completionist" achievement, THE Achievement_System SHALL unlock the Gold_Theme for that player
3. WHEN either theme is unlocked, THE Achievement_System SHALL make it available as a selectable option in the player's theme settings
4. THE Achievement_System SHALL persist theme unlocks permanently once granted, independent of Net_Worth or achievement display status
5. THE Money_Theme and Gold_Theme SHALL apply cosmetic visual changes (color palette and decorative styling) without altering any functional UI layout or trading mechanics
6. THE Money_Theme and Gold_Theme SHALL coexist independently with the OreX Advanced functional UI changes (logo swap and advanced layout); a player may have a cosmetic theme active alongside Advanced Mode since they operate on different layers

### Requirement 14: Achievement Display

**User Story:** As a player, I want to view my earned achievements, so that I can track my progress and show off my accomplishments.

#### Acceptance Criteria

1. THE Achievement_System SHALL provide a display of all nine achievements showing earned status and earned date for each
2. WHILE an achievement has not been earned by a player, THE Achievement_System SHALL display the achievement in a locked visual state with its name and earning condition visible
3. WHILE an achievement has been earned by a player, THE Achievement_System SHALL display the achievement in an unlocked visual state with the earned_at date
4. THE Achievement_System SHALL display achievement progress indicators for quantitative achievements: current Trade_Count toward 100, current Play_Time toward 20 minutes, current Login_Streak toward 3 days, and current Net_Worth toward $1,000,000 and $10,000,000

### Requirement 15: Achievement Notification

**User Story:** As a player, I want to be notified when I earn an achievement, so that I experience a moment of celebration and awareness.

#### Acceptance Criteria

1. WHEN an achievement is awarded to a player, THE Achievement_System SHALL display a yellow toast notification to the player indicating the achievement name and a brief description
2. WHEN the awarded achievement unlocks the Money_Theme or Gold_Theme, THE Achievement_System SHALL include mention of the theme unlock in the notification
3. THE Achievement_System SHALL deliver the notification within the current page session without requiring a full page reload (using htmx partial updates or equivalent in-page mechanism)
4. THE achievement toast notification SHALL persist on screen longer than standard notifications and SHALL be clickable, navigating the player to the achievements page when clicked

### Requirement 16: Achievement Persistence Across Account Reset

**User Story:** As a player who resets their account, I want to retain my earned achievements, so that irreversible accomplishments are not lost.

#### Acceptance Criteria

1. WHEN a player resets their account, THE Achievement_System SHALL retain all previously earned achievements for that player
2. WHEN a player resets their account, THE Achievement_System SHALL reset Play_Time to zero
3. WHEN a player resets their account, THE Achievement_System SHALL reset Login_Streak to zero
4. WHEN a player resets their account, THE Achievement_System SHALL retain the Money_Theme and Gold_Theme unlocks if previously earned
5. WHEN a player deletes their account, THE Achievement_System SHALL permanently delete all achievement records for that player (handled by CASCADE foreign key constraint)
