# Requirements Document

## Introduction

The Tutorial System is an interactive guided walkthrough feature for OreX that onboards new players and introduces advanced players to expanded mechanics. It provides two distinct tutorial tracks — a Beginner Tutorial triggered on first login and an Advanced Tutorial triggered on first Advanced Mode activation — each consisting of step-by-step highlight overlays that animate toward target UI elements on the actual game pages. The system uses an animated lightbox approach with smooth CSS transitions to draw attention to specific buttons, panels, and chart areas, delivering a React-like interactive feel within the existing htmx + Jinja2 stack. Players can skip, dismiss, or replay tutorials from the Help section in the profile dropdown.

## Glossary

- **Tutorial_System**: The overall infrastructure responsible for managing tutorial tracks, step progression, overlay rendering, state persistence, and replay functionality
- **Tutorial_Track**: A named, ordered sequence of Tutorial_Steps that together form a complete guided walkthrough (e.g., Beginner_Tutorial or Advanced_Tutorial)
- **Tutorial_Step**: A single instructional unit within a Tutorial_Track containing: a target element selector, instructional text, page context, highlight position, and optional action prompt
- **Beginner_Tutorial**: A Tutorial_Track covering core gameplay basics (dashboard, market, trading, portfolio, leaderboard) triggered on a player's first login
- **Advanced_Tutorial**: A Tutorial_Track covering advanced mechanics (finances page, shorting, stop loss/take profit, chart overlays, risk management) triggered when a player first activates Advanced_Mode
- **Tutorial_Overlay**: A full-screen semi-transparent backdrop rendered on top of existing page content that isolates and highlights the current Tutorial_Step's target element
- **Highlight_Box**: An animated visual frame that transitions (shrinks, moves, fades) to surround and emphasize the target DOM element for the current Tutorial_Step
- **Target_Element**: The specific DOM element on a page that a Tutorial_Step references via a CSS selector, to which the Highlight_Box animates
- **Step_Card**: A floating instructional panel displayed alongside the Highlight_Box containing the step's title, description text, step counter, and navigation controls (Next, Back, Skip)
- **Tutorial_State**: A persistent record per player per Tutorial_Track storing: completion status, current step index, and whether the tutorial has been dismissed
- **Alpine_Component**: A client-side Alpine.js component managing tutorial overlay rendering, step transitions, and animation orchestration
- **Help_Page**: The existing help page at `/help` accessible from the Profile_Menu where players can access tutorial replay options
- **Advanced_Mode**: The gated prestige tier (purchased for $50,000 after reaching $100,000 net worth) that unlocks advanced trading mechanics
- **Tick_Engine**: The background market engine that updates ore prices every 20 seconds, which may cause htmx partial re-renders during a tutorial
- **Profile_Menu**: The navigation dropdown providing access to Profile, Settings, Help, and logout

## Requirements

### Requirement 1: Tutorial Track Definitions and Step Data

**User Story:** As a developer, I want tutorial tracks and steps defined as structured data, so that content can be maintained and extended without changing application logic.

#### Acceptance Criteria

1. THE Tutorial_System SHALL define each Tutorial_Track as a JSON-serializable data structure containing: a unique track identifier, a display name, an ordered array of Tutorial_Steps, and the trigger condition for automatic activation
2. THE Tutorial_System SHALL define each Tutorial_Step with the following fields: step index, target element CSS selector, target page route, step title, description text, highlight position (top, bottom, left, right, or center relative to target), and an optional action description prompting the player to interact
3. THE Beginner_Tutorial SHALL contain steps covering: welcome introduction, dashboard overview (balance and net worth display), market page navigation, ore detail page (price chart reading), executing a buy/sell trade, portfolio holdings overview, and leaderboard competition explanation
4. THE Advanced_Tutorial SHALL contain steps covering: Advanced Mode welcome, finances page capital breakdown, opening a short position, collateral and fee mechanics, setting stop loss and take profit orders, resistance and support chart overlays, and the cash runway risk indicator
5. THE Tutorial_System SHALL store track and step definitions server-side so that content changes do not require client-side code deployment

