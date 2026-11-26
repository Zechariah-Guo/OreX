"""Real-browser tests for the tutorial overlay (headless Chrome/Edge).

These drive the actual page in a browser through the DevTools client in
scripts/screenshot.py, so they cover what the Flask-client tests cannot: the
Alpine component, cross-page hand-off, htmx re-positioning, keyboard handling.

They run against the fixture track in tests/fixtures/tutorial_test_tracks.json
(selectors that exist on today's pages), not the production tutorials.json, so
rewording steps or changing production selectors does not affect them.

Skipped automatically when no Chrome/Edge is installed or the Alpine.js CDN is
unreachable. Deselect explicitly with:  pytest -m "not browser"
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'dev'))
import screenshot as shot  # noqa: E402  (the screenshot tool doubles as the browser driver)

pytestmark = [pytest.mark.browser, pytest.mark.tutorial]

FIXTURE_TRACKS = os.path.join(ROOT, 'tests', 'fixtures', 'tutorial_test_tracks.json')
with open(FIXTURE_TRACKS, encoding='utf-8') as _f:
    BEGINNER_STEPS = json.load(_f)['tracks'][0]['steps']

STATE = "Alpine.$data(document.querySelector('.tutorial-root'))"
PADDING = 8
RESUME_TOAST = '#notification-toasts [data-tutorial-resume]'


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def site():
    """The real app (fixture tracks, throwaway DB) plus a headless browser connected to it."""
    browser_path = shot.find_browser()
    if not browser_path:
        pytest.skip('Chrome/Edge not found')

    tmp = tempfile.mkdtemp(prefix='orex_browser_tests_')
    patcher = pytest.MonkeyPatch()
    server = proc = ws = None
    try:
        from app.config import Config
        import app.market.engine as engine
        db_path = os.path.join(tmp, 'orex.db')
        patcher.setattr(Config, 'DATABASE_PATH', db_path)
        patcher.setattr(Config, 'TUTORIAL_DATA_PATH', FIXTURE_TRACKS)   # absolute path overrides src/
        patcher.setattr(engine, 'start_engine', lambda app: None)

        patcher.setenv('OREX_ALLOW_DEFAULT_SECRET', '1')   # not debug/testing, so allow the dev secret
        patcher.setenv('SESSION_COOKIE_SECURE', '0')       # served over plain http

        from app import create_app
        from werkzeug.serving import make_server
        flask_app = create_app()
        server = make_server('127.0.0.1', 0, flask_app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        debug_port = shot.free_port()
        proc = shot.launch_browser(browser_path, os.path.join(tmp, 'profile'), debug_port)
        ws = shot.connect_to_browser(debug_port)
        cdp = shot.CDP(ws)
        for domain in ('Page', 'Runtime', 'Network', 'Log'):
            cdp.call(f'{domain}.enable')
        cdp.call('Emulation.setDeviceMetricsOverride',
                 {'width': 1280, 'height': 720, 'deviceScaleFactor': 1, 'mobile': False})
        yield SimpleNamespace(app=flask_app, cdp=cdp, db_path=db_path,
                              base=f'http://127.0.0.1:{server.server_port}')
    finally:
        if ws:
            ws.close()
        shot.stop_browser(proc)
        if server:
            server.shutdown()
        patcher.undo()
        shot.remove_dir(tmp)


def run(site, expression):
    return site.cdp.evaluate(expression)


def wait_for(site, expression, timeout=10, what=None):
    """Poll a JavaScript expression until it is truthy (tolerates the page navigating)."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            value = site.cdp.evaluate(expression)
            if value:
                return value
        except (shot.CDPError, TimeoutError) as exc:
            last_error = exc
        time.sleep(0.15)
    raise AssertionError(f'Timed out waiting for {what or expression} (last error: {last_error})')


def wait_step(site, title, timeout=10):
    wait_for(site, (
        f"(() => {{ const d = {STATE}; const s = d.currentStep;"
        " const card = document.querySelector('.tutorial-card');"
        f" return !!(d.showOverlay && d.showCard && !d.busy && s && s.title === {json.dumps(title)}"
        " && card && getComputedStyle(card).display !== 'none'); })()"
    ), timeout, f'the "{title}" step to be shown and settled')
    # "busy" is the component's guard against double clicks while a step change finishes;
    # waiting for it to clear means the next click in a test is a real, accepted one.


