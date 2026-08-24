# Requirements Document

## Introduction

The Notification System is a general-purpose in-app notification infrastructure for OreX that provides a shared message delivery layer used by multiple game features. It handles notification creation, persistent storage, a full Inbox page with two-panel layout, category-aware toast popups, and a red unread indicator in the profile dropdown. The system is designed as simple, extensible infrastructure — other features call a single function to emit notifications, and the Notification System handles storage, display, and lifecycle management without knowledge of the emitting feature's business logic.

## Glossary

- **Notification_System**: The subsystem responsible for storing, displaying, and managing the lifecycle of in-app notifications for all players
- **Notification**: A single message record stored in the notifications table, containing a category, message text, optional action URL, read status, and timestamp
- **Inbox_Page**: A dedicated full page at `/inbox` displaying all notifications in a two-panel layout (list + detail)
- **Inbox_List**: The left panel of the Inbox page showing notification entries with filter tabs
- **Inbox_Detail**: The right panel of the Inbox page showing expanded content for the selected notification
- **Unread_Dot**: A small red dot indicator displayed on the Inbox icon in the profile dropdown when unread notifications exist
- **Profile_Dropdown**: The dropdown menu opened by clicking the avatar button in the nav bar, redesigned with an icon row for quick access
- **Toast**: A brief popup message displayed at a fixed position on the current page to alert the player of a new notification in real time
- **Category**: A TEXT field on a notification record identifying the source feature (e.g., "liquidation", "achievement"), used for toast styling and detail panel content
- **Action_URL**: An optional URL path stored on a notification that provides a link to the relevant page
- **Polling_Interval**: The frequency (20 seconds) at which the client checks the server for new notifications
- **create_notification**: The server-side function that other features call to emit a notification: `create_notification(user_id, category, message, action_url=None)`

## Requirements

### Requirement 1: Notification Data Model

**User Story:** As a developer, I want a well-defined data model for notifications, so that the system can store and query notification records reliably.

#### Acceptance Criteria

1. THE Notification_System SHALL store each notification with: id (INTEGER PRIMARY KEY), user_id (INTEGER NOT NULL), category (TEXT NOT NULL), message (TEXT NOT NULL), action_url (TEXT, nullable), is_read (INTEGER NOT NULL DEFAULT 0), created_at (TEXT NOT NULL DEFAULT current timestamp)
2. THE Notification_System SHALL maintain referential integrity between notifications and the users table using a foreign key constraint on user_id with CASCADE on delete
3. THE Notification_System SHALL create an index on (user_id, is_read) to support efficient unread checks and filtered queries
4. THE Notification_System SHALL create an index on (user_id, id DESC) to support efficient polling and ordering queries
5. THE Notification_System SHALL store category as a free-form TEXT field without enum constraints, allowing new categories to be added by other features without schema changes

### Requirement 2: Notification Creation API

**User Story:** As a developer building a game feature, I want a simple function to emit notifications, so that I can notify players without understanding the notification infrastructure internals.

#### Acceptance Criteria

1. THE Notification_System SHALL expose a `create_notification(user_id, category, message, action_url=None)` function that inserts a new notification record and returns the created notification ID
2. WHEN `create_notification` is called with a valid user_id, category, and message, THE Notification_System SHALL persist the notification with is_read set to 0 and created_at set to the current server timestamp
3. IF `create_notification` is called with an empty or whitespace-only message, THEN THE Notification_System SHALL reject the call and raise a ValueError
4. IF `create_notification` is called with a user_id that does not exist in the users table, THEN THE Notification_System SHALL reject the call and raise a ValueError
5. THE Notification_System SHALL accept any non-empty string as a valid category value

### Requirement 3: Unread Indicator (Red Dot)

**User Story:** As a player, I want to see a visual indicator when I have unread notifications, so that I know to check my inbox.

#### Acceptance Criteria

1. WHILE a player is authenticated, THE Profile_Dropdown SHALL include an Inbox icon in the icon row
2. WHILE a player has one or more unread notifications, THE Unread_Dot SHALL be displayed on the Inbox icon
3. WHILE a player has zero unread notifications, THE Unread_Dot SHALL be hidden (not displayed)
4. THE Notification_System SHALL poll for unread status every 20 seconds and toggle the Unread_Dot without requiring a full page reload
5. THE Unread_Dot SHALL be a simple red circle with no number

### Requirement 4: Inbox Page

**User Story:** As a player, I want a full inbox page to view, read, and manage all my notifications in one place.

#### Acceptance Criteria

1. WHEN a player navigates to `/inbox`, THE Inbox_Page SHALL display all notifications in a two-panel layout: Inbox_List on the left and Inbox_Detail on the right
2. THE Inbox_List SHALL display notifications in reverse chronological order (newest first) with unread entries appearing bold/bright and read entries appearing greyed
3. THE Inbox_List SHALL provide filter tabs: "All", "Read", "Unread" that filter the displayed notifications accordingly
4. THE Inbox_List SHALL provide a "Mark all as read" button that marks all notifications as read in a single action
5. WHEN a player clicks a notification in the Inbox_List, THE notification SHALL be automatically marked as read and the Inbox_Detail panel SHALL display the expanded content for that notification
6. THE Inbox_Detail panel SHALL display a template-based layout (similar to an email view) with category-specific expanded content
7. WHEN no notification is selected, THE Inbox_Detail panel SHALL display an empty/placeholder state
8. WHEN there are no notifications, THE Inbox_List SHALL display an empty state message

