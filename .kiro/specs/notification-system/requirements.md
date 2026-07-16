# Requirements Document

## Introduction

The Notification System is a general-purpose in-app notification infrastructure for OreX that provides a shared message delivery layer used by multiple game features. It handles notification creation, persistent storage, a nav bar bell icon with unread count badge, a dropdown notification tray, and category-aware toast popups. The system is designed as simple, extensible infrastructure — other features call a single function to emit notifications, and the Notification System handles storage, display, and lifecycle management without knowledge of the emitting feature's business logic.

## Glossary

- **Notification_System**: The subsystem responsible for storing, displaying, pruning, and managing the lifecycle of in-app notifications for all players
- **Notification**: A single message record stored in the notifications table, containing a category, message text, optional action URL, read status, and timestamp
- **Notification_Bell**: A clickable icon element in the navigation bar that indicates the presence of unread notifications and opens the Notification_Tray
- **Unread_Badge**: A numeric badge displayed on the Notification_Bell showing the count of unread notifications for the current player
- **Notification_Tray**: A dropdown panel opened by clicking the Notification_Bell, displaying recent notifications in reverse chronological order
- **Toast**: A brief popup message displayed at a fixed position on the current page to alert the player of a new notification in real time
- **Category**: A TEXT field on a notification record identifying the source feature (e.g., "liquidation", "achievement", "advanced_mode", "daily_bonus", "market_event", "tutorial"), used for toast styling and icon selection
- **Action_URL**: An optional URL path stored on a notification that, when present, makes the notification clickable and navigates the player to the relevant page
- **Polling_Interval**: The frequency at which the client checks the server for new notifications via htmx polling
- **Notification_Cap**: Removed — no cap needed since acknowledged notifications are deleted immediately
- **Retention_Period**: The maximum age of an unacknowledged notification before automatic pruning (2 days)
- **create_notification**: The server-side function that other features call to emit a notification: `create_notification(user_id, category, message, action_url=None)`

## Requirements

### Requirement 1: Notification Data Model

**User Story:** As a developer, I want a well-defined data model for notifications, so that the system can store and query notification records reliably.

#### Acceptance Criteria

1. THE Notification_System SHALL store each notification with: id (INTEGER PRIMARY KEY), user_id (INTEGER NOT NULL), category (TEXT NOT NULL), message (TEXT NOT NULL), action_url (TEXT, nullable), is_read (INTEGER NOT NULL DEFAULT 0), created_at (TEXT NOT NULL DEFAULT current timestamp)
2. THE Notification_System SHALL maintain referential integrity between notifications and the users table using a foreign key constraint on user_id with CASCADE on delete
3. THE Notification_System SHALL create an index on user_id and is_read to support efficient unread count and tray queries
4. THE Notification_System SHALL create an index on user_id and created_at to support efficient ordering and pruning queries
5. THE Notification_System SHALL store category as a free-form TEXT field without enum constraints, allowing new categories to be added by other features without schema changes

### Requirement 2: Notification Creation API

**User Story:** As a developer building a game feature, I want a simple function to emit notifications, so that I can notify players without understanding the notification infrastructure internals.

#### Acceptance Criteria

1. THE Notification_System SHALL expose a `create_notification(user_id, category, message, action_url=None)` function that inserts a new notification record and returns the created notification ID
2. WHEN `create_notification` is called with a valid user_id, category, and message, THE Notification_System SHALL persist the notification with is_read set to 0 and created_at set to the current server timestamp
3. IF `create_notification` is called with an empty or whitespace-only message, THEN THE Notification_System SHALL reject the call and raise a ValueError
4. IF `create_notification` is called with a user_id that does not exist in the users table, THEN THE Notification_System SHALL reject the call and raise a ValueError
5. THE Notification_System SHALL accept any non-empty string as a valid category value

### Requirement 3: Notification Bell and Unread Badge

**User Story:** As a player, I want to see a notification bell in the navigation bar with an unread count, so that I know when new notifications are waiting.

#### Acceptance Criteria

1. WHILE a player is authenticated, THE Notification_Bell SHALL be displayed in the navigation bar adjacent to the profile pill element
2. WHILE a player has one or more unread notifications, THE Unread_Badge SHALL display the count of unread notifications on the Notification_Bell
3. WHILE a player has zero unread notifications, THE Unread_Badge SHALL be hidden (not displayed)
4. WHEN the unread count exceeds 9, THE Unread_Badge SHALL display "9+" instead of the exact count
5. THE Notification_Bell SHALL update the Unread_Badge count via htmx polling at the configured Polling_Interval without requiring a full page reload

### Requirement 4: Notification Tray

**User Story:** As a player, I want to click the notification bell to see my unread notifications, so that I can review pending messages and navigate to relevant pages.

#### Acceptance Criteria

1. WHEN a player clicks the Notification_Bell, THE Notification_Tray SHALL open as a dropdown panel displaying all unread notifications in reverse chronological order (newest first)
2. THE Notification_Tray SHALL display each notification with: a category-specific icon, the message text, and a relative timestamp (e.g., "2m ago", "1h ago")
3. WHEN a player clicks a notification that has an Action_URL, THE Notification_Tray SHALL navigate the player to the Action_URL page and delete the notification
4. WHEN a player clicks a notification that has no Action_URL, THE Notification_Tray SHALL delete the notification (removing it from the tray)
5. THE Notification_Tray SHALL provide a "Dismiss all" button that deletes all unread notifications for the player in a single action
6. WHEN the Notification_Tray is open and the player clicks outside of the tray, THE Notification_Tray SHALL close
7. THE Notification_Tray SHALL load its content via htmx partial request when opened, displaying current data without a full page reload
8. WHEN there are no unread notifications, THE Notification_Tray SHALL display an empty state message (e.g., "No new notifications")