def wait_overlay_closed(site, timeout=8):
    wait_for(site, f'!{STATE}.showOverlay', timeout, 'the overlay to close')


def state(site, field):
    return run(site, f'{STATE}.{field}')


def click(site, selector):
    clicked = run(site, f"(() => {{ const e = document.querySelector({json.dumps(selector)});"
                        " if (!e) return false; e.click(); return true; })()")
    assert clicked, f'no element matches {selector}'


def press(site, key, shift=False):
    run(site, f"document.dispatchEvent(new KeyboardEvent('keydown', {{key: {json.dumps(key)},"
              f" shiftKey: {str(shift).lower()}, bubbles: true, cancelable: true}}))")


def card_text(site):
    return run(site, "document.querySelector('.tutorial-card').textContent")


def pathname(site):
    return run(site, 'location.pathname')


def idle(site, seconds=3.5):
    """Wait long enough for the 2s resume-toast delay and any auto-start to have happened."""
    time.sleep(seconds)


def tutorial_absent(site):
    """True when the page rendered no tutorial UI at all (nothing active, nothing to start)."""
    return run(site, "document.querySelector('.tutorial-root') === null")


def db_rows(site, query, params=()):
    conn = sqlite3.connect(site.db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def track_status(site, user, track_id):
    rows = db_rows(site, 'SELECT status, current_step_index FROM tutorial_progress '
                         'WHERE user_id = ? AND track_id = ?', (user.id, track_id))
    return (rows[0]['status'], rows[0]['current_step_index']) if rows else None


def new_user(site, tutorials='completed', advanced=False):
    """Register a fresh user in the browser and put their tutorial state in a known shape.

    tutorials: 'fresh' (nothing recorded, so the beginner tutorial auto-starts),
               'completed' (both tracks done), 'beginner_done' (only beginner done).
    """
    cdp = site.cdp
    cdp.call('Network.clearBrowserCookies')
    cdp.navigate(site.base + '/login')
    run(site, 'sessionStorage.clear()')
    username = 'bt' + uuid.uuid4().hex[:8]
    # The dashboard after registration auto-starts the tutorial. Block those calls: a
    # POST /tutorial/start still in flight could land after the state edits below and
    # leave the track "in progress", so a 'fresh' user would get no auto-start.
    cdp.call('Network.setBlockedURLs', {'urls': ['*/tutorial/*']})
    try:
        shot.register_user(cdp, site.base, username)
        cdp.navigate('about:blank')   # stop the post-registration page's scripts before editing state
    finally:
        cdp.call('Network.setBlockedURLs', {'urls': []})

    user_id = db_rows(site, 'SELECT id FROM users WHERE username = ?', (username,))[0]['id']
    db_rows(site, 'DELETE FROM tutorial_progress WHERE user_id = ?', (user_id,))
    done = {'completed': ('beginner', 'advanced'), 'beginner_done': ('beginner',), 'fresh': ()}[tutorials]
    for track_id in done:
        db_rows(site, "INSERT INTO tutorial_progress (user_id, track_id, status) VALUES (?, ?, 'completed')",
                (user_id, track_id))
    if advanced:
        db_rows(site, 'UPDATE users SET advanced_eligible=1, advanced_purchased=1, advanced_active=1 WHERE id=?',
                (user_id,))
    cdp.reset_diagnostics()
    return SimpleNamespace(id=user_id, name=username)


def jump_to(site, user, index):
    """Open the beginner tutorial directly at a step, as if the player had navigated there with it."""
    site.cdp.navigate(site.base + '/about')          # a page with no tutorial, to set the hand-off flag
    run(site, "sessionStorage.setItem('orex-tutorial-nav', JSON.stringify("
              f"{{track_id: 'beginner', step_index: {index}, ts: Date.now()}}))")
    db_rows(site, "INSERT INTO tutorial_progress (user_id, track_id, status, current_step_index) "
                  "VALUES (?, 'beginner', 'in_progress', ?) ON CONFLICT(user_id, track_id) "
                  "DO UPDATE SET status = 'in_progress', current_step_index = excluded.current_step_index",
            (user.id, index))
    site.cdp.navigate(site.base + BEGINNER_STEPS[index]['route'])


def js_errors(site):
    """Console errors that are not just the browser noting a failed (expected) HTTP response."""
    return [e for e in site.cdp.console_errors if not e.startswith('Failed to load resource')]


# ---------------------------------------------------------------------------
# Auto-start and the step card
# ---------------------------------------------------------------------------

def test_first_login_starts_the_beginner_tutorial(site):
    user = new_user(site, 'fresh')
    site.cdp.navigate(site.base + '/dashboard')
    wait_step(site, 'Fixture Welcome')

    text = card_text(site)
    assert 'Fixture welcome text.' in text and 'Step 1 of 4' in text
    assert track_status(site, user, 'beginner') == ('in_progress', 0)
    # Accessibility contract for the overlay container
    assert run(site, "document.querySelector('.tutorial-overlay').getAttribute('role')") == 'dialog'
    assert run(site, "document.querySelector('.tutorial-overlay').getAttribute('aria-modal')") == 'true'
    # The welcome step has no spotlight; the card is centred
    assert state(site, 'hideHighlight') is True
    assert state(site, 'cardSide') == 'center'
    assert js_errors(site) == []


def test_every_step_shows_its_title_description_and_counter(site):
    """Property 3 / Requirement 5.1: the card shows step info, and steps on other pages navigate there."""
    user = new_user(site, 'fresh')
    site.cdp.navigate(site.base + '/dashboard')
    last = len(BEGINNER_STEPS) - 1
    for i, step in enumerate(BEGINNER_STEPS):
        wait_step(site, step['title'])
        text = card_text(site)
        assert step['description'] in text
        assert f'Step {i + 1} of {len(BEGINNER_STEPS)}' in text
        assert pathname(site) == step['route']                       # followed any cross-page navigation
        assert run(site, "document.querySelector('[data-tutorial-primary]').textContent.trim()") == \
            ('Finish' if i == last else 'Next')
        assert run(site, "document.querySelector('.tutorial-card__actions button').disabled") is (i == 0)
        assert track_status(site, user, 'beginner') == ('in_progress', i)
        if i < last:
            click(site, '[data-tutorial-primary]')
    assert js_errors(site) == []


def test_back_returns_to_the_previous_page(site):
    user = new_user(site)
    jump_to(site, user, 2)                       # first step on /market
    wait_step(site, 'Fixture Market')
    assert pathname(site) == '/market'
    click(site, '.tutorial-card__actions button')  # Back
    wait_step(site, 'Fixture Menu')
    assert pathname(site) == '/dashboard'
    assert track_status(site, user, 'beginner') == ('in_progress', 1)


# ---------------------------------------------------------------------------
# Resume, skip, finish
# ---------------------------------------------------------------------------

def test_leaving_by_hand_offers_a_resume_toast(site):
    user = new_user(site)
    jump_to(site, user, 1)
    wait_step(site, 'Fixture Menu')

    site.cdp.navigate(site.base + '/market')     # navigating without the tutorial controls
    wait_for(site, f"!!document.querySelector({json.dumps(RESUME_TOAST)})", 6, 'the resume toast')
    assert state(site, 'showOverlay') is False   # never resumes automatically
    assert 'Resume your tutorial' in run(site, f"document.querySelector({json.dumps(RESUME_TOAST)}).textContent")

    click(site, RESUME_TOAST)                    # tapping the toast resumes
    wait_step(site, 'Fixture Menu')              # back on the saved step, on its own page
    assert pathname(site) == '/dashboard'

    # Swiping the toast away leaves the tutorial paused (it does not resume)
    site.cdp.navigate(site.base + '/market')
    wait_for(site, f"!!document.querySelector({json.dumps(RESUME_TOAST)})", 6, 'the resume toast')
    run(site, f"document.querySelector({json.dumps(RESUME_TOAST)}).remove()")
    site.cdp.navigate(site.base + '/portfolio')
    idle(site)
    assert state(site, 'showOverlay') is False
    assert track_status(site, user, 'beginner') == ('in_progress', 1)


def test_resume_toast_times_out_but_leaves_the_tutorial_paused(site):
    user = new_user(site)
    # Shorten the auto-hide so the test does not wait the full configured duration
    jump_to(site, user, 1)
    wait_step(site, 'Fixture Menu')
    site.cdp.navigate(site.base + '/market')
    run(site, f"(function(){{var t=document.querySelector({json.dumps(RESUME_TOAST)});"
              " if(t){t.dataset.duration='600';}})()")
    # The toast element appears then auto-dismisses; the tutorial stays paused
    wait_for(site, f"!!document.querySelector({json.dumps(RESUME_TOAST)})", 6, 'the resume toast')
    time.sleep(1.5)
    assert state(site, 'showOverlay') is False
    assert track_status(site, user, 'beginner') == ('in_progress', 1)


def test_tapping_a_dim_panel_advances_like_next(site):
    """Option A: a click anywhere on a dim panel moves to the next step."""
    new_user(site, 'fresh')
    site.cdp.navigate(site.base + '/dashboard')
    wait_step(site, 'Fixture Welcome')
    assert state(site, 'hideHighlight') is True          # welcome step has no spotlight
    # Click a dim panel (the full-screen top panel covers everything on a no-highlight step)
    click(site, '.tutorial-panel')
    wait_step(site, 'Fixture Menu')
    assert state(site, 'currentIndex') == 1
    # Advancing again crosses to the next page
    click(site, '.tutorial-panel')
    wait_step(site, 'Fixture Market')
    assert pathname(site) == '/market'


def test_no_highlight_step_dims_the_whole_screen(site):
    """A step with highlight:none collapses the spotlight to a zero-size hole at the
    screen centre, so the four panels together cover the whole viewport and no frame
    shows. (The centred hole lets the spotlight zoom open/closed on neighbouring steps.)"""
    new_user(site, 'fresh')
    site.cdp.navigate(site.base + '/dashboard')
    wait_step(site, 'Fixture Welcome')
    # The highlight frame is hidden and the component reports no spotlight
    assert run(site, "getComputedStyle(document.querySelector('.tutorial-highlight')).opacity") == '0'
    assert run(site, STATE + ".hideHighlight") is True
    # Every pixel of the viewport is covered by some panel (sample a grid of points)
    uncovered = run(site,
                    "(function(){var panels=[].slice.call(document.querySelectorAll('.tutorial-panel'));"
                    " var vw=window.innerWidth, vh=window.innerHeight, miss=0;"
                    " for(var x=20;x<vw;x+=120){for(var y=20;y<vh;y+=120){"
                    "   var cx=x,cy=y;"
                    "   var hit=panels.some(function(p){var r=p.getBoundingClientRect();"
                    "     return cx>=r.left&&cx<=r.right&&cy>=r.top&&cy<=r.bottom&&r.width>0&&r.height>0;});"
                    "   if(!hit)miss++;}}return miss;})()")
    assert uncovered == 0


def test_spotlight_leaves_the_target_undimmed(site):
    """On a normal step the four panels surround the target, leaving a transparent hole over it."""
    user = new_user(site)
    jump_to(site, user, 2)                       # 'Fixture Market', targets 'main h1'
    wait_step(site, 'Fixture Market')
    hole = run(site,
               "(function(){var d=" + STATE + ";"
               " var panels=[].slice.call(document.querySelectorAll('.tutorial-panel'));"
               " var el=document.querySelector('main h1'); var r=el.getBoundingClientRect();"
               " var cx=r.left+r.width/2, cy=r.top+r.height/2;"
               " var covered=panels.some(function(p){var q=p.getBoundingClientRect();"
               "   return cx>=q.left&&cx<=q.right&&cy>=q.top&&cy<=q.bottom&&q.width>0&&q.height>0;});"
               " return {covered: covered, hidden: d.hideHighlight};})()")
    assert hole['covered'] is False and hole['hidden'] is False


def test_clicking_the_highlighted_target_advances_and_does_not_interact(site):
    """The spotlight hole is still visually undimmed, but a transparent catcher
    covers it so the highlighted element is NOT interactive during the tour: a
    click at the target's centre hits the overlay catcher and advances the tour,
    rather than activating the underlying element."""
    user = new_user(site)
    jump_to(site, user, 2)                        # 'Fixture Market', targets 'main h1'
    wait_step(site, 'Fixture Market')

    # The element at the target's centre point is the tutorial catcher/overlay,
    # not the page element underneath — so clicks can't reach the page.
    topmost_class = run(site,
        "(function(){var el=document.querySelector('main h1');var r=el.getBoundingClientRect();"
        " var hit=document.elementFromPoint(r.left+r.width/2, r.top+r.height/2);"
        " return hit ? hit.className : null;})()")
    assert topmost_class is not None
    assert 'tutorial' in topmost_class            # overlay element, not the page's h1

    # Clicking at the target centre advances the tour (same as tapping a panel).
    run(site,
        "(function(){var el=document.querySelector('main h1');var r=el.getBoundingClientRect();"
        " var hit=document.elementFromPoint(r.left+r.width/2, r.top+r.height/2); hit.click();})()")
    wait_step(site, 'Fixture Footer')
    assert state(site, 'currentIndex') == 3


def test_skipping_asks_first_then_dismisses_for_good(site):
    user = new_user(site, 'fresh')
    site.cdp.navigate(site.base + '/dashboard')
    wait_step(site, 'Fixture Welcome')

    press(site, 'Escape')                                     # Escape asks, it does not end the tutorial
    wait_for(site, f'{STATE}.showConfirmSkip', 5, 'the skip confirmation')
    assert state(site, 'showOverlay') is True
    wait_for(site, "document.activeElement.textContent.trim() === 'Continue'", 5, 'focus on "Continue"')
    press(site, 'Escape')                                     # Escape again goes back to the step
    wait_for(site, f'!{STATE}.showConfirmSkip', 5, 'the confirmation to close')
    assert state(site, 'showOverlay') is True

    click(site, '.tutorial-card__skip')
    wait_for(site, f'{STATE}.showConfirmSkip', 5, 'the skip confirmation')
    click(site, '.tutorial-confirm .tutorial-btn--primary')   # Continue
    wait_for(site, f'!{STATE}.showConfirmSkip', 5, 'the confirmation to close')
    assert track_status(site, user, 'beginner') == ('in_progress', 0)

    click(site, '.tutorial-card__skip')
    wait_for(site, f'{STATE}.showConfirmSkip', 5, 'the skip confirmation')
    click(site, '.tutorial-confirm .tutorial-btn--secondary')  # End Tutorial
    wait_overlay_closed(site)
    deadline = time.time() + 5
    while track_status(site, user, 'beginner') != ('dismissed', 0) and time.time() < deadline:
        time.sleep(0.2)
    assert track_status(site, user, 'beginner') == ('dismissed', 0)

    site.cdp.navigate(site.base + '/dashboard')               # does not come back by itself
    idle(site)
    assert tutorial_absent(site)


def test_finishing_completes_the_tutorial(site):
    user = new_user(site, 'fresh')
    site.cdp.navigate(site.base + '/dashboard')
    for step in BEGINNER_STEPS[:-1]:
        wait_step(site, step['title'])
        click(site, '[data-tutorial-primary]')
    wait_step(site, BEGINNER_STEPS[-1]['title'])
    assert run(site, "document.querySelector('[data-tutorial-primary]').textContent.trim()") == 'Finish'
    click(site, '[data-tutorial-primary]')
    wait_overlay_closed(site)

    deadline = time.time() + 5
    while track_status(site, user, 'beginner') != ('completed', 0) and time.time() < deadline:
        time.sleep(0.2)
    assert track_status(site, user, 'beginner') == ('completed', 0)
    site.cdp.navigate(site.base + '/dashboard')
    idle(site)
    assert tutorial_absent(site)
    assert js_errors(site) == []


# ---------------------------------------------------------------------------
# htmx compatibility and keyboard handling
# ---------------------------------------------------------------------------

def highlight_error(site, selector):
    """Largest difference (px) between the highlight box and the target's rect plus padding."""
    return run(site, (
        f"(() => {{ const d = {STATE}; const el = document.querySelector({json.dumps(selector)});"
        " if (!el) return null; const r = el.getBoundingClientRect(); const p = d.padding;"
        " return Math.max(Math.abs(d.highlightTop - (r.top - p)), Math.abs(d.highlightLeft - (r.left - p)),"
        " Math.abs(d.highlightWidth - (r.width + 2 * p)), Math.abs(d.highlightHeight - (r.height + 2 * p))); })()"
    ))


def settle_htmx(site):
    run(site, "document.body.dispatchEvent(new CustomEvent('htmx:afterSettle', {bubbles: true}))")


def test_overlay_survives_htmx_swaps_and_follows_the_target(site):
    user = new_user(site)
    jump_to(site, user, 2)                       # targets "main h1" on /market
    wait_step(site, 'Fixture Market')
    assert highlight_error(site, 'main h1') < 1.5
    assert state(site, 'padding') == PADDING

    # The target moves (as after a partial re-render): the highlight follows, the overlay never closes
    before = state(site, 'highlightTop')
    run(site, "document.querySelector('main h1').style.marginTop = '80px'")
    settle_htmx(site)
    deadline = time.time() + 5
    while time.time() < deadline and abs(state(site, 'highlightTop') - before) < 60:
        time.sleep(0.15)
    assert abs(state(site, 'highlightTop') - before) >= 60
    assert highlight_error(site, 'main h1') < 1.5
    assert state(site, 'showOverlay') is True

    # The target disappears for good: move on to the next step (Requirement 8.5)
    run(site, "document.querySelector('main h1').remove()")
    settle_htmx(site)
    wait_step(site, 'Fixture Footer', timeout=8)
    assert track_status(site, user, 'beginner') == ('in_progress', 3)


def test_tab_stays_inside_the_card_and_the_confirmation(site):
    new_user(site, 'fresh')
    site.cdp.navigate(site.base + '/dashboard')
    wait_step(site, 'Fixture Welcome')
    wait_for(site, "document.activeElement.hasAttribute('data-tutorial-primary')", 5, 'focus on the Next button')

    # On the first step Back is disabled, so Next is the first stop and Skip the last
    run(site, "document.querySelector('.tutorial-card__skip').focus()")
    press(site, 'Tab')
    assert run(site, "document.activeElement.hasAttribute('data-tutorial-primary')") is True
    press(site, 'Tab', shift=True)
    assert run(site, "document.activeElement.classList.contains('tutorial-card__skip')") is True

    click(site, '.tutorial-card__skip')
    wait_for(site, f'{STATE}.showConfirmSkip', 5, 'the skip confirmation')
    wait_for(site, "!!document.activeElement.closest('.tutorial-confirm')", 5, 'focus inside the confirmation')
    for _ in range(5):
        press(site, 'Tab')
        assert run(site, "!!document.activeElement.closest('.tutorial-confirm')") is True


# ---------------------------------------------------------------------------
# Advanced tutorial, account reset, Help page Replay
# ---------------------------------------------------------------------------

def test_short_tab_reveal_shows_the_hidden_short_form(site):
    """A reveal:short-tab step must switch the ore page to the Short tab so its
    (normally hidden) target becomes visible and the step shows instead of skipping."""
    user = new_user(site, 'beginner_done', advanced=True)
    # Jump straight onto the fixture advanced track's short-tab step (index 1)
    site.cdp.navigate(site.base + '/about')
    run(site, "sessionStorage.setItem('orex-tutorial-nav', JSON.stringify("
              "{track_id: 'advanced', step_index: 1, ts: Date.now()}))")
    db_rows(site, "INSERT INTO tutorial_progress (user_id, track_id, status, current_step_index) "
                  "VALUES (?, 'advanced', 'in_progress', 1) ON CONFLICT(user_id, track_id) "
                  "DO UPDATE SET status='in_progress', current_step_index=1", (user.id,))
    site.cdp.navigate(site.base + '/market/1')

    wait_step(site, 'Fixture Short')
    # The Short tab is now active and its form is visible (not display:none)
    assert run(site, "document.querySelector('#trade-tab-short').classList.contains('trade-tab-content--active')") is True
    assert run(site, "document.querySelector('#short-order-form').getClientRects().length > 0") is True
    # The spotlight sits on the short form
    assert highlight_error(site, '#short-order-form') < 2.0


def _demo_short_count(site, user):
    return db_rows(site, "SELECT COUNT(*) AS n FROM short_positions "
                         "WHERE user_id = ? AND is_demo = 1", (user.id,))[0]['n']


def test_demo_short_opens_on_its_step_populates_shorts_tab_and_clears_on_finish(site):
    """The demo-short-open action opens a tutorial short when its step is reached,
    the portfolio shorts tab then shows a live row, and finishing the tour removes it
    with the balance unchanged (no money glitch)."""
    user = new_user(site, 'beginner_done', advanced=True)
    db_rows(site, 'UPDATE users SET balance = 1000000 WHERE id = ?', (user.id,))
    balance_before = db_rows(site, 'SELECT balance FROM users WHERE id = ?', (user.id,))[0]['balance']

    site.cdp.navigate(site.base + '/dashboard')
    wait_step(site, 'Fixture Advanced Welcome')
    assert _demo_short_count(site, user) == 0          # not opened before its step

    # Advance to the short step (index 1): its action opens the demo short
    click(site, '.tutorial-panel')
    wait_step(site, 'Fixture Short')
    assert pathname(site) == '/market/1'
    deadline = time.time() + 5
    while _demo_short_count(site, user) == 0 and time.time() < deadline:
        time.sleep(0.2)
    assert _demo_short_count(site, user) == 1          # opened exactly once

    # Advance to the portfolio shorts tab: it is revealed and shows the demo row
    click(site, '.tutorial-panel')
    wait_step(site, 'Fixture Shorts Tab')
    assert pathname(site) == '/portfolio'
    assert run(site, "document.querySelector('#portfolio-tab-shorts')"
                     ".classList.contains('portfolio-tab-content--active')") is True
    assert run(site, "document.querySelectorAll('#portfolio-tab-shorts .shorts-table tbody tr').length") >= 1

    # Finish: the demo short is cleared and the balance is exactly as it started
    click(site, '.tutorial-panel')                      # -> Fixture Advanced End (last step)
    wait_step(site, 'Fixture Advanced End')
    click(site, '[data-tutorial-primary]')              # Finish
    wait_overlay_closed(site)

    deadline = time.time() + 5
    while _demo_short_count(site, user) > 0 and time.time() < deadline:
        time.sleep(0.2)
    assert _demo_short_count(site, user) == 0
    balance_after = db_rows(site, 'SELECT balance FROM users WHERE id = ?', (user.id,))[0]['balance']
    assert round(balance_after, 2) == round(balance_before, 2)
    assert js_errors(site) == []


def test_navigating_away_mid_tour_clears_the_demo_short(site):
    """Leaving the page outside a tour hop (user wanders off) fires the pagehide
    beacon that clears the demo short — it must not linger once the tour is off screen."""
    user = new_user(site, 'beginner_done', advanced=True)
    db_rows(site, 'UPDATE users SET balance = 1000000 WHERE id = ?', (user.id,))

    site.cdp.navigate(site.base + '/dashboard')
    wait_step(site, 'Fixture Advanced Welcome')
    click(site, '.tutorial-panel')                       # -> Fixture Short (opens demo short)
    wait_step(site, 'Fixture Short')
    deadline = time.time() + 5
    while _demo_short_count(site, user) == 0 and time.time() < deadline:
        time.sleep(0.2)
    assert _demo_short_count(site, user) == 1

    # Wander off to an unrelated page WITHOUT the tour's nav hand-off flag set
    # (a real user clicking a nav link, not the tour's Next). The pagehide beacon
    # should clear the demo short as the page unloads.
    run(site, "sessionStorage.removeItem('orex-tutorial-nav')")
    site.cdp.navigate(site.base + '/about')
    deadline = time.time() + 6
    while _demo_short_count(site, user) > 0 and time.time() < deadline:
        time.sleep(0.2)
    assert _demo_short_count(site, user) == 0


def test_advanced_tutorial_starts_once(site):
    user = new_user(site, 'beginner_done', advanced=True)
    site.cdp.navigate(site.base + '/dashboard')
    wait_step(site, 'Fixture Advanced Welcome')
    assert track_status(site, user, 'advanced') == ('in_progress', 0)

    press(site, 'Escape')
    wait_for(site, f'{STATE}.showConfirmSkip', 5, 'the skip confirmation')
    click(site, '.tutorial-confirm .tutorial-btn--secondary')
    wait_overlay_closed(site)
    deadline = time.time() + 5
    while track_status(site, user, 'advanced') != ('dismissed', 0) and time.time() < deadline:
        time.sleep(0.2)
    assert track_status(site, user, 'advanced') == ('dismissed', 0)

    # Turning Advanced Mode off and on again does not restart it (Requirement 2.4)
    db_rows(site, 'UPDATE users SET advanced_active = 0 WHERE id = ?', (user.id,))
    db_rows(site, 'UPDATE users SET advanced_active = 1 WHERE id = ?', (user.id,))
    site.cdp.navigate(site.base + '/dashboard')
    idle(site)
    assert tutorial_absent(site)


def test_account_reset_does_not_start_the_tutorial_again(site):
    user = new_user(site, 'completed')
    site.cdp.navigate(site.base + '/dashboard')
    idle(site, 2)
    assert tutorial_absent(site)

    with site.app.app_context():
        from app.models import reset_account
        reset_account(user.id)
        # reset_account signs other sessions out; the settings route re-issues the
        # current one. Undo the bump here so the open browser stays signed in.
        from app.database import get_db
        get_db().execute('UPDATE users SET session_version = session_version - 1 WHERE id = ?', (user.id,))
        get_db().commit()
    assert db_rows(site, 'SELECT COUNT(*) AS n FROM tutorial_progress WHERE user_id = ?', (user.id,))[0]['n'] > 0

    site.cdp.navigate(site.base + '/dashboard')
    idle(site, 2)
    assert tutorial_absent(site)


def test_help_page_replay_restarts_the_tutorial(site):
    user = new_user(site, 'completed')
    site.cdp.navigate(site.base + '/help')
    assert run(site, "document.querySelectorAll('[data-tutorial-replay]').length") >= 1
    assert run(site, "document.querySelector('[data-tutorial-replay=\"beginner\"]').textContent.trim()") == 'Replay'
    click(site, '[data-tutorial-replay="beginner"]')

    wait_step(site, 'Fixture Welcome')            # straight into the overlay, not the resume toast
    assert pathname(site) == '/dashboard'
    assert run(site, f"!document.querySelector({json.dumps(RESUME_TOAST)})")  # no resume toast shown
    assert track_status(site, user, 'beginner') == ('in_progress', 0)


def test_help_page_resume_recovers_an_in_progress_tutorial(site):
    """Dead-end guard: an in-progress tutorial whose resume toast was dismissed/expired
    must still be reachable from Help via a 'Resume' button, continuing at the saved step."""
    user = new_user(site)
    # Pause the tutorial partway through, on the Market step
    jump_to(site, user, 2)
    wait_step(site, 'Fixture Market')
    assert track_status(site, user, 'beginner') == ('in_progress', 2)

    # Simulate the resume toast having been offered already this session
    run(site, "sessionStorage.setItem('orex-tutorial-resume-dismissed', 'beginner')")

    # Go to Help: the in-progress track shows both Resume and Replay buttons
    site.cdp.navigate(site.base + '/help')
    labels = run(site, "[].slice.call(document.querySelectorAll('[data-tutorial-replay=\"beginner\"]'))"
                       ".map(function(b){return b.textContent.trim();})")
    assert labels == ['Resume', 'Replay']

    # Resume continues at the saved step (not step 0)
    click(site, "[data-tutorial-replay=\"beginner\"][data-tutorial-restart=\"false\"]")
    wait_step(site, 'Fixture Market')
    assert track_status(site, user, 'beginner') == ('in_progress', 2)
    assert run(site, f"!document.querySelector({json.dumps(RESUME_TOAST)})")


def test_help_page_replay_restarts_an_in_progress_tutorial(site):
    """The Replay button on an in-progress track restarts it from step 0."""
    user = new_user(site)
    jump_to(site, user, 2)
    wait_step(site, 'Fixture Market')
    assert track_status(site, user, 'beginner') == ('in_progress', 2)

    site.cdp.navigate(site.base + '/help')
    # Replay forces a restart at step 0
    click(site, "[data-tutorial-replay=\"beginner\"][data-tutorial-restart=\"true\"]")
    wait_step(site, 'Fixture Welcome')
    assert track_status(site, user, 'beginner') == ('in_progress', 0)
