# Requirements Document

## Introduction

The Profile Page is a dedicated player identity hub for OreX that consolidates avatar customization, gameplay statistics, the daily login bonus system, and achievement display into a single page. It introduces a custom profile picture (PFP) upload system with client-side cropping, a 3-day cycling login bonus mechanic, peak net worth tracking, and a reorganized navigation that relocates the FAQ into a "Help" section accessible from the profile menu. The page serves as the primary "player card" — a place to view stats, collect rewards, and showcase progress.

## Glossary

- **Profile_Page**: A dedicated authenticated page at `/profile` displaying a player's avatar, stats, daily bonus status, and earned achievements
- **Profile_Picture**: A square avatar image uploaded by a player, stored on the server and displayed on the Profile_Page and Leaderboard
- **Cropper_Widget**: A client-side image cropping interface powered by Cropper.js that constrains the selection to a 1:1 aspect ratio before upload
- **Default_Avatar**: A system-provided generic avatar image displayed for players who have not uploaded a custom Profile_Picture
- **Bot_Icon**: A distinct system icon displayed on the Leaderboard in place of a Profile_Picture for bot accounts
- **Daily_Login_Bonus**: A 3-day cycling reward system awarding $1,000 on Day 1, $10,000 on Day 2, and $100,000 on Day 3, resetting to Day 1 after collection on Day 3
- **Bonus_Cycle_Day**: The player's current position (1, 2, or 3) within the Daily_Login_Bonus cycle
- **Peak_Net_Worth**: The highest Net_Worth value a player has ever achieved, recorded and updated by the Tick_Engine
- **Net_Worth**: The sum of a player's Free_Cash balance and the current market value of all ore holdings (balance + SUM(holdings.quantity × ore.current_price))
- **Play_Time**: The cumulative duration in minutes a player has spent with an active session (tracked by the Achievement_System)
- **Login_Streak**: The count of consecutive calendar days a player has authenticated (tracked by the Achievement_System)
- **Trade_Count**: The total number of completed trade transactions recorded for a player across all time
- **Profile_Menu**: A navigation element (dropdown or sidebar section) providing access to the Profile_Page, Settings, Help, and logout
- **Help_Page**: The existing FAQ/help content, relocated to be accessible from the Profile_Menu instead of its current standalone navigation position
- **Tick_Engine**: The background market engine that updates ore prices every 20–30 seconds

## Requirements

### Requirement 1: Profile Page Route and Navigation

**User Story:** As a player, I want a dedicated profile page accessible from the existing profile dropdown, so that I have a central place to view my identity and stats.

#### Acceptance Criteria

1. THE Profile_Page SHALL be accessible at the `/profile` URL path for authenticated players
2. WHEN an unauthenticated user attempts to access the Profile_Page, THE Profile_Page SHALL redirect the user to the login page
3. THE existing profile dropdown button in the navigation bar SHALL include a "Profile" link that navigates to the Profile_Page
4. THE Profile_Page SHALL NOT have its own dedicated tab button in the primary navigation bar (it is accessed via the existing profile dropdown alongside Settings, Help, and logout)
5. THE Help_Page SHALL be accessible from the profile dropdown at its existing `/help` URL path (relocated from standalone navigation)

### Requirement 2: Profile Picture Upload

**User Story:** As a player, I want to upload and crop a custom avatar, so that I have a personalized identity in the game.

#### Acceptance Criteria

1. THE Profile_Page SHALL display the player's current Profile_Picture or the Default_Avatar if no custom image has been uploaded
2. WHEN a player initiates a Profile_Picture upload, THE Cropper_Widget SHALL open and allow the player to select, pan, zoom, and crop the image to a 1:1 square aspect ratio
3. WHEN a player confirms the cropped image, THE Profile_Page SHALL upload the image to the server and replace the current avatar
4. THE Profile_Page SHALL accept image uploads in PNG, JPEG, and WebP formats only
5. IF a player uploads a file that is not PNG, JPEG, or WebP format, THEN THE Profile_Page SHALL reject the upload and display a format error message
6. THE Profile_Page SHALL reject uploaded image files larger than 2 MB before cropping and display a file size error message
7. THE Profile_Page SHALL store the final cropped image resized to 200×200 pixels on the server
8. THE Profile_Page SHALL update the displayed avatar without requiring a full page reload (using htmx partial update)

