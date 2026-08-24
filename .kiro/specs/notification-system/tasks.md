# Implementation Plan: Notification System

## Overview

Implement the in-app Notification System for OreX. This proceeds bottom-up: schema → data layer functions → blueprint routes → context processor → profile dropdown redesign → inbox page templates → client-side polling JS → CSS → account lifecycle integration. Each step builds incrementally so the feature is testable at every stage.

## Tasks

- [x] 1. Database schema and migration
  - [x] 1.1 Update notifications table in `src/schema.sql`
    - Ensure `notifications` table has columns: id (INTEGER PRIMARY KEY), user_id (INTEGER NOT NULL), category (TEXT NOT NULL), message (TEXT NOT NULL), action_url (TEXT), is_read (INTEGER NOT NULL DEFAULT 0), created_at (TEXT NOT NULL DEFAULT datetime('now', 'localtime'))
    - Ensure FOREIGN KEY on user_id REFERENCES users(id) ON DELETE CASCADE
    - Replace existing indexes with: `idx_notifications_user_read` on (user_id, is_read) and `idx_notifications_user_id_desc` on (user_id, id DESC)
    - Remove any `idx_notifications_user_created` index if present (no longer needed without pruning)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 1.2 Update migration file `migrations/add_notifications.sql`
    - Include CREATE TABLE IF NOT EXISTS with `is_read` column and CREATE INDEX IF NOT EXISTS statements
    - Ensure migration is idempotent for safe re-runs
    - Handle existing databases that already have the table (the `is_read` column already exists from the placeholder)
    - Apply migration to `src/data/orex.db`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Data layer functions
  - [x] 2.1 Implement `create_notification` in `src/app/models.py`
    - Validate message is not empty or whitespace-only, raise ValueError if invalid
    - Validate user_id exists in users table, raise ValueError if not found
    - Insert new notification row with is_read=0 and return the created notification ID
    - Accept any non-empty string as category
    - Move function from `src/app/advancements.py` to models.py with validation added
    - Update `advancements.py` to import from models instead of defining its own
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 2.2 Implement query functions in `src/app/models.py`
    - Implement `get_notifications(user_id, filter='all')` returning notifications filtered by 'all', 'read', or 'unread', ordered by id DESC
    - Implement `get_notification_detail(notification_id, user_id)` returning a single notification owned by user or None
    - Implement `has_unread_notifications(user_id)` returning bool (True if any is_read=0 exist)
    - Implement `get_new_notifications_since(user_id, since_id)` returning unread notifications with id > since_id
    - _Requirements: 3.2, 4.1, 4.2, 4.3, 6.5_

  - [x] 2.3 Implement mutation functions in `src/app/models.py`
    - Implement `mark_notification_read(notification_id, user_id)` setting is_read=1, returning bool success
    - Implement `mark_all_notifications_read(user_id)` setting is_read=1 for all user notifications, returning updated count
    - Implement `delete_notification(notification_id, user_id)` deleting a single notification owned by user, returning bool success
    - _Requirements: 7.1, 7.2, 7.4, 8.1, 8.3, 4.4, 4.5_

  - [x] 2.4 Write property tests for notification creation
    - **Property 1: Notification creation round-trip** — For any valid user, category, message, and action_url, create_notification returns a positive ID and the stored record matches all fields with is_read=0
    - **Property 2: Whitespace message rejection** — For any whitespace-only or empty message, create_notification raises ValueError and count is unchanged
    - **Property 3: Non-existent user rejection** — For any user_id not in the users table, create_notification raises ValueError and no row is inserted
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

  - [x] 2.5 Write property tests for query and mutation functions
    - **Property 4: Has-unread accuracy** — For any user with at least one is_read=0 notification, has_unread returns True; with all read or none, returns False
    - **Property 5: List ordering is newest-first** — For any user with multiple notifications, get_notifications returns them in strictly descending id order
    - **Property 6: Mark-all-read marks all** — For any user with unread notifications, mark_all_notifications_read results in has_unread returning False
    - **Property 8: Watermark filtering returns only newer unread** — For any since_id, get_new_notifications_since returns only unread notifications with id > since_id
    - **Property 9: Single delete removes exactly one** — delete_notification removes the target and leaves all others unchanged
    - **Property 10: Mark-read sets is_read without deleting** — mark_notification_read sets is_read=1 and the notification remains retrievable
    - **Validat es: Requirements 3.2, 4.1, 4.5, 6.5, 7.1, 8.1, 8.3**

