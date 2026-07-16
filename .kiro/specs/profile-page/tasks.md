# Implementation Plan: Profile Page

## Overview

Implement the Profile Page feature for OreX — a player identity hub at `/profile` consolidating avatar upload with client-side cropping, gameplay statistics, a one-time 3-day login bonus system, and achievement display. Implementation proceeds bottom-up: schema → storage abstraction → avatar processing → bonus logic → peak net worth tracking → profile blueprint/routes → templates → navigation updates → leaderboard integration → account lifecycle hooks.

## Tasks

- [ ] 1. Database schema and configuration
  - [ ] 1.1 Add profile-related columns to users table in `src/schema.sql`
    - Add `avatar_path TEXT DEFAULT NULL` column to users table
    - Add `peak_net_worth REAL NOT NULL DEFAULT 10000` column to users table
    - Add `bonus_cycle_day INTEGER NOT NULL DEFAULT 1` column to users table
    - Add `last_bonus_collected_date TEXT DEFAULT NULL` column to users table
    - _Requirements: 7.1, 7.2, 9.4, 4.5_

  - [ ] 1.2 Add profile configuration constants to `src/app/config.py`
    - Add `STORAGE_BACKEND = os.environ.get('STORAGE_BACKEND', 'local')`
    - Add `MAX_AVATAR_SIZE = 2 * 1024 * 1024` (2 MB)
    - Add `AVATAR_OUTPUT_SIZE = 300` (pixels, square)
    - Add `AVATAR_FORMAT = 'WEBP'`
    - Add OCI config: `OCI_NAMESPACE`, `OCI_BUCKET`, `OCI_CONFIG_PATH`
    - Add `BONUS_AMOUNTS = {1: 1000, 2: 10000, 3: 100000}`
    - _Requirements: 6.1, 9.6, 9.8_

  - [ ] 1.3 Apply schema migration to existing database
    - Create migration script to ALTER the users table adding the 4 new columns
    - Run migration against `src/data/orex.db`
    - _Requirements: 7.1, 9.4_

- [ ] 2. Implement storage abstraction
  - [ ] 2.1 Create `src/app/storage.py` with StorageBackend interface and LocalStorage implementation
    - Define abstract `StorageBackend` class with `store()`, `delete()`, and `get_url()` methods
    - Implement `LocalStorage` class storing files in `static/uploads/avatars/`
    - Implement `get_storage_backend(app)` factory function selecting backend from config
    - _Requirements: 9.1, 9.6, 9.7_

  - [ ] 2.2 Add OCIStorage implementation to `src/app/storage.py`
    - Implement `OCIStorage` class using Oracle Cloud Infrastructure SDK
    - Store files in configured bucket with namespace/bucket from config
    - Generate public URLs for stored objects
    - _Requirements: 9.1, 9.8_

- [ ] 3. Implement avatar processing module
  - [ ] 3.1 Create `src/app/avatar.py` with validation and processing functions
    - Implement `validate_avatar(file_data)` checking size ≤ 2MB and format in {PNG, JPEG, WEBP}
    - Implement `process_avatar(file_data, output_size=300)` resizing to square WebP output
    - Define `ALLOWED_FORMATS`, `MAX_FILE_SIZE`, and `OUTPUT_SIZE` constants
    - _Requirements: 2.4, 2.5, 2.6, 2.7_

  - [ ]* 3.2 Write property tests for avatar validation
    - **Property 2: Avatar Validation Correctness** — For any byte sequence > 2MB, validate returns (False, size_error). For valid images in {PNG, JPEG, WEBP} ≤ 2MB, validate returns (True, ""). For invalid formats ≤ 2MB, validate returns (False, format_error).
    - **Validates: Requirements 2.4, 2.5, 2.6**

  - [ ]* 3.3 Write property test for avatar processing dimensions
    - **Property 3: Avatar Processing Produces Fixed Dimensions** — For any valid image of arbitrary W×H (W≥1, H≥1), process_avatar produces a WebP image of exactly AVATAR_OUTPUT_SIZE × AVATAR_OUTPUT_SIZE pixels.
    - **Validates: Requirements 2.7**