### Requirement 2: Automatic Tutorial Triggering

**User Story:** As a player, I want the appropriate tutorial to start automatically at the right moment, so that I receive guidance exactly when I need it without seeking it out.

#### Acceptance Criteria

1. WHEN a player logs in for the first time (account has zero prior logins recorded), THE Tutorial_System SHALL automatically initiate the Beginner_Tutorial on the dashboard page
2. WHEN a player activates Advanced_Mode for the first time (toggling from inactive to active with no prior Advanced_Tutorial completion), THE Tutorial_System SHALL automatically initiate the Advanced_Tutorial on the current page
3. THE Tutorial_System SHALL NOT automatically trigger a Tutorial_Track that the player has previously completed or dismissed
4. THE Tutorial_System SHALL NOT automatically trigger the Advanced_Tutorial on subsequent Advanced_Mode activations after the first
5. WHEN a tutorial is automatically triggered, THE Tutorial_System SHALL display the first Tutorial_Step within 500 milliseconds of the triggering page load completing

### Requirement 3: Tutorial Overlay and Highlight Animation

**User Story:** As a player, I want the tutorial highlights to animate smoothly toward target elements, so that the experience feels polished and engaging rather than static popup tooltips.

#### Acceptance Criteria

1. WHEN a Tutorial_Step is displayed, THE Tutorial_Overlay SHALL render a full-screen semi-transparent backdrop (opacity between 0.4 and 0.6) covering all page content except the Target_Element
2. WHEN a Tutorial_Step is displayed, THE Highlight_Box SHALL animate from an expanded state to tightly surround the Target_Element using a CSS transition with a duration between 300 and 500 milliseconds and an easing function
3. WHEN transitioning between Tutorial_Steps on the same page, THE Highlight_Box SHALL animate its position and dimensions smoothly from the previous Target_Element to the next Target_Element without flickering or disappearing
4. THE Tutorial_Overlay SHALL use CSS pointer-events to allow the player to interact with the highlighted Target_Element while blocking interaction with all other page elements
5. THE Highlight_Box SHALL include a subtle pulsing or glowing animation on the border to draw continued attention to the target element
6. WHEN a Tutorial_Step targets an element that is not currently visible in the viewport, THE Tutorial_System SHALL scroll the page smoothly to bring the Target_Element into view before animating the Highlight_Box

### Requirement 4: Step Card Display and Navigation

**User Story:** As a player, I want clear instructional text and navigation controls at each step, so that I understand what I am looking at and can move through the tutorial at my own pace.

#### Acceptance Criteria

1. THE Step_Card SHALL display the current step's title, description text, and a step counter showing progress (e.g., "Step 3 of 7")
2. THE Step_Card SHALL position itself adjacent to the Highlight_Box on the side specified by the Tutorial_Step's highlight position field, avoiding overflow beyond the viewport edges
3. THE Step_Card SHALL include a "Next" button that advances to the next Tutorial_Step in the track
4. THE Step_Card SHALL include a "Back" button that returns to the previous Tutorial_Step (disabled on the first step)
5. THE Step_Card SHALL include a "Skip" button that dismisses the entire tutorial with a confirmation prompt
6. WHEN the player reaches the final step in a Tutorial_Track, THE Step_Card SHALL replace the "Next" button with a "Finish" button that completes the tutorial
7. THE Step_Card SHALL animate its appearance with a fade-in transition when a new step is displayed

### Requirement 5: Cross-Page Step Navigation

**User Story:** As a player, I want the tutorial to guide me across different pages when steps require it, so that the walkthrough covers the full game experience without breaking.

#### Acceptance Criteria

1. WHEN the next Tutorial_Step targets a different page route than the current page, THE Tutorial_System SHALL navigate the player to the target page before rendering the step's highlight
2. WHEN navigating to a new page for a Tutorial_Step, THE Tutorial_System SHALL persist the active tutorial state (current track and step index) so the tutorial resumes on the destination page after load
3. WHEN a tutorial-driven page navigation completes, THE Tutorial_System SHALL wait for the page to fully render (DOM ready) before displaying the next Tutorial_Step overlay
4. WHEN the player manually navigates away from the tutorial's expected page without using tutorial controls, THE Tutorial_System SHALL pause the tutorial and display a non-intrusive prompt offering to resume or dismiss
5. THE Tutorial_System SHALL support the "Back" button navigating to the previous page when the prior step was on a different route