- [x] 3. Checkpoint - Data layer verification
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Category style mapping
  - [x] 4.1 Implement category style mapping utility
    - Create a `get_notification_style(category)` function in `src/app/models.py`
    - Return (css_class, icon, duration) tuple based on category
    - "achievement" → ("flash--achievement", "trophy/star icon", 5000)
    - "liquidation" → ("flash--liquidation", "warning/alert icon", 5000)
    - All other categories → ("flash--default", "bell icon", 3000)
    - _Requirements: 5.3, 5.4, 5.5, 9.1, 9.2, 9.3, 9.4_

  - [x] 4.2 Write property test for category style mapping
    - **Property 7: Category style mapping is deterministic and consistent** — For any category string, the style mapping returns identical (css_class, icon, duration) values regardless of message, action_url, or creation time
    - **Validates: Requirements 9.3, 9.4, 9.5**

- [x] 5. Blueprint routes
  - [x] 5.1 Create `src/app/routes/inbox.py` with polling endpoint
    - Create blueprint `inbox_bp` with url_prefix `/inbox`
    - Implement `GET /inbox/poll` accepting `since` query param (default 0)
    - Return JSON: `{notifications: [...], has_unread: bool, last_id: int}`
    - Each notification object includes: id, category, message, action_url, created_at, css_class, icon, duration
    - Require `@login_required`
    - _Requirements: 6.1, 6.2, 6.3, 6.5_

  - [x] 5.2 Add inbox page and detail endpoints to `src/app/routes/inbox.py`
    - Implement `GET /inbox` rendering the full inbox page with list + empty detail panel
    - Accept `filter` query param ('all', 'read', 'unread') for tab filtering
    - Implement `GET /inbox/<int:id>` returning detail panel partial (htmx)
    - Implement `POST /inbox/<int:id>/read` marking notification as read, returning detail partial
    - Implement `POST /inbox/mark-all-read` marking all as read, returning updated list partial
    - Implement `DELETE /inbox/<int:id>` deleting a notification, returning updated list partial
    - All endpoints require `@login_required`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 7.1, 7.2, 7.3, 8.1, 8.3, 8.4_

  - [x] 5.3 Register `inbox_bp` blueprint in `src/app/__init__.py`
    - Import and register the new blueprint in the app factory
    - _Requirements: 4.1_

  - [x] 5.4 Remove notification poll route from advancements blueprint
    - Delete `poll_notifications()` function from `src/app/routes/advancements.py`
    - Remove the htmx polling div from `src/templates/base.html` that targets the advancements poll route
    - Delete `src/templates/partials/notification_toasts.html` (will be replaced by new toast template)
    - _Requirements: 5.1, 6.1_

- [x] 6. Context processor and account lifecycle
  - [x] 6.1 Register notification context processor in `src/app/__init__.py`
    - Add context processor that injects `has_unread` (boolean) into all templates for authenticated users
    - Call `has_unread_notifications(current_user.id)` only when user is authenticated
    - _Requirements: 3.2, 3.3, 6.4_

  - [x] 6.2 Integrate notification cleanup into account reset
    - In `reset_account()` (models.py), add `DELETE FROM notifications WHERE user_id = ?`
    - Verify CASCADE handles account deletion automatically (no extra code needed)
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 6.3 Write property test for account reset
    - **Property 11: Account reset removes all notifications** — For any user with notifications, calling reset_account results in zero notifications remaining
    - **Validates: Requirements 10.1**

