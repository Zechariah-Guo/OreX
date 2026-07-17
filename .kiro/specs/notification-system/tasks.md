# Implementation Plan: Notification System

## Overview

Implement the in-app Notification System for OreX. This proceeds bottom-up: schema → data layer functions → blueprint routes → context processor → templates (bell, tray, toast) → client-side polling JS → CSS → account lifecycle integration. Each step builds incrementally so the feature is testable at every stage.

## Tasks

- [ ] 1. Database schema and migration
  - [ ] 1.1 Add notifications table and indexes to `src/schema.sql`
    - Create `notifications` table with columns: id (INTEGER PRIMARY KEY), user_id (INTEGER NOT NULL), category (TEXT NOT NULL), message (TEXT NOT NULL), action_url (TEXT), created_at (TEXT NOT NULL DEFAULT datetime('now', 'localtime'))
    - Add FOREIGN KEY on user_id REFERENCES users(id) ON DELETE CASCADE
    - Create index `idx_notifications_user_created` on (user_id, created_at)
    - Create index `idx_notifications_user_id_desc` on (user_id, id DESC)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ] 1.2 Create migration file `migrations/add_notifications.sql`
    - Include CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS statements
    - Ensure migration is idempotent for safe re-runs
    - Apply migration to `src/data/orex.db`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ] 2. Data layer functions
  - [ ] 2.1 Implement `create_notification` in `src/app/models.py`
    - Validate message is not empty or whitespace-only, raise ValueError if invalid
    - Validate user_id exists in users table, raise ValueError if not found
    - Call `prune_expired_notifications(user_id)` before inserting
    - Insert new notification row and return the created notification ID
    - Accept any non-empty string as category
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 7.3_

  - [ ] 2.2 Implement query functions in `src/app/models.py`
    - Implement `get_unread_notifications(user_id)` returning all notifications for user ordered by id DESC
    - Implement `get_unread_count(user_id)` returning count of notifications for user
    - Implement `get_new_notifications_since(user_id, since_id)` returning notifications with id > since_id
    - _Requirements: 3.2, 4.1, 6.5_

  - [ ] 2.3 Implement deletion functions in `src/app/models.py`
    - Implement `delete_notification(notification_id, user_id)` deleting a single notification owned by user, returning bool success
    - Implement `delete_all_notifications(user_id)` deleting all notifications for user, returning deleted count
    - Implement `prune_expired_notifications(user_id)` deleting notifications older than 48 hours for user
    - _Requirements: 7.1, 7.4, 8.1, 8.2, 4.5_

  - [ ]* 2.4 Write property tests for notification creation
    - **Property 1: Notification creation round-trip** — For any valid user, category, message, and action_url, create_notification returns a positive ID and the stored record matches all fields
    - **Property 2: Whitespace message rejection** — For any whitespace-only or empty message, create_notification raises ValueError and count is unchanged
    - **Property 3: Non-existent user rejection** — For any user_id not in the users table, create_notification raises ValueError and no row is inserted
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

  - [ ]* 2.5 Write property tests for query and deletion functions
    - **Property 4: Unread count accuracy** — For any user with N notifications, get_unread_count returns exactly N
    - **Property 5: Tray ordering is newest-first** — For any user with multiple notifications, get_unread_notifications returns them in strictly descending id order
    - **Property 6: Dismiss-all empties all notifications** — For any user with notifications, delete_all_notifications results in get_unread_count returning 0
    - **Property 8: Watermark filtering returns only newer notifications** — For any since_id, get_new_notifications_since returns only notifications with id > since_id
    - **Property 9: Pruning deletes expired and preserves fresh** — When create_notification triggers pruning, notifications older than 48h are deleted and fresher ones are preserved
    - **Property 10: Single dismiss removes exactly one notification** — delete_notification removes the target and leaves all others unchanged
    - **Validates: Requirements 3.2, 4.1, 4.5, 6.5, 7.1, 7.3, 8.1, 8.2**

- [ ] 3. Checkpoint - Data layer verification
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Category style mapping
  - [ ] 4.1 Implement category style mapping utility
    - Create a `get_notification_style(category)` function (in `src/app/models.py` or a new `src/app/notification_styles.py`)
    - Return (css_class, icon, duration) tuple based on category
    - "achievement" → ("flash--achievement", "trophy/star icon", 5000)
    - "liquidation" → ("flash--liquidation", "warning/alert icon", 5000)
    - All other categories → ("flash--default", "bell icon", 3000)
    - _Requirements: 5.3, 5.4, 5.5, 9.1, 9.2, 9.3, 9.4_

  - [ ]* 4.2 Write property test for category style mapping
    - **Property 7: Category style mapping is deterministic and consistent** — For any category string, the style mapping returns identical (css_class, icon, duration) values regardless of message, action_url, or creation time; tray icon equals toast icon for same category
    - **Validates: Requirements 9.3, 9.4, 9.5**

