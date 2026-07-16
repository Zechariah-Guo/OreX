# Implementation Plan: Tutorial System

## Overview

Implement a guided tutorial overlay system for OreX using Alpine.js, Flask blueprints, and SQLite persistence. The approach is bottom-up: database schema → data loader → model functions → Flask blueprint → context processor → Alpine.js component → templates/CSS → Help page integration → account lifecycle hooks. Each step builds incrementally so the feature is testable at every stage.

## Tasks

- [ ] 1. Database schema and configuration
  - [ ] 1.1 Add `tutorial_progress` table to `src/schema.sql`
    - Create table with columns: id (INTEGER PRIMARY KEY), user_id (INTEGER NOT NULL FK to users ON DELETE CASCADE), track_id (TEXT NOT NULL), current_step_index (INTEGER NOT NULL DEFAULT 0), status (TEXT NOT NULL DEFAULT 'not_started' CHECK IN ('not_started','in_progress','completed','dismissed')), last_updated (TEXT NOT NULL DEFAULT datetime('now','localtime'))
    - Add UNIQUE constraint on (user_id, track_id)
    - Create index `idx_tutorial_progress_user` on user_id
    - Create index `idx_tutorial_progress_user_status` on (user_id, status)
    - _Requirements: 11.1, 11.2_

  - [ ] 1.2 Add tutorial configuration constants to `src/app/config.py`
    - Add `TUTORIAL_HIGHLIGHT_PADDING = 8`
    - Add `TUTORIAL_TRANSITION_DURATION = 400`
    - Add `TUTORIAL_BACKDROP_OPACITY = 0.5`
    - Add `TUTORIAL_DATA_PATH = 'static/data/tutorials.json'`
    - _Requirements: 9.6, 3.2_

  - [ ] 1.3 Create tutorial step definitions JSON at `src/static/data/tutorials.json`
    - Define "beginner" track with trigger "first_login" and steps covering: welcome intro, dashboard overview (balance/net worth), market page navigation, ore detail (price chart), executing a buy/sell trade, portfolio holdings overview, leaderboard explanation
    - Define "advanced" track with trigger "first_advanced_activation" and steps covering: Advanced Mode welcome, finances page capital breakdown, opening a short position, collateral/fee mechanics, setting SL/TP, resistance/support chart overlays, cash runway risk indicator
    - Each step has: index, selector, route, title, description, position, action
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ] 2. Tutorial data loader module
  - [ ] 2.1 Create `src/app/tutorial/data.py` with track loading functions
    - Implement `load_track(track_id)` — load and return a track dict from tutorials.json, or None if unknown
    - Implement `load_all_tracks()` — return list of all track metadata (id, name, trigger)
    - Implement `get_step(track_id, step_index)` — return a single step dict or None if out of bounds
    - Implement `get_track_length(track_id)` — return total number of steps in a track
    - Create `src/app/tutorial/__init__.py` for the package
    - _Requirements: 1.1, 1.2, 1.5_

  - [ ]* 2.2 Write property test for tutorial data serialization round-trip
    - **Property 1: Tutorial Data Serialization Round-Trip**
    - Generate random tracks with valid step fields (index, selector, route, title, description, position from ['top','bottom','left','right','center'], optional action)
    - Serialize to JSON and deserialize back, verify identical structure
    - **Validates: Requirements 1.1, 1.2**