- [x] 7. Checkpoint - Routes and backend verification
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Profile dropdown redesign
  - [x] 8.1 Redesign `src/templates/partials/nav.html` profile dropdown
    - Replace text-only dropdown links with new compact layout:
      - Icon row at top: Portfolio icon, Inbox icon (with red dot), History icon
      - Text links below: Profile, Settings
      - Logout link at bottom separated by divider, red/danger styling
    - Each icon navigates directly to its page (Portfolio, Inbox, History)
    - Inbox icon displays red dot when `has_unread` is True (from context processor)
    - Use placeholder icons initially (Material Design icons to be added later)
    - Add `aria-label` to inbox icon indicating purpose and unread state
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 3.1, 3.2, 3.3, 3.5, 11.1_

  - [x] 8.2 Add CSS for redesigned dropdown in `src/static/css/global.css`
    - Add `.nav__dropdown-icons` — horizontal flex row container for icon buttons
    - Add `.nav__dropdown-icon` — individual icon button styling (square, hover state)
    - Add `.nav__dropdown-icon--unread` — red dot overlay (small circle, positioned top-right of icon)
    - Adjust existing `.nav__dropdown` padding/spacing for new layout
    - _Requirements: 12.1, 12.5, 3.5_

- [x] 9. Inbox page templates
  - [x] 9.1 Create `src/templates/inbox.html` full page template
    - Extends base.html
    - Two-panel layout: left panel (list) and right panel (detail)
    - Include filter tab row (All | Read | Unread) and "Mark all as read" button in header
    - Left panel includes `partials/inbox_list.html`
    - Right panel includes `partials/inbox_detail.html` (initially empty/placeholder state)
    - _Requirements: 4.1, 4.3, 4.4, 4.7, 4.8_

  - [x] 9.2 Create `src/templates/partials/inbox_list.html`
    - Render notification entries in reverse chronological order
    - Each entry shows: category icon, message text, relative timestamp
    - Unread entries: bold/bright text styling
    - Read entries: greyed/muted text styling
    - Each entry has a bin (delete) icon visible on hover
    - Each entry is clickable: htmx GET to load detail + POST to mark as read
    - Show empty state when no notifications match the current filter
    - _Requirements: 4.1, 4.2, 4.8, 7.1, 8.1, 8.2, 9.5, 11.4, 11.5_

  - [x] 9.3 Create `src/templates/partials/inbox_detail.html`
    - Template-based layout (email-like structure): header with category icon + timestamp, body with message, footer with action link if present
    - Content area padded with category-specific expanded info (TBD per category — start with generic layout)
    - Empty/placeholder state when no notification is selected
    - _Requirements: 4.5, 4.6, 4.7_

  - [x] 9.4 Create `src/templates/partials/notification_toast.html`
    - Single toast template structure matching existing `.flash--toast` pattern
    - Include category-specific CSS class and icon
    - Toast is clickable and navigates to action_url when present
    - Used as a template for JS-based injection
    - _Requirements: 5.1, 5.2, 5.6, 5.7_

  - [x] 9.5 Update toast container in `src/templates/base.html`
    - Replace old advancements polling div with new toast container
    - Keep fixed-position toast container in top-right corner
    - Keep ARIA live region with `aria-live="polite"` for screen reader announcements
    - Wire to new polling system (JS-driven, not htmx hx-get on the container)
    - _Requirements: 5.2, 5.8, 11.3_

- [x] 10. Client-side JavaScript
  - [x] 10.1 Extend `src/static/js/notifications.js` with polling loop
    - Add `setInterval` at 20s calling `GET /inbox/poll?since=<last_id>`
    - Track `last_id` watermark between polls
    - Only poll when user is authenticated (check for presence of inbox icon or a data attribute)
    - On response: toggle red dot visibility on inbox icon, trigger toasts for new notifications
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 3.4_

  - [x] 10.2 Add toast injection logic to `src/static/js/notifications.js`
    - Create toast DOM elements from poll response data using existing `.flash--toast` structure
    - Apply category-specific modifier classes and duration
    - Auto-dismiss toasts after configured duration with fade-out animation
    - Handle toast click → navigate to action_url or inbox page
    - Pause toast display while the profile dropdown is open: queue incoming toasts and flush the queue when the dropdown closes
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 10.3 Add inbox page interactivity to `src/static/js/notifications.js` (or new `inbox.js`)
    - Handle list item click → load detail panel via htmx
    - Handle delete icon click → delete notification via htmx, update list
    - Handle filter tab clicks → reload list with filter param
    - Handle "Mark all as read" → POST and update list styling
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 7.1, 7.3, 8.3, 8.4_