### Requirement 3: Profile Picture Display on Leaderboard

**User Story:** As a player, I want to see profile pictures on the leaderboard, so that I can visually identify other players.

#### Acceptance Criteria

1. THE Leaderboard SHALL display each human player's Profile_Picture (or Default_Avatar) next to their username
2. THE Leaderboard SHALL display the Bot_Icon next to bot account usernames instead of a Profile_Picture
3. THE Leaderboard SHALL render Profile_Pictures at a consistent thumbnail size (32×32 pixels)

### Requirement 4: Peak Net Worth Tracking

**User Story:** As a player, I want the game to track my highest-ever net worth, so that I can see my all-time best performance on my profile.

#### Acceptance Criteria

1. THE Tick_Engine SHALL calculate each player's current Net_Worth after every price update tick
2. WHEN a player's current Net_Worth exceeds their stored Peak_Net_Worth, THE Tick_Engine SHALL update the stored Peak_Net_Worth to the current value
3. THE Profile_Page SHALL display the player's Peak_Net_Worth as a formatted currency value
4. WHEN a player resets their account, THE Profile_Page system SHALL reset Peak_Net_Worth to the default starting balance ($10,000)
5. THE Peak_Net_Worth SHALL be initialized to the player's starting balance ($10,000) upon account creation

### Requirement 5: Player Statistics Display

**User Story:** As a player, I want to see my key stats on one page, so that I can track my progress and engagement at a glance.

#### Acceptance Criteria

1. THE Profile_Page SHALL display the following statistics for the authenticated player: Play_Time (formatted as hours and minutes), Login_Streak (current consecutive days), Peak_Net_Worth (formatted currency), Trade_Count (total trades), and account creation date
2. THE Profile_Page SHALL display the player's username prominently at the top of the page
3. THE Profile_Page SHALL organize statistics in a clearly labeled section with readable formatting
4. THE Profile_Page SHALL retrieve Play_Time and Login_Streak values from the existing fields tracked by the Achievement_System

### Requirement 6: Daily Login Bonus (One-Time 3-Day Welcome Reward)

**User Story:** As a new player, I want to collect a one-time 3-day login bonus across any 3 login days, so that I receive a starting boost regardless of how frequently I play.

#### Acceptance Criteria

1. THE Daily_Login_Bonus SHALL award $1,000 on Bonus_Cycle_Day 1, $10,000 on Bonus_Cycle_Day 2, and $100,000 on Bonus_Cycle_Day 3
2. WHEN a player logs in on a new calendar date and has not yet collected a bonus for the current Bonus_Cycle_Day, THE Profile_Page SHALL present a collectible bonus for that day
3. WHEN a player collects the daily bonus, THE Daily_Login_Bonus SHALL add the awarded amount to the player's Free_Cash balance and advance the Bonus_Cycle_Day by 1
4. THE Daily_Login_Bonus SHALL allow only one bonus collection per calendar date — a player cannot collect Day 1 and Day 2 on the same date
5. THE Daily_Login_Bonus SHALL NOT reset the Bonus_Cycle_Day under any circumstances other than account reset — missing days between logins does not affect progress
6. WHEN a player collects the bonus on Bonus_Cycle_Day 3, THE Daily_Login_Bonus SHALL mark the entire bonus cycle as permanently completed for that player
7. WHILE the bonus cycle is not yet completed, THE Profile_Page SHALL display the current Bonus_Cycle_Day, the reward amount available, and whether the bonus has already been collected today
8. WHILE the bonus cycle is not yet completed, THE Profile_Page SHALL display a visual indicator showing all 3 days of the cycle with completed, current, and upcoming states
9. WHEN the bonus cycle is permanently completed, THE Profile_Page SHALL hide the Daily_Login_Bonus section entirely (the section disappears after all 3 days are collected)
10. WHEN a player collects the bonus, THE Profile_Page SHALL update the bonus display without requiring a full page reload (using htmx partial update)