### Requirement 5: Toast Notifications

**User Story:** As a player, I want new notifications to appear as brief toast popups on the current page, so that I am immediately aware of important events without navigating to the inbox.

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

1. THE Notification_System SHALL poll the server for new notifications at an interval of 20 seconds
2. WHEN the polling request returns new unread notifications that were not present in the previous poll response, THE Notification_System SHALL trigger toast display for each newly detected notification
3. WHEN the polling request returns an updated unread status, THE Notification_System SHALL update the Unread_Dot accordingly
4. WHILE a player is not authenticated, THE Notification_System SHALL NOT perform any polling requests
5. THE Notification_System SHALL include a notification ID watermark in each poll request so the server can identify which notifications are new since the last poll

### Requirement 7: Notification Deletion

**User Story:** As a player, I want to delete notifications from my inbox, so that I can keep my notification list clean.

#### Acceptance Criteria

1. THE Inbox_List SHALL display a delete (bin) icon on each notification entry when the player hovers over it
2. WHEN a player clicks the delete icon on a notification, THE Notification_System SHALL permanently delete that notification from the database
3. WHEN a notification is deleted, THE Inbox_List SHALL update to remove the entry without a full page reload (via htmx partial update)
4. THE Notification_System SHALL only allow a player to delete their own notifications

### Requirement 8: Notification Read Status

**User Story:** As a player, I want notifications to be visually distinguished by read status, so that I can quickly identify new messages.

#### Acceptance Criteria

1. WHEN a player clicks a notification in the Inbox_List, THE Notification_System SHALL mark that notification as read (is_read=1)
2. THE Inbox_List SHALL display unread notifications with bold/bright styling and read notifications with greyed/muted styling
3. WHEN a player clicks "Mark all as read", THE Notification_System SHALL set is_read=1 for all notifications belonging to that player
4. THE Notification_System SHALL process read status updates without requiring a full page reload

### Requirement 9: Category-Based Styling

**User Story:** As a player, I want notification toasts and inbox entries to be visually distinct based on their category, so that I can quickly assess the type of each notification.

#### Acceptance Criteria

1. THE Notification_System SHALL apply a yellow background and a trophy/star icon to toasts with category "achievement"
2. THE Notification_System SHALL apply a red background and a warning/alert icon to toasts with category "liquidation"
3. THE Notification_System SHALL apply a default neutral background and a bell icon to toasts with any other category value
4. THE Notification_System SHALL determine styling solely from the category field, requiring no changes to the notification infrastructure when new categories are added
5. THE Inbox_List SHALL display a category-appropriate icon for each notification entry

### Requirement 10: Account Lifecycle Integration

**User Story:** As a game system, I want the notification system to properly handle account resets and deletions, so that notification data does not become orphaned or stale.

#### Acceptance Criteria

1. WHEN a player resets their account, THE Notification_System SHALL delete all notification records for that player
2. WHEN a player deletes their account, THE Notification_System SHALL delete all notification records for that player (handled by CASCADE foreign key constraint on user_id)
3. WHEN a player resets their account, THE Notification_System SHALL clear the notification state so that the Unread_Dot is hidden and the Inbox_Page is empty immediately after reset

### Requirement 11: Accessibility

**User Story:** As a player using assistive technology, I want the notification system to be accessible, so that I can interact with notifications using a keyboard and screen reader.

#### Acceptance Criteria

1. THE Inbox icon in the Profile_Dropdown SHALL have an aria-label indicating its purpose (e.g., "Inbox") and unread state
2. THE Inbox_Page SHALL be navigable with keyboard Tab and Enter keys
3. WHEN a toast notification appears, THE Notification_System SHALL announce the toast content to screen readers using an ARIA live region with aria-live="polite"
4. THE Inbox_List items SHALL have appropriate ARIA roles for list semantics
5. THE delete button on each notification SHALL have an aria-label (e.g., "Delete notification")

### Requirement 12: Profile Dropdown Redesign

**User Story:** As a player, I want the profile dropdown to be compact and provide quick icon-based access to key pages, so that navigation is faster.

#### Acceptance Criteria

1. THE Profile_Dropdown SHALL display a row of icon buttons at the top: Portfolio, Inbox, History
2. THE icon buttons SHALL navigate directly to their respective pages when clicked
3. THE Profile_Dropdown SHALL display text links below the icon row: Profile, Settings
4. THE Profile_Dropdown SHALL display a "Logout" link separated at the bottom with red/danger styling
5. THE Inbox icon SHALL display the Unread_Dot when unread notifications exist
6. THE icon row SHALL use Material Design icons (with placeholder icons during development)