- [x] 11. CSS styles
  - [x] 11.1 Add notification and inbox CSS classes to `src/static/css/global.css`
    - Keep `.flash--achievement` with yellow background (already exists)
    - Add `.flash--liquidation` with red background and warning/alert icon
    - Add `.inbox` two-panel page layout (flexbox or grid, responsive)
    - Add `.inbox__list` left panel styles (scrollable, fixed width)
    - Add `.inbox__list-item` notification row styles
    - Add `.inbox__list-item--unread` bold/bright text for unread entries
    - Add `.inbox__list-item--read` greyed/muted text for read entries
    - Add `.inbox__list-item:hover .inbox__delete-btn` bin icon visibility on hover
    - Add `.inbox__detail` right panel styles (flexible width, padded)
    - Add `.inbox__filters` filter tab row styles
    - Add `.inbox__empty-state` empty state message styles
    - Add fade-out animation for toast dismissal
    - _Requirements: 5.2, 5.7, 8.2, 9.1, 9.2, 9.3_

- [x] 12. Checkpoint - Full feature integration
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Integration tests and final validation
  - [x] 13.1 Write unit tests for notification system
    - Test red dot appears when has_unread is True
    - Test red dot hidden when has_unread is False
    - Test inbox list shows bold for unread entries
    - Test inbox list shows greyed for read entries
    - Test achievement category returns yellow class
    - Test liquidation category returns red class
    - Test poll endpoint returns 401 for unauthenticated users
    - Test filter tabs correctly filter notifications
    - Test CASCADE delete removes notifications when user is deleted
    - _Requirements: 3.3, 3.5, 8.2, 9.1, 9.2, 6.4, 11.1, 10.2_

  - [x] 13.2 Write integration tests for notification lifecycle
    - Test full page render includes profile dropdown with inbox icon for authenticated user
    - Test polling endpoint returns correct JSON structure with has_unread boolean
    - Test DELETE endpoint removes notification and returns updated list partial
    - Test POST mark-read endpoint sets is_read=1 and returns detail partial
    - Test inbox page renders two-panel layout
    - Test account reset followed by inbox page shows empty state
    - Test create_notification → poll → toast → open inbox → see entry lifecycle
    - _Requirements: 3.1, 6.1, 7.2, 8.1, 4.1, 10.1, 10.3_

  - [x] 13.3 Final checkpoint
    - Ensure all tests pass, ask the user if questions arise.

- [x] 14. SL/TP trigger toast notifications (Advanced Mode integration)
  - [x] 14.1 Fire notification on SL/TP auto-sell in tick engine
    - In `evaluate_stop_loss_take_profit()` (engine.py), after a successful auto-sell, call `create_notification(user_id, 'liquidation', message, action_url)`
    - Message format: "Stop Loss triggered: sold {quantity} {ore_name} at ${price}" or "Take Profit triggered: sold {quantity} {ore_name} at ${price}"
    - action_url: link to transaction history or inbox page
    - _Requirements: 5.1 (toast appearance), Advanced Mode Req 6.3, 6.4_

  - [x] 14.2 Verify toast appears on next poll cycle
    - The existing polling loop (task 10.1) will pick up the new notification and show it as a toast with the "liquidation" category styling (red background, warning icon)
    - No additional client-side work needed — the existing system handles it
    - _Requirements: 6.1, 6.2_

## Notes

- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (11 properties total across tasks 2.4, 2.5, 4.2, 6.3)
- Unit tests validate specific examples and edge cases
- The existing flash/toast CSS infrastructure is extended, not replaced
- `is_read` column is retained — read notifications appear greyed in inbox, not deleted
- No auto-pruning — users delete notifications manually via bin icon
- All DELETE/POST endpoints reuse existing CSRF protection from Flask-WTF
- The `notifications.js` extension builds on the existing file that handles flash toasts
- Detail panel content is template-based and TBD per category (generic layout first, category-specific expansion later)
- Profile dropdown redesign uses placeholder icons initially; Material Design icons added in polish pass
- **TODO:** In `nav.html`, the "Profile" link currently points to `settings.overview` as a placeholder — replace with a dedicated profile route (e.g., `profile.overview`) once one exists