### Requirement 7: Daily Login Bonus Data Model

**User Story:** As a developer, I want a clear data model for the daily bonus system, so that bonus state is persisted reliably across sessions.

#### Acceptance Criteria

1. THE Daily_Login_Bonus SHALL store the following fields per player: bonus_cycle_day (INTEGER, 1–4 where 4 means completed), last_bonus_collected_date (TEXT, ISO 8601 date, nullable), stored on the users table
2. THE Daily_Login_Bonus SHALL initialize bonus_cycle_day to 1 and last_bonus_collected_date to NULL for new accounts
3. WHEN a player collects the Day 3 bonus, THE Daily_Login_Bonus SHALL set bonus_cycle_day to 4, permanently marking the cycle as complete
4. WHEN a player resets their account, THE Daily_Login_Bonus SHALL reset bonus_cycle_day to 1 and last_bonus_collected_date to NULL (allowing the player to earn the welcome bonus again)
5. THE Daily_Login_Bonus SHALL enforce that a player can collect at most one bonus per calendar date by comparing the current date against last_bonus_collected_date
6. WHILE bonus_cycle_day equals 4, THE Daily_Login_Bonus SHALL not present or allow any further bonus collection

### Requirement 8: Achievement Display on Profile

**User Story:** As a player, I want to see my earned achievements on my profile, so that I can showcase my accomplishments.

#### Acceptance Criteria

1. THE Profile_Page SHALL display a section showing all nine achievements with their earned or locked status
2. WHILE an achievement has been earned, THE Profile_Page SHALL display the achievement badge in an unlocked visual state with the earned date
3. WHILE an achievement has not been earned, THE Profile_Page SHALL display the achievement badge in a locked (greyed-out) visual state with the achievement name visible
4. THE Profile_Page SHALL retrieve achievement data from the Achievement_System data model (user_achievements table)
5. THE Profile_Page SHALL display achievements in a grid or row layout that accommodates all nine badges without scrolling on standard desktop viewports

### Requirement 9: Profile Picture Storage and Serving

**User Story:** As a developer, I want profile pictures stored and served via an abstraction layer, so that the system can use local file storage in development and Oracle Object Storage in production without code changes.

#### Acceptance Criteria

1. THE Profile_Page system SHALL store uploaded profile pictures using a storage abstraction that supports both local filesystem and Oracle Object Storage backends
2. THE Profile_Page system SHALL name stored files using the player's user ID to ensure uniqueness (e.g., `{user_id}.png`)
3. WHEN a player uploads a new Profile_Picture, THE Profile_Page system SHALL overwrite the previous file for that player in the active storage backend
4. THE Profile_Page system SHALL store the avatar URL or path reference on the users table so the application can resolve the image location regardless of storage backend
5. THE Profile_Page system SHALL serve avatar images with appropriate cache headers to minimize repeated downloads
6. THE Profile_Page system SHALL select the storage backend (local or Oracle Object Storage) via application configuration, defaulting to local filesystem for development
7. WHEN using local storage, THE Profile_Page system SHALL store files in `static/uploads/avatars/`
8. WHEN using Oracle Object Storage, THE Profile_Page system SHALL store files in a configured bucket using the Oracle Cloud Infrastructure SDK, compatible with the Oracle Cloud Free Tier

### Requirement 10: Account Reset Interaction

**User Story:** As a player who resets their account, I want clarity on which profile data is preserved and which is cleared, so that there are no surprises.

#### Acceptance Criteria

1. WHEN a player resets their account, THE Profile_Page system SHALL retain the player's Profile_Picture
2. WHEN a player resets their account, THE Profile_Page system SHALL reset Peak_Net_Worth to the default starting balance ($10,000)
3. WHEN a player resets their account, THE Profile_Page system SHALL reset the Daily_Login_Bonus state (bonus_cycle_day to 1, last_bonus_collected_date to NULL)
4. WHEN a player resets their account, THE Profile_Page system SHALL retain the player's account creation date
5. WHEN a player deletes their account, THE Profile_Page system SHALL delete the associated Profile_Picture file from the server