- [ ] 4. Implement daily bonus logic module
  - [ ] 4.1 Create `src/app/bonus.py` with pure bonus functions
    - Implement `is_bonus_available(user_row)` checking cycle_day < 4 AND last_collected != today
    - Implement `get_bonus_amount(cycle_day)` returning amount from {1:1000, 2:10000, 3:100000} or 0
    - Implement `is_bonus_complete(cycle_day)` returning True if cycle_day >= 4
    - Implement `collect_bonus(db, user_id)` performing the full collection transaction
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.5, 7.6_

  - [ ]* 4.2 Write property test for bonus amount mapping
    - **Property 5: Bonus Amount Mapping** — For any cycle_day D in {1,2,3}, get_bonus_amount(D) returns the correct mapped value. For D≥4 or D≤0, returns 0.
    - **Validates: Requirements 6.1**

  - [ ]* 4.3 Write property test for bonus collection state machine
    - **Property 6: Bonus Collection State Machine** — For any player state (D, L, T): if D≥4, collect returns (False, 0) and balance unchanged; if D<4 AND L==T, returns (False, 0); if D<4 AND (L is NULL OR L!=T), returns (True, BONUS_AMOUNTS[D]) with correct state transitions.
    - **Validates: Requirements 6.2, 6.3, 6.4, 7.5, 7.6**

- [ ] 5. Implement peak net worth tracking
  - [ ] 5.1 Add `update_peak_net_worths(db)` function to tick engine (`src/app/market/engine.py`)
    - Query all users with their computed net worth (balance + holdings value)
    - Update `peak_net_worth` for players whose current net worth exceeds stored peak
    - Call after `process_tick(db)` in the tick engine cycle
    - _Requirements: 4.1, 4.2_

  - [ ]* 5.2 Write property test for peak net worth monotonicity
    - **Property 4: Peak Net Worth is Monotonically Non-Decreasing** — For any player with stored peak P and current net worth N: if N>P, stored peak becomes N; if N≤P, stored peak remains P. New peak = max(N, P).
    - **Validates: Requirements 4.1, 4.2**

- [ ] 6. Checkpoint - Core modules verification
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement profile blueprint and routes
  - [ ] 7.1 Create `src/app/routes/profile.py` with profile blueprint and overview route
    - Create `profile_bp` Blueprint
    - Implement `GET /profile` route with `@login_required`
    - Query user stats (username, balance, created_at, avatar_path, bonus state, play_time, login_streak, peak_net_worth)
    - Query trade_count from transactions table
    - Retrieve achievements via `get_user_achievements(db, user_id)`
    - Compute bonus availability and amount
    - Render `pages/profile.html` template with all context
    - _Requirements: 1.1, 1.2, 4.3, 5.1, 5.2, 5.3, 5.4, 6.2, 6.7, 8.1_

  - [ ] 7.2 Add avatar upload route to `src/app/routes/profile.py`
    - Implement `POST /profile/avatar` with `@login_required`
    - Validate uploaded file (presence, size, format) using `validate_avatar()`
    - Process image with `process_avatar()` to resize to square WebP
    - Store via `StorageBackend.store()` with filename `{user_id}.webp`
    - Update `avatar_path` on users table
    - Return htmx partial with new avatar image tag
    - _Requirements: 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 9.2, 9.3_

  - [ ] 7.3 Add bonus collection route to `src/app/routes/profile.py`
    - Implement `POST /profile/bonus/collect` with `@login_required`
    - Call `collect_bonus(db, user_id)` and flash appropriate message
    - Return htmx partial with updated bonus section
    - _Requirements: 6.3, 6.10_

  - [ ] 7.4 Register profile blueprint in `src/app/__init__.py`
    - Import and register `profile_bp` in the app factory
    - _Requirements: 1.1_

  - [ ]* 7.5 Write property tests for avatar URL resolution and filename derivation
    - **Property 1: Avatar URL Resolution** — For any user row: if avatar_path is non-null/non-empty, resolved URL derives from avatar_path; if NULL/empty, returns default avatar path.
    - **Property 7: Avatar Filename Derivation** — For any positive integer user_id, stored filename equals `f"{user_id}.webp"`.
    - **Validates: Requirements 2.1, 9.2**

- [ ] 8. Implement profile templates
  - [ ] 8.1 Create `src/templates/pages/profile.html` with layout sections
    - Create profile page extending `base.html`
    - Header section: username + avatar with upload button overlay (show first 2 letters if no PFP)
    - Stats grid: 4 stat boxes (creation date + play time, peak net worth, trade count, login streak + bonus)
    - Achievement ring: 9 badges with earned/locked visual states and expand/collapse toggle
    - Include Cropper.js from CDN for avatar upload
    - _Requirements: 2.1, 2.2, 4.3, 5.1, 5.2, 5.3, 6.7, 6.8, 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ] 8.2 Implement daily bonus UI section within profile template
    - Display current cycle day, reward amount, and collection status
    - Show 3-day visual progress indicator (completed/current/upcoming states)
    - Add "Collect" button triggering htmx POST to `/profile/bonus/collect`
    - Conditionally hide entire section when `bonus_cycle_day >= 4`
    - _Requirements: 6.7, 6.8, 6.9, 6.10_

  - [ ] 8.3 Implement avatar upload JavaScript with Cropper.js integration
    - Load Cropper.js from CDN on profile page only
    - Initialize cropper with 1:1 aspect ratio constraint on file selection
    - On confirm: `getCroppedCanvas().toBlob()` → POST to `/profile/avatar` via htmx
    - Swap avatar section with htmx response
    - _Requirements: 2.2, 2.3, 2.8_