- [ ] 5. Blueprint routes
  - [ ] 5.1 Create `src/app/routes/notifications.py` with polling endpoint
    - Create blueprint `notifications_bp` with url_prefix `/notifications`
    - Implement `GET /notifications/poll` accepting `since` query param (default 0)
    - Return JSON: `{notifications: [...], unread_count: int, last_id: int}`
    - Each notification object includes: id, category, message, action_url, created_at, css_class, icon, duration
    - Require `@login_required`
    - _Requirements: 6.1, 6.2, 6.3, 6.5_

  - [ ] 5.2 Add tray and dismiss endpoints to `src/app/routes/notifications.py`
    - Implement `GET /notifications/tray` returning HTML partial of all unread notifications
    - Implement `DELETE /notifications/<int:id>` dismissing a single notification, returning updated tray partial with HX-Trigger for badge update
    - Implement `DELETE /notifications/all` dismissing all notifications, returning empty tray partial with HX-Trigger for badge update
    - If notification has action_url, the tray template handles navigation client-side
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 8.1, 8.2, 8.3_

  - [ ] 5.3 Register `notifications_bp` blueprint in `src/app/__init__.py`
    - Import and register the new blueprint in the app factory
    - _Requirements: 4.1_

- [ ] 6. Context processor and account lifecycle
  - [ ] 6.1 Register notification context processor in `src/app/__init__.py`
    - Add context processor that injects `notification_count` into all templates for authenticated users
    - Call `get_unread_count(current_user.id)` only when user is authenticated
    - _Requirements: 3.2, 3.3, 6.4_

  - [ ] 6.2 Integrate notification cleanup into account reset
    - In `reset_account()` (models.py), add `DELETE FROM notifications WHERE user_id = ?`
    - Verify CASCADE handles account deletion automatically (no extra code needed)
    - _Requirements: 10.1, 10.2, 10.3_

  - [ ]* 6.3 Write property test for account reset
    - **Property 11: Account reset removes all notifications** — For any user with notifications, calling reset_account results in zero notifications remaining
    - **Validates: Requirements 10.1**

- [ ] 7. Checkpoint - Routes and backend verification
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Templates: bell, tray, and toast
  - [ ] 8.1 Update `src/templates/partials/nav.html` with notification bell
    - Add bell icon element adjacent to the profile pill
    - Add `#notification-badge` span showing unread count from `notification_count`
    - Hide badge when count is 0, display "9+" when count exceeds 9
    - Add `aria-label` attribute including current unread count (e.g., "Notifications, 3 unread")
    - Add htmx polling attribute targeting badge update endpoint (30s interval)
    - Wire click to open/close notification tray via htmx GET
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 11.1_

  - [ ] 8.2 Create `src/templates/partials/notification_tray.html`
    - Render unread notifications in reverse chronological order
    - Each notification shows: category icon, message text, relative timestamp (e.g., "2m ago", "1h ago")
    - Notifications with action_url are clickable links that also trigger dismiss
    - Notifications without action_url dismiss on click
    - Include "Dismiss all" button
    - Show empty state message when no notifications
    - Add `role="menu"` to tray container and `role="menuitem"` to each notification item
    - Support keyboard navigation (Tab, Enter) and Escape to close
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 11.2, 11.4, 11.5_

  - [ ] 8.3 Create `src/templates/partials/notification_toast.html`
    - Single toast template structure matching existing `.flash--toast` pattern
    - Include category-specific CSS class and icon
    - Toast is clickable and navigates to action_url when present
    - Used as a template for JS-based injection
    - _Requirements: 5.1, 5.2, 5.6, 5.7_

  - [ ] 8.4 Add toast container to `src/templates/base.html`
    - Add fixed-position toast container in top-right corner for notification toasts
    - Add ARIA live region with `aria-live="polite"` for screen reader announcements
    - _Requirements: 5.2, 5.8, 11.3_