- [ ] 3. Tutorial state model functions
  - [ ] 3.1 Create `src/app/tutorial/models.py` with database access functions
    - Implement `get_tutorial_state(user_id, track_id)` — return tutorial_progress row as dict or None
    - Implement `get_all_tutorial_states(user_id)` — return all tutorial_progress rows for a user
    - Implement `create_or_update_tutorial_state(user_id, track_id, status, step_index)` — upsert record, return row ID
    - Implement `advance_step(user_id, track_id, new_index)` — update current_step_index, return True on success
    - Implement `complete_tutorial(user_id, track_id)` — set status='completed', reset step_index=0
    - Implement `dismiss_tutorial(user_id, track_id)` — set status='dismissed', reset step_index=0
    - Implement `replay_tutorial(user_id, track_id)` — set status='in_progress', step_index=0
    - Implement `delete_tutorial_progress(user_id)` — delete all records for a user, return count
    - Implement `should_auto_trigger(user_id, track_id)` — return True if no record exists or status='not_started'
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 11.1, 11.2, 11.5, 11.6_

  - [ ]* 3.2 Write property test for auto-trigger correctness
    - **Property 2: Auto-Trigger Correctness**
    - Generate random statuses (None, 'not_started', 'in_progress', 'completed', 'dismissed')
    - Verify auto-trigger returns True only when no record exists OR status='not_started'
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

  - [ ]* 3.3 Write property test for tutorial state persistence round-trip
    - **Property 7: Tutorial State Persistence Round-Trip**
    - Generate random (user_id, track_id, status, step_index) tuples
    - Write to DB and read back, verify identical values
    - **Validates: Requirements 5.2, 6.1, 6.2**

  - [ ]* 3.4 Write property test for UNIQUE constraint on user-track pair
    - **Property 12: UNIQUE Constraint on User-Track Pair**
    - Insert a record, attempt second insert with same (user_id, track_id), verify IntegrityError raised
    - **Validates: Requirements 11.2**

  - [ ]* 3.5 Write property test for upsert behavior
    - **Property 14: Tutorial State Upsert Behavior**
    - Generate (user_id, track_id) pairs, call create_or_update when no record exists (verify creation), call again (verify update without duplicate)
    - **Validates: Requirements 11.5**

  - [ ]* 3.6 Write property test for replay resetting state
    - **Property 10: Replay Resets Tutorial State to Beginning**
    - Generate tracks with status 'completed' or 'dismissed' and random step_index, invoke replay, verify status='in_progress' and step_index=0
    - **Validates: Requirements 7.3, 11.6**

- [ ] 4. Checkpoint - Data layer verification
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Tutorial Flask blueprint
  - [ ] 5.1 Create `src/app/routes/tutorial.py` with blueprint and endpoints
    - Create `tutorial_bp` blueprint with url_prefix='/tutorial'
    - Implement `GET /tutorial/track/<track_id>` — return full step definitions as JSON
    - Implement `POST /tutorial/advance` — advance step index, return `{ok: true, next_page: str|null}`
    - Implement `POST /tutorial/complete` — mark track completed, return `{ok: true}`
    - Implement `POST /tutorial/dismiss` — mark track dismissed, return `{ok: true}`
    - Implement `POST /tutorial/replay` — reset and restart track, return `{ok: true, redirect: str}`
    - Implement `GET /tutorial/state` — fetch current tutorial state for client init
    - All endpoints require `@login_required`
    - Validate track_id is a known track before DB operations
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.3_

  - [ ] 5.2 Register tutorial blueprint in `src/app/__init__.py`
    - Import and register `tutorial_bp` in the app factory
    - _Requirements: 6.1_

  - [ ] 5.3 Add tutorial context processor to `src/app/__init__.py`
    - Implement `inject_tutorial_state()` context processor
    - For authenticated users: fetch all tutorial states, determine if any is 'in_progress', check if any track should auto-trigger
    - Inject `tutorial_active` (active state dict or None) and `tutorial_should_load_alpine` (bool)
    - _Requirements: 2.1, 2.2, 5.4, 9.5_

  - [ ]* 5.4 Write property test for resume prompt logic
    - **Property 8: Resume Prompt Triggers Only for In-Progress State**
    - Generate random statuses, verify resume prompt offered only when status='in_progress'
    - **Validates: Requirements 5.4, 6.5, 6.6**

- [ ] 6. Account lifecycle integration
  - [ ] 6.1 Extend `reset_account()` in `src/app/models.py` to delete tutorial progress
    - Add `DELETE FROM tutorial_progress WHERE user_id = ?` to the reset function
    - _Requirements: 11.3, 11.4_

  - [ ]* 6.2 Write property test for account lifecycle cleanup
    - **Property 13: Account Lifecycle Clears All Tutorial Records**
    - Create user with N tutorial_progress records, call reset, verify zero records remain
    - **Validates: Requirements 11.3, 11.4**