## Future: Content & Polish Pass

This spec implements the bare-bones notification infrastructure (schema, data layer, inbox page, toasts, polling). A separate **content & polish pass** is planned after all core systems are built. That pass will cover:

- **Inbox detail panel content per category** — What the "email body" actually shows for achievements, liquidations, tutorial milestones, etc. Currently the detail panel uses a generic template.
- **Tutorial system integration** — The tutorial system (once implemented) will likely send inbox notifications (welcome messages, milestone congrats, resume prompts). It just needs to call `create_notification()` — no infrastructure changes required. Remember that the future help section should also contain tutorial start buttons.
- **Changelog / About page content** — Written alongside tutorial step copy to maintain consistent voice.
- **Any other systems** that want to emit notifications (daily bonuses, market events, etc.) — they just call `create_notification()` and the inbox handles the rest.

This is intentional: the notification API is stable regardless of what detail panels show or what systems emit notifications. Adding new categories and detail templates later doesn't require reworking infrastructure.

## Existing Placeholder (from achievements-system task 7.3)

The achievements-system spec (task 7.3) implemented a **partial notification infrastructure** as a placeholder. Here is what currently exists and what needs to change:

### What already exists

| File | What's there |
|------|-------------|
| `src/schema.sql` | `notifications` table with `is_read` column ✓ (keep as-is) |
| `migrations/add_notifications.sql` | CREATE TABLE with `is_read` column ✓ (update indexes only) |
| `src/app/routes/advancements.py` | `GET /notifications/poll` endpoint — returns HTML partial, marks as read |
| `src/templates/partials/notification_toasts.html` | Toast partial rendering notifications as `<a>` elements |
| `src/templates/base.html` | `#notification-toasts` div with `hx-get` polling every 10s targeting advancements |
| `src/static/js/notifications.js` | `initToast()` + `htmx:afterSwap` listener for dynamic toast injection |
| `src/static/css/global.css` | `.flash--advancement` yellow style |
| `src/app/advancements.py` | `create_notification()` function (simple INSERT wrapper) |

### What must change

1. **Keep `is_read` column and table structure** — The existing schema is mostly correct. Just update indexes (task 1.1).
2. **Replace indexes** — Remove `idx_notifications_user_read` if it's on wrong columns, ensure (user_id, is_read) and (user_id, id DESC).
3. **Delete the poll route from advancements blueprint** — Remove `poll_notifications()` from `src/app/routes/advancements.py`. The new `inbox_bp` blueprint (task 5.1) owns all notification endpoints.
4. **Remove htmx polling div from base.html** — Remove the `#notification-toasts` div that currently polls the advancements blueprint. Task 9.5 will add the proper toast container (JS-driven, not htmx hx-get).
5. **Delete `src/templates/partials/notification_toasts.html`** — Task 9.4 creates the correct toast template.
6. **Move `create_notification()` to models.py** — Task 2.1 implements the proper version with validation in `src/app/models.py`. Update `advancements.py` to import from models.
7. **Keep `notifications.js` changes** — The `initToast()` + `htmx:afterSwap` pattern is correct and will be extended by tasks 10.1/10.2.
8. **Keep `.flash--achievement` CSS** — The yellow style is correct. Task 11.1 adds `.flash--liquidation` alongside it.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["2.4", "2.5", "4.1"] },
    { "id": 3, "tasks": ["4.2", "5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3", "5.4", "6.1", "6.2"] },
    { "id": 5, "tasks": ["6.3", "8.1", "8.2"] },
    { "id": 6, "tasks": ["9.1", "9.2", "9.3"] },
    { "id": 7, "tasks": ["9.4", "9.5", "10.1"] },
    { "id": 8, "tasks": ["10.2", "10.3", "11.1"] },
    { "id": 9, "tasks": ["13.1", "13.2"] },
    { "id": 10, "tasks": ["14.1", "14.2"] }
  ]
}
```