### Requirement 6: Tutorial State Persistence

**User Story:** As a player, I want my tutorial progress saved, so that I can resume where I left off if I close the browser or navigate away.

#### Acceptance Criteria

1. THE Tutorial_System SHALL store Tutorial_State per player per Tutorial_Track in the database with fields: track_id (TEXT), current_step_index (INTEGER), status (TEXT: "not_started", "in_progress", "completed", "dismissed"), and last_updated (TEXT, ISO 8601 datetime)
2. WHEN a player advances to a new Tutorial_Step, THE Tutorial_System SHALL update the current_step_index in the player's Tutorial_State
3. WHEN a player completes a Tutorial_Track (clicks "Finish" on the last step), THE Tutorial_System SHALL set the Tutorial_State status to "completed"
4. WHEN a player dismisses a Tutorial_Track via the "Skip" button, THE Tutorial_System SHALL set the Tutorial_State status to "dismissed"
5. WHEN a player with an "in_progress" Tutorial_State loads any page, THE Tutorial_System SHALL offer to resume the tutorial from the saved step via a non-intrusive toast notification
6. THE Tutorial_System SHALL NOT resume a paused tutorial automatically — the player must opt in via the resume prompt

### Requirement 7: Tutorial Replay from Help Page

**User Story:** As a player, I want to replay tutorials from the Help section, so that I can revisit guidance anytime I need a refresher.

#### Acceptance Criteria

1. THE Help_Page SHALL display a "Tutorials" section listing all Tutorial_Tracks available to the player with their completion status
2. THE Help_Page SHALL display a "Replay" button next to each Tutorial_Track that the player has previously completed or dismissed
3. WHEN a player clicks "Replay" on a Tutorial_Track, THE Tutorial_System SHALL reset that track's Tutorial_State to "in_progress" with current_step_index of 0 and initiate the tutorial from the first step
4. THE Help_Page SHALL display the Beginner_Tutorial as replayable for all players
5. WHILE Advanced_Mode has never been purchased by a player, THE Help_Page SHALL NOT display the Advanced_Tutorial in the tutorials section
6. WHILE Advanced_Mode has been purchased (regardless of current active state), THE Help_Page SHALL display the Advanced_Tutorial as replayable

### Requirement 8: Compatibility with htmx Partial Updates

**User Story:** As a player, I want the tutorial overlay to remain stable when the page updates via htmx polling, so that a background price tick does not break or dismiss my active tutorial step.

#### Acceptance Criteria

1. WHEN an htmx partial update re-renders a section of the page containing the current Target_Element, THE Tutorial_System SHALL re-acquire the Target_Element reference and reposition the Highlight_Box after the DOM update completes
2. WHEN an htmx partial update removes the current Target_Element from the DOM, THE Tutorial_System SHALL reposition the Highlight_Box to the re-rendered element matching the same CSS selector once the swap completes
3. THE Tutorial_System SHALL listen for htmx lifecycle events (htmx:afterSwap or htmx:afterSettle) to detect DOM changes and adjust overlay positioning accordingly
4. THE Tutorial_Overlay SHALL remain rendered and visible during htmx partial page updates without flickering or momentary disappearance
5. IF an htmx partial update causes the Target_Element's CSS selector to no longer match any element on the page, THEN THE Tutorial_System SHALL advance to the next step automatically and log a warning for debugging

### Requirement 9: Alpine.js Integration and Animation Engine

**User Story:** As a developer, I want the tutorial overlay managed by Alpine.js components, so that animations are reactive, declarative, and maintain React-like interactivity within the htmx stack.

#### Acceptance Criteria