- [ ] 7. Checkpoint - Server-side verification
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Alpine.js tutorial component
  - [ ] 8.1 Create `src/static/js/tutorial.js` with Alpine.js tutorial component
    - Register `Alpine.data('tutorial', ...)` global component
    - Implement reactive state: active, trackId, steps, currentIndex, showOverlay, showConfirmSkip, showResumeToast, highlight position/dimensions, card position
    - Implement `init()` — read tutorial_state from server context, decide auto-trigger or resume toast
    - Implement `startTrack(trackId)` — fetch steps from `/tutorial/track/<id>`, begin overlay
    - Implement `next()` — advance step, POST to server, handle cross-page navigation when routes differ
    - Implement `back()` — go to previous step, handle cross-page navigation
    - Implement `skip()` — show confirmation prompt
    - Implement `confirmSkip()` — POST dismiss, close overlay
    - Implement `finish()` — POST complete, close overlay
    - Implement `resumeTutorial()` — hide toast, show overlay from saved step
    - Implement `dismissResume()` — hide toast, leave tutorial paused
    - _Requirements: 4.3, 4.4, 4.5, 4.6, 5.1, 5.4, 5.5, 6.5, 6.6, 9.1, 9.2, 10.1, 10.5, 10.6_

  - [ ] 8.2 Add highlight positioning and scroll logic to `src/static/js/tutorial.js`
    - Implement `positionHighlight()` — getBoundingClientRect + configurable padding
    - Implement `positionCard()` — place adjacent to highlight on specified side, clamp to viewport bounds
    - Implement `scrollToTarget()` — scrollIntoView if target not in viewport
    - Implement `onHtmxSettle()` — re-query selector, reposition highlight after htmx swaps (debounced)
    - Register `htmx:afterSettle` event listener
    - Handle missing selector case (auto-advance to next step)
    - _Requirements: 3.6, 4.2, 8.1, 8.2, 8.3, 8.4, 8.5, 9.3, 9.6_

  - [ ]* 8.3 Write property test for step card positioning within viewport
    - **Property 4: Step Card Positioning Within Viewport**
    - Generate random highlight positions and viewport dimensions
    - Verify computed card position keeps card entirely within viewport bounds
    - **Validates: Requirements 4.2**

  - [ ]* 8.4 Write property test for navigation button state
    - **Property 5: Navigation Button State Matches Step Position**
    - Generate random track lengths and current step indices
    - Verify Back disabled iff index==0, forward button shows "Finish" iff index==N-1
    - **Validates: Requirements 4.4, 4.6**

  - [ ]* 8.5 Write property test for cross-page navigation
    - **Property 6: Cross-Page Navigation Triggers on Route Mismatch**
    - Generate step arrays with varying routes
    - Verify page navigation triggered when consecutive steps have different routes
    - **Validates: Requirements 5.1, 5.5**

  - [ ]* 8.6 Write property test for highlight box dimensions
    - **Property 11: Highlight Box Dimensions from Target Rect Plus Padding**
    - Generate random bounding rects and padding values
    - Verify highlight dimensions = (top-P, left-P, width+2P, height+2P)
    - **Validates: Requirements 9.6**

- [ ] 9. Tutorial overlay template and CSS
  - [ ] 9.1 Create `src/templates/partials/tutorial_overlay.html`
    - Full-screen backdrop div with `pointer-events: none`
    - Highlight box div with CSS transitions on transform, width, height, opacity
    - Step card with: title, description, step counter ("Step X of Y"), Back/Next/Skip buttons
    - Skip confirmation modal with "End Tutorial" and "Continue" options
    - Resume toast banner (appears with 2s delay)
    - Add `role="dialog"`, `aria-modal="true"`, `aria-labelledby` referencing step title
    - Keyboard: focus trapping within step card, Escape triggers skip confirmation, Tab cycles Back/Next/Skip
    - _Requirements: 3.1, 3.4, 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 10.1, 10.2, 10.3, 10.4, 10.6_

  - [ ] 9.2 Create `src/static/css/tutorial.css`
    - `.tutorial-backdrop` — fixed position, z-index above all content, semi-transparent
    - `.tutorial-highlight` — animated border, box-shadow glow, CSS transitions, `@keyframes tutorial-pulse`
    - `.tutorial-card` — card styling matching OreX design system (font, border-radius, spacing)
    - `.tutorial-toast` — small banner for resume prompt
    - Theme-aware custom properties for colors (standard + advanced theme)
    - Highlight border glow uses primary accent color from active theme
    - Ensure WCAG AA contrast (4.5:1) on step card text
    - _Requirements: 3.2, 3.3, 3.5, 12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ] 9.3 Update `src/templates/base.html` with Alpine.js and tutorial integration
    - Conditionally load Alpine.js CDN script when `tutorial_should_load_alpine` is True
    - Conditionally load `static/js/tutorial.js` when `tutorial_should_load_alpine` is True
    - Include `partials/tutorial_overlay.html` when `tutorial_should_load_alpine` is True
    - _Requirements: 9.1, 9.5_