### Requirement 5: Toast Notifications

**User Story:** As a player, I want new notifications to appear as brief toast popups on the current page, so that I am immediately aware of important events without checking the bell.

#### Acceptance Criteria

1. WHEN a new notification is detected by the client polling mechanism, THE Notification_System SHALL display a toast popup for each new notification
2. THE Notification_System SHALL display toasts in a fixed-position container in the top-right corner of the viewport, stacking vertically when multiple toasts are active
3. WHEN a notification has category "achievement", THE Notification_System SHALL display the toast with yellow styling and a persistence duration of 5 seconds
4. WHEN a notification has category "liquidation", THE Notification_System SHALL display the toast with red styling and a persistence duration of 5 seconds
5. WHEN a notification has a category other than "achievement" or "liquidation", THE Notification_System SHALL display the toast with default styling and a persistence duration of 3 seconds
6. WHEN a toast notification has an associated Action_URL, THE toast SHALL be clickable and navigate the player to the Action_URL when clicked
7. WHEN the persistence duration of a toast elapses, THE toast SHALL dismiss automatically with a fade-out animation
8. THE Notification_System SHALL render the toast container in base.html so that toasts appear on all pages without page-specific template changes

### Requirement 6: Polling and New Notification Detection

**User Story:** As a player, I want the notification system to check for new messages periodically, so that I receive timely updates without manual page refreshes.

#### Acceptance Criteria

1. THE Notification_System SHALL poll the server for new notifications using htmx polling at an interval of 30 seconds
2. WHEN the polling request returns new unread notifications that were not present in the previous poll response, THE Notification_System SHALL trigger toast display for each newly detected notification
3. WHEN the polling request returns an updated unread count, THE Notification_System SHALL update the Unread_Badge to reflect the current count
4. WHILE a player is not authenticated, THE Notification_System SHALL NOT perform any polling requests
5. THE Notification_System SHALL include a timestamp or notification ID watermark in each poll request so the server can identify which notifications are new since the last poll

### Requirement 7: Notification Pruning

**User Story:** As a game system, I want unacknowledged notifications to be automatically cleaned up after 2 days, so that the database does not grow unbounded with abandoned notifications.

#### Acceptance Criteria

1. THE Notification_System SHALL delete unread notifications older than 2 days (48 hours) regardless of category
2. THE Notification_System SHALL delete read notifications immediately upon being marked as read (no retention for acknowledged notifications)
3. THE Notification_System SHALL execute pruning checks when a new notification is created for a player, removing expired notifications in the same operation
4. THE Notification_System SHALL delete pruned notifications permanently (hard delete)

### Requirement 8: Notification Acknowledgment

**User Story:** As a player, I want to dismiss notifications individually or all at once, so that I can clear my tray and remove the unread badge.

#### Acceptance Criteria

1. WHEN a player dismisses a single notification (click or swipe), THE Notification_System SHALL delete that notification from the database and remove it from the tray via htmx partial response
2. WHEN a player activates "Dismiss all", THE Notification_System SHALL delete all notifications belonging to that player and update the Unread_Badge to hidden
3. THE Notification_System SHALL process dismissal operations without requiring a full page reload (using htmx partial updates)

### Requirement 9: Category-Based Toast Styling

**User Story:** As a player, I want notification toasts to be visually distinct based on their category, so that I can quickly assess the importance and type of each notification.

#### Acceptance Criteria

1. THE Notification_System SHALL apply a yellow background and a trophy/star icon to toasts with category "achievement"
2. THE Notification_System SHALL apply a red background and a warning/alert icon to toasts with category "liquidation"
3. THE Notification_System SHALL apply a default neutral background and a bell icon to toasts with any other category value
4. THE Notification_System SHALL determine toast styling solely from the category field, requiring no changes to the notification infrastructure when new categories are added (new categories receive default styling automatically)
5. THE Notification_System SHALL display a category-appropriate icon in the Notification_Tray for each notification, matching the icon used in the corresponding toast

### Requirement 10: Account Lifecycle Integration

**User Story:** As a game system, I want the notification system to properly handle account resets and deletions, so that notification data does not become orphaned or stale.

#### Acceptance Criteria

1. WHEN a player resets their account, THE Notification_System SHALL delete all notification records for that player
2. WHEN a player deletes their account, THE Notification_System SHALL delete all notification records for that player (handled by CASCADE foreign key constraint on user_id)
3. WHEN a player resets their account, THE Notification_System SHALL clear the notification state so that the Unread_Badge displays zero and the Notification_Tray is empty immediately after reset

### Requirement 11: Accessibility and Keyboard Navigation

**User Story:** As a player using assistive technology, I want the notification system to be accessible, so that I can interact with notifications using a keyboard and screen reader.

#### Acceptance Criteria

1. THE Notification_Bell SHALL have an aria-label attribute that includes the current unread count (e.g., "Notifications, 3 unread")
2. THE Notification_Tray SHALL be navigable with keyboard Tab and Enter keys, allowing players to open, read, and dismiss notifications without a mouse
3. WHEN a toast notification appears, THE Notification_System SHALL announce the toast content to screen readers using an ARIA live region with aria-live="polite"
4. THE Notification_Tray SHALL have role="menu" and each notification item SHALL have role="menuitem" for proper semantic structure
5. WHEN the Notification_Tray is open, THE Escape key SHALL close the tray and return focus to the Notification_Bell