1. THE Tutorial_System SHALL use Alpine.js as the client-side framework for managing tutorial overlay state, step transitions, and animation triggers
2. THE Alpine_Component SHALL manage the following reactive state: active tutorial track, current step data, overlay visibility, highlight box position/dimensions, and step card position
3. THE Alpine_Component SHALL use CSS transitions (transform, opacity, width, height) for all Highlight_Box animations rather than JavaScript-driven frame-by-frame animation
4. THE Alpine_Component SHALL use Alpine.js x-transition directives for Step_Card enter/leave animations
5. THE Tutorial_System SHALL load Alpine.js only on pages where a tutorial is active or could be triggered, to avoid unnecessary payload on pages with no tutorial relevance
6. THE Alpine_Component SHALL calculate Highlight_Box position by reading the Target_Element's bounding rectangle (getBoundingClientRect) and applying a configurable padding (default 8 pixels)

### Requirement 10: Skip, Dismiss, and Accessibility

**User Story:** As a player, I want full control over dismissing or skipping the tutorial, and I want the overlay to be keyboard accessible, so that the tutorial enhances my experience without trapping me.

#### Acceptance Criteria

1. WHEN a player presses the Escape key while a Tutorial_Overlay is active, THE Tutorial_System SHALL display the skip confirmation prompt (same behavior as clicking "Skip")
2. THE Step_Card SHALL be keyboard-navigable with Tab key cycling through the "Back", "Next"/"Finish", and "Skip" buttons in logical order
3. THE Tutorial_Overlay SHALL set aria-modal="true" and role="dialog" on the overlay container, with aria-labelledby referencing the current step title
4. THE Step_Card SHALL apply focus trapping so that keyboard focus does not escape to elements behind the overlay (except the highlighted Target_Element)
5. THE Tutorial_System SHALL NOT prevent the player from using browser navigation (back button, URL bar) to leave the tutorial at any time
6. WHEN the skip confirmation prompt is displayed, THE Tutorial_System SHALL offer two options: "End Tutorial" (sets status to "dismissed") and "Continue" (returns to the current step)

### Requirement 11: Tutorial Data Model

**User Story:** As a developer, I want a clear database schema for tutorial state, so that progress tracking is reliable across sessions and account lifecycle events.

#### Acceptance Criteria

1. THE Tutorial_System SHALL store tutorial progress in a `tutorial_progress` table with columns: id (INTEGER PRIMARY KEY), user_id (INTEGER NOT NULL, FOREIGN KEY to users), track_id (TEXT NOT NULL), current_step_index (INTEGER NOT NULL DEFAULT 0), status (TEXT NOT NULL DEFAULT "not_started"), last_updated (TEXT NOT NULL DEFAULT datetime('now'))
2. THE Tutorial_System SHALL enforce a UNIQUE constraint on the combination of user_id and track_id to prevent duplicate progress records
3. WHEN a player resets their account, THE Tutorial_System SHALL delete all tutorial_progress records for that player (allowing tutorials to re-trigger on the fresh account)
4. WHEN a player deletes their account, THE Tutorial_System SHALL delete all tutorial_progress records for that player
5. THE Tutorial_System SHALL create a tutorial_progress record with status "in_progress" when a tutorial is first triggered, and update the existing record on subsequent state changes
6. WHEN a Tutorial_Track reaches status "completed" or "dismissed", THE Tutorial_System SHALL reset the current_step_index to 0 so that any future replay starts from the first step

### Requirement 12: Visual Design and Theming

**User Story:** As a player, I want the tutorial overlay to be visually cohesive with the rest of OreX regardless of my current theme, so that it feels like a native part of the game.

#### Acceptance Criteria

1. THE Tutorial_Overlay backdrop SHALL use a dark semi-transparent color that works with both light and dark themes (adapting opacity or color to maintain readability)
2. THE Step_Card SHALL use the same font family, border radius, and spacing conventions as other OreX card components
3. THE Highlight_Box border glow SHALL use the application's primary accent color from the active theme (standard or OreX_Advanced_Theme)
4. WHILE the OreX_Advanced_Theme is active, THE Tutorial_Overlay and Step_Card SHALL adopt the advanced theme's color palette and styling
5. THE Step_Card SHALL be readable with sufficient contrast ratios (minimum WCAG AA 4.5:1 for body text) against its background regardless of the active theme