- [ ] 10. Help page tutorial section
  - [ ] 10.1 Update `src/templates/pages/help.html` with Tutorials section
    - Add "Tutorials" section above the FAQ listing available tracks with status badges (completed/not started/in progress)
    - Show "Replay" button next to tracks with status 'completed' or 'dismissed'
    - Always show Beginner_Tutorial for all players
    - Show Advanced_Tutorial only when `has_advanced_purchased` is True
    - Wire Replay button to POST /tutorial/replay endpoint
    - _Requirements: 7.1, 7.2, 7.4, 7.5, 7.6_

  - [ ]* 10.2 Write property test for Help page track visibility rules
    - **Property 9: Help Page Track Visibility Rules**
    - Generate random advanced_purchased state and track statuses
    - Verify Beginner always visible, Advanced visible iff purchased, Replay shown iff completed/dismissed
    - **Validates: Requirements 7.1, 7.2, 7.4, 7.5, 7.6**

- [ ] 11. Checkpoint - Full feature integration verification
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Write property test for step card rendering
  - [ ]* 12.1 Write property test for step card required information
    - **Property 3: Step Card Contains Required Information**
    - Generate random titles, descriptions, step indices, and total steps
    - Verify rendered output contains title, description, and "Step {I+1} of {N}" progress indicator
    - **Validates: Requirements 4.1**

- [ ] 13. Integration tests
  - [ ]* 13.1 Write integration tests for first-login beginner tutorial flow
    - Register new user → first login → verify Beginner_Tutorial auto-triggers on dashboard
    - Advance through all steps → click Finish → verify DB status='completed'
    - Login again → verify tutorial does NOT auto-trigger
    - _Requirements: 2.1, 2.3, 6.3_

  - [ ]* 13.2 Write integration tests for Advanced tutorial trigger and cross-page navigation
    - Activate Advanced Mode first time → verify Advanced_Tutorial triggers
    - Advance to step on different page → verify page navigation occurs → tutorial resumes on new page
    - Dismiss tutorial → activate Advanced Mode again → verify NOT re-triggered
    - _Requirements: 2.2, 2.4, 5.1, 5.2, 5.3_

  - [ ]* 13.3 Write integration tests for resume and replay flows
    - Start tutorial → navigate away → reload → verify resume toast appears → click resume → overlay shows correct step
    - Complete tutorial → visit Help → click Replay → verify tutorial restarts at step 0
    - _Requirements: 5.4, 6.5, 7.3_

  - [ ]* 13.4 Write integration tests for htmx compatibility and account reset
    - Start tutorial on dashboard → simulate htmx partial update → verify overlay persists and highlight repositions
    - Complete tutorials → reset account → verify all tutorial_progress deleted → first login triggers tutorial again
    - _Requirements: 8.1, 8.4, 11.3_

- [ ] 14. Final checkpoint - Complete test suite passes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (14 properties total)
- Unit tests validate specific examples and edge cases
- Alpine.js is loaded from CDN (already permitted by existing CSP headers)
- The `ON DELETE CASCADE` foreign key on tutorial_progress handles account deletion at DB level
- All tutorial POST endpoints must include CSRF token validation (existing Flask-WTF setup)
- The htmx:afterSettle listener must debounce repositioning to avoid rapid-fire recalculations during multi-swap updates

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3"] },
    { "id": 5, "tasks": ["5.4", "6.1"] },
    { "id": 6, "tasks": ["6.2", "8.1"] },
    { "id": 7, "tasks": ["8.2"] },
    { "id": 8, "tasks": ["8.3", "8.4", "8.5", "8.6", "9.1", "9.2"] },
    { "id": 9, "tasks": ["9.3", "10.1"] },
    { "id": 10, "tasks": ["10.2", "12.1"] },
    { "id": 11, "tasks": ["13.1", "13.2", "13.3", "13.4"] }
  ]
}
```