- [ ] 9. Update navigation and leaderboard
  - [ ] 9.1 Update `src/templates/partials/nav.html` with Profile and Help links
    - Add "Profile" link pointing to `url_for('profile.overview')` in dropdown
    - Add "Help" link pointing to `url_for('pages.help')` in dropdown
    - _Requirements: 1.3, 1.4, 1.5_

  - [ ] 9.2 Update leaderboard query in `src/app/models.py` to include `avatar_path`
    - Add `avatar_path` to the SELECT in the leaderboard query
    - _Requirements: 3.1, 3.2_

  - [ ] 9.3 Update `src/templates/partials/leaderboard_table.html` to display avatars
    - Show player's Profile_Picture (or Default_Avatar) at 32×32 px next to username
    - Show Bot_Icon for bot accounts instead of avatar
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ] 9.4 Create default avatar and bot icon assets
    - Add `src/static/images/default-avatar.png` (generic avatar fallback)
    - Add `src/static/images/bot-icon.png` (bot indicator for leaderboard)
    - Create `src/static/uploads/avatars/` directory structure
    - _Requirements: 2.1, 3.2, 9.7_

- [ ] 10. Checkpoint - Routes and templates verification
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Account lifecycle integration
  - [ ] 11.1 Update `reset_account()` in `src/app/models.py` for profile fields
    - Reset `peak_net_worth` to 10000 (default balance)
    - Reset `bonus_cycle_day` to 1
    - Reset `last_bonus_collected_date` to NULL
    - Preserve `avatar_path` (do NOT clear)
    - Preserve `created_at` (do NOT clear)
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ] 11.2 Update `delete_account()` in `src/app/models.py` for avatar cleanup
    - Retrieve user's `avatar_path` before deletion
    - If avatar exists, call `storage.delete(f"{user_id}.webp")` to remove the file
    - _Requirements: 10.5_

- [ ] 12. Integration tests and final verification
  - [ ]* 12.1 Write integration tests for avatar upload lifecycle
    - Test full upload flow: select image → crop → upload → verify DB updated + file stored
    - Test re-upload overwrites previous file
    - Test rejection of invalid format and oversized files
    - Test unauthenticated access returns redirect
    - _Requirements: 2.3, 2.4, 2.5, 2.6, 9.2, 9.3, 1.2_

  - [ ]* 12.2 Write integration tests for bonus collection full cycle
    - Test collect day 1 → verify balance +1000 → advance date → collect day 2 → verify balance +10000 → advance date → collect day 3 → verify balance +100000 → verify cycle_day=4 → attempt collect → verify rejected
    - Test double collection on same day rejected
    - Test section hidden after completion
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.9_

  - [ ]* 12.3 Write integration tests for peak net worth and account lifecycle
    - Test peak net worth updates when current exceeds stored
    - Test peak net worth unchanged when current is lower
    - Test account reset preserves avatar, resets bonus and peak
    - Test account delete removes avatar file from storage
    - _Requirements: 4.1, 4.2, 10.1, 10.2, 10.3, 10.5_

- [ ] 13. Final checkpoint - Complete test suite passes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (7 properties total)
- Unit tests validate specific examples and edge cases
- The project already uses Hypothesis for property-based testing (`.hypothesis/` directory present)
- Cropper.js is loaded from CDN only on the profile page to avoid site-wide bundle bloat
- Avatar filename is derived from user_id (`{user_id}.webp`) — prevents path traversal and ensures uniqueness
- SQLite WAL mode provides isolation for concurrent tick engine + bonus collection
- The `ON DELETE CASCADE` or explicit cleanup handles account deletion

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "4.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.2", "4.3", "5.1"] },
    { "id": 4, "tasks": ["5.2", "7.1", "7.2", "7.3"] },
    { "id": 5, "tasks": ["7.4", "7.5"] },
    { "id": 6, "tasks": ["8.1", "8.2", "8.3"] },
    { "id": 7, "tasks": ["9.1", "9.2", "9.3", "9.4"] },
    { "id": 8, "tasks": ["11.1", "11.2"] },
    { "id": 9, "tasks": ["12.1", "12.2", "12.3"] }
  ]
}
```