- [ ] 9. Client-side JavaScript
  - [ ] 9.1 Extend `src/static/js/notifications.js` with polling loop
    - Add `setInterval` at 30s calling `GET /notifications/poll?since=<last_id>`
    - Track `last_id` watermark between polls
    - Only poll when user is authenticated (check for presence of bell element)
    - On response: update badge count and visibility, trigger toasts for new notifications
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 9.2 Add toast injection and tray toggle logic to `src/static/js/notifications.js`
    - Create toast DOM elements from poll response data using existing `.flash--toast` structure
    - Apply category-specific modifier classes and duration
    - Auto-dismiss toasts after configured duration with fade-out animation
    - Handle tray open/close on bell click
    - Close tray on outside click or Escape key press, return focus to bell
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 4.6, 11.5_

- [ ] 10. CSS styles
  - [ ] 10.1 Add notification CSS classes to `src/static/css/global.css`
    - Add `.flash--achievement` with yellow background and trophy/star icon
    - Add `.flash--liquidation` with red background and warning/alert icon
    - Add `.notification-bell` positioning and icon styling
    - Add `.notification-badge` circular badge styles (hidden when empty)
    - Add `.notification-tray` dropdown panel styles
    - Add `.notification-item` individual row styles in tray with category icon
    - Add fade-out animation for toast dismissal
    - _Requirements: 5.2, 5.7, 9.1, 9.2, 9.3_

- [ ] 11. Checkpoint - Full feature integration
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Integration tests and final validation
  - [ ]* 12.1 Write unit tests for notification system
    - Test badge displays "9+" when count is 10
    - Test badge is hidden when count is 0
    - Test tray shows empty state when no notifications
    - Test achievement category returns yellow class
    - Test liquidation category returns red class
    - Test poll endpoint returns 401 for unauthenticated users
    - Test tray partial has `role="menu"` and items have `role="menuitem"`
    - Test bell element has `aria-label` with count
    - Test CASCADE delete removes notifications when user is deleted
    - _Requirements: 3.3, 3.4, 4.8, 9.1, 9.2, 6.4, 11.1, 11.2, 11.4, 10.2_

  - [ ]* 12.2 Write integration tests for notification lifecycle
    - Test full page render includes bell icon for authenticated user
    - Test polling endpoint returns correct JSON structure
    - Test DELETE endpoint removes notification and returns updated partial
    - Test htmx tray load returns partial (no `<!DOCTYPE>` in response)
    - Test account reset followed by tray request shows empty state
    - Test create_notification → poll → toast → dismiss lifecycle
    - _Requirements: 3.1, 6.1, 8.1, 4.7, 10.1, 10.3_

  - [ ] 12.3 Final checkpoint
    - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. SL/TP trigger toast notifications (Advanced Mode integration)
  - [ ] 13.1 Fire notification on SL/TP auto-sell in tick engine
    - In `evaluate_stop_loss_take_profit()` (engine.py), after a successful auto-sell, call `create_notification(user_id, 'liquidation', message, action_url)`
    - Message format: "Stop Loss triggered: sold {quantity} {ore_name} at ${price}" or "Take Profit triggered: sold {quantity} {ore_name} at ${price}"
    - action_url: link to transaction history or portfolio page
    - _Requirements: 5.1 (toast appearance), Advanced Mode Req 6.3, 6.4_

  - [ ] 13.2 Verify toast appears on next poll cycle
    - The existing polling loop (task 9.1) will pick up the new notification and show it as a toast with the "liquidation" category styling (red background, warning icon)
    - No additional client-side work needed — the existing system handles it
    - _Requirements: 6.1, 6.2_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (11 properties total across tasks 2.4, 2.5, 4.2, 6.3)
- Unit tests validate specific examples and edge cases
- The existing flash/toast CSS infrastructure is extended, not replaced
- No `is_read` column — acknowledged notifications are deleted immediately (design decision)
- Pruning piggybacks on `create_notification` rather than requiring a background scheduler
- All DELETE endpoints reuse existing CSRF protection from Flask-WTF
- The `notifications.js` extension builds on the existing file that handles flash toasts

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["2.4", "2.5", "4.1"] },
    { "id": 3, "tasks": ["4.2", "5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3", "6.1", "6.2"] },
    { "id": 5, "tasks": ["6.3", "8.1", "8.2"] },
    { "id": 6, "tasks": ["8.3", "8.4", "9.1"] },
    { "id": 7, "tasks": ["9.2", "10.1"] },
    { "id": 8, "tasks": ["12.1", "12.2"] }
  ]
}
```
