"""Integration tests for the Tutorial System using the Flask test client.

Covers the HTTP endpoints, the context processor that decides whether the
tutorial loads, the Help page tutorial list, and the account-reset hook.
The browser side (overlay, animation, navigation) is covered separately in
test_tutorial_browser.py.
"""

import re
import sqlite3

import pytest
from flask import template_rendered

from conftest import login_user, register_user
from app.tutorial.data import load_track

pytestmark = pytest.mark.tutorial

USERNAME = 'TestUser1'
PASSWORD = 'Password123!'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tclient(authenticated_client, app):
    """Authenticated client with CSRF checks off so JSON POSTs can be made directly."""
    app.config['WTF_CSRF_ENABLED'] = False
    yield authenticated_client
    app.config['WTF_CSRF_ENABLED'] = True


def post(client, path, **body):
    return client.post(path, json=body)


def sql(app, query, params=()):
    """Run a statement directly against the test database."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def set_status(app, track_id, status, step=0, user_id=1):
    sql(app,
        "INSERT INTO tutorial_progress (user_id, track_id, status, current_step_index) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, track_id) DO UPDATE SET status = excluded.status, "
        "current_step_index = excluded.current_step_index, last_updated = datetime('now', 'localtime')",
        (user_id, track_id, status, step))


def get_status(app, track_id, user_id=1):
    rows = sql(app, 'SELECT status, current_step_index FROM tutorial_progress WHERE user_id = ? AND track_id = ?',
               (user_id, track_id))
    return (rows[0]['status'], rows[0]['current_step_index']) if rows else None


def enable_advanced(app, active=True, user_id=1):
    sql(app, 'UPDATE users SET advanced_eligible = 1, advanced_purchased = 1, advanced_active = ? WHERE id = ?',
        (1 if active else 0, user_id))


def page_context(client, app, path='/dashboard'):
    """GET a page and return the tutorial-related template context values."""
    seen = {}

    def record(sender, template, context, **extra):
        for key in ('tutorial_active', 'tutorial_auto_track', 'tutorial_should_load_alpine'):
            seen[key] = context.get(key)

    template_rendered.connect(record, app)
    try:
        response = client.get(path)
        assert response.status_code == 200
    finally:
        template_rendered.disconnect(record, app)
    seen['html'] = response.data.decode()
    return seen


def overlay_attrs(html):
    """Extract the data-* attributes of the tutorial overlay root, or None if it is not rendered."""
    match = re.search(r'<div class="tutorial-root"(.*?)>', html, re.S)
    if not match:
        return None
    return dict(re.findall(r'data-([a-z-]+)="([^"]*)"', match.group(1)))


def first_cross_page_step(track_id):
    steps = load_track(track_id)['steps']
    for i in range(1, len(steps)):
        if steps[i]['route'] != steps[i - 1]['route']:
            return i
    pytest.fail(f'{track_id} has no step that changes page')


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def test_endpoints_require_login(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    try:
        assert client.get('/tutorial/state').status_code == 302
        assert client.get('/tutorial/track/beginner').status_code == 302
        for path in ('start', 'advance', 'complete', 'dismiss', 'replay'):
            response = client.post(f'/tutorial/{path}', json={'track_id': 'beginner'})
            assert response.status_code == 302, path
            assert '/login' in response.headers['Location']
    finally:
        app.config['WTF_CSRF_ENABLED'] = True


def test_track_endpoint(tclient):
    track = tclient.get('/tutorial/track/beginner').get_json()
    assert track['id'] == 'beginner' and track['steps']
    assert tclient.get('/tutorial/track/nope').status_code == 404
    # Advanced is locked until Advanced Mode has been purchased
    assert tclient.get('/tutorial/track/advanced').status_code == 403


def test_start_is_idempotent_and_refuses_finished_tracks(tclient, app):
    assert tclient.get('/tutorial/state').get_json() is None
    first = post(tclient, '/tutorial/start', track_id='beginner')
    assert first.status_code == 200 and first.get_json()['step_index'] == 0
    assert get_status(app, 'beginner') == ('in_progress', 0)
    assert post(tclient, '/tutorial/start', track_id='beginner').status_code == 200

    post(tclient, '/tutorial/complete', track_id='beginner')
    assert post(tclient, '/tutorial/start', track_id='beginner').status_code == 409
    assert get_status(app, 'beginner') == ('completed', 0)


def test_advance_validation_and_next_page(tclient, app):
    # Nothing to advance before the track has started
    assert post(tclient, '/tutorial/advance', track_id='beginner', step_index=1).status_code == 404
    post(tclient, '/tutorial/start', track_id='beginner')

    length = len(load_track('beginner')['steps'])
    for bad in (-1, length, 'x', None, True, 1.5):
        response = post(tclient, '/tutorial/advance', track_id='beginner', step_index=bad)
        assert response.status_code == 400, bad

    # Same page -> no navigation requested; changing page -> the new route is returned
    crossing = first_cross_page_step('beginner')
    steps = load_track('beginner')['steps']
    post(tclient, '/tutorial/advance', track_id='beginner', step_index=crossing - 1)
    response = post(tclient, '/tutorial/advance', track_id='beginner', step_index=crossing)
    assert response.get_json() == {'ok': True, 'next_page': steps[crossing]['route']}
    assert get_status(app, 'beginner') == ('in_progress', crossing)
    same_page = post(tclient, '/tutorial/advance', track_id='beginner', step_index=crossing)
    assert same_page.get_json()['next_page'] is None


def test_complete_and_dismiss_reset_the_step(tclient, app):
    for action, expected in (('complete', 'completed'), ('dismiss', 'dismissed')):
        post(tclient, '/tutorial/start', track_id='beginner') if action == 'complete' \
            else post(tclient, '/tutorial/replay', track_id='beginner')
        post(tclient, '/tutorial/advance', track_id='beginner', step_index=3)
        assert post(tclient, f'/tutorial/{action}', track_id='beginner').status_code == 200
        assert get_status(app, 'beginner') == (expected, 0)
        # Finished tracks cannot be advanced any more
        assert post(tclient, '/tutorial/advance', track_id='beginner', step_index=1).status_code == 409
    # Completing or dismissing a track that was never started
    assert post(tclient, '/tutorial/complete', track_id='advanced').status_code in (403, 404)


def test_replay_restarts_or_is_a_noop(tclient, app):
    first_route = load_track('beginner')['steps'][0]['route']
    # Never started -> replay starts it at step 0
    assert post(tclient, '/tutorial/replay', track_id='beginner').get_json() == {
        'ok': True, 'redirect': first_route, 'step_index': 0}
    assert get_status(app, 'beginner') == ('in_progress', 0)
    # In progress -> no-op: keeps the current step and reports it (so Help "Resume" lands there)
    post(tclient, '/tutorial/advance', track_id='beginner', step_index=2)
    resumed = post(tclient, '/tutorial/replay', track_id='beginner').get_json()
    assert resumed['step_index'] == 2
    assert get_status(app, 'beginner') == ('in_progress', 2)
    # Finished -> back to step 0
    post(tclient, '/tutorial/complete', track_id='beginner')
    post(tclient, '/tutorial/replay', track_id='beginner')
    assert get_status(app, 'beginner') == ('in_progress', 0)
    # The Advanced track cannot be replayed before it has been purchased
    assert post(tclient, '/tutorial/replay', track_id='advanced').status_code == 403
    enable_advanced(app)
    assert post(tclient, '/tutorial/replay', track_id='advanced').status_code == 200


def test_most_recently_updated_track_is_the_active_one(tclient, app):
    enable_advanced(app)
    set_status(app, 'beginner', 'in_progress', 4)
    sql(app, "UPDATE tutorial_progress SET last_updated = '2026-01-01 00:00:00' WHERE track_id = 'beginner'")
    set_status(app, 'advanced', 'in_progress', 1)
    assert tclient.get('/tutorial/state').get_json() == {
        'track_id': 'advanced', 'step_index': 1, 'status': 'in_progress'}
    attrs = overlay_attrs(page_context(tclient, app)['html'])
    assert attrs['active-track'] == 'advanced' and attrs['active-step'] == '1'


# ---------------------------------------------------------------------------
# Context processor / page wiring (Property 8, rendered)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('status', [None, 'not_started', 'in_progress', 'completed', 'dismissed'])
def test_resume_and_auto_start_depend_on_status(tclient, app, status):
    if status is not None:
        set_status(app, 'beginner', status, 2 if status == 'in_progress' else 0)
    ctx = page_context(tclient, app)
    attrs = overlay_attrs(ctx['html'])

    if status == 'in_progress':
        assert attrs['active-track'] == 'beginner' and attrs['active-step'] == '2'
        assert attrs['auto-track'] == ''
    elif status in (None, 'not_started'):
        assert attrs['auto-track'] == 'beginner' and attrs['active-track'] == ''
    else:  # completed / dismissed: never auto-trigger again, nothing to resume
        assert attrs is None
        assert ctx['tutorial_should_load_alpine'] is False
    assert ('js/tutorial.js' in ctx['html']) is (attrs is not None)


def test_assets_are_loaded_only_when_needed_and_in_the_right_order(tclient, app):
    html = page_context(tclient, app)['html']
    assert 'css/tutorial.css' in html
    # tutorial.js registers its component on alpine:init, so it must come before Alpine
    assert html.index('js/tutorial.js') < html.index('alpinejs')
    assert 'role="dialog"' in html and 'aria-modal="true"' in html
    assert 'aria-labelledby="tutorial-step-title"' in html

    set_status(app, 'beginner', 'completed')
    html = page_context(tclient, app)['html']
    assert 'tutorial.js' not in html and 'alpinejs' not in html and 'tutorial-root' not in html
    # The CSRF meta tag is always present (the Help page Replay button needs it)
    assert re.search(r'<meta name="csrf-token" content="[^"]{10,}">', html)


def test_profile_page_keeps_alpine_without_a_tutorial(tclient, app):
    set_status(app, 'beginner', 'completed')
    html = page_context(tclient, app, '/profile')['html']
    assert 'alpinejs' in html and 'achievementOrbit' in html
    assert 'tutorial.js' not in html


def test_advanced_tutorial_triggers_only_while_advanced_is_active(tclient, app):
    set_status(app, 'beginner', 'completed')
    assert page_context(tclient, app)['tutorial_auto_track'] is None   # advanced not owned
    enable_advanced(app, active=False)
    assert page_context(tclient, app)['tutorial_auto_track'] is None   # owned but switched off
    enable_advanced(app, active=True)
    assert page_context(tclient, app)['tutorial_auto_track'] == 'advanced'


def test_beginner_runs_before_advanced_and_never_alongside(tclient, app):
    enable_advanced(app)
    assert page_context(tclient, app)['tutorial_auto_track'] == 'beginner'
    # Standard Mode: a paused beginner tour is the one offered, and blocks advanced
    enable_advanced(app, active=False)
    set_status(app, 'beginner', 'in_progress', 1)
    ctx = page_context(tclient, app)
    assert ctx['tutorial_auto_track'] is None and ctx['tutorial_active']['track_id'] == 'beginner'


def test_paused_beginner_not_offered_in_advanced_mode(tclient, app):
    # Its steps can't render in the Advanced layout, so no resume prompt once
    # the player is in Advanced Mode (e.g. after finishing the advanced tour).
    enable_advanced(app, active=True)
    set_status(app, 'beginner', 'in_progress', 3)
    set_status(app, 'advanced', 'completed')
    ctx = page_context(tclient, app)
    assert ctx['tutorial_active'] is None
    assert ctx['tutorial_should_load_alpine'] is False


# ---------------------------------------------------------------------------
# Flows (13.1 - 13.4, server side)
# ---------------------------------------------------------------------------

def test_first_login_flow_runs_to_completion_then_stays_quiet(tclient, app):
    # 13.1: auto-triggers on the first visit...
    assert overlay_attrs(page_context(tclient, app)['html'])['auto-track'] == 'beginner'
    post(tclient, '/tutorial/start', track_id='beginner')
    # ...walk every step, as the Next button does, then Finish
    for index in range(1, len(load_track('beginner')['steps'])):
        assert post(tclient, '/tutorial/advance', track_id='beginner', step_index=index).status_code == 200
    assert get_status(app, 'beginner') == ('in_progress', len(load_track('beginner')['steps']) - 1)
    post(tclient, '/tutorial/complete', track_id='beginner')
    assert get_status(app, 'beginner') == ('completed', 0)

    # Log out and back in: no tutorial any more
    tclient.get('/logout')
    login_user(tclient, USERNAME, PASSWORD)
    ctx = page_context(tclient, app)
    assert ctx['tutorial_should_load_alpine'] is False and overlay_attrs(ctx['html']) is None


def test_advanced_flow_triggers_once_and_navigates_across_pages(tclient, app):
    # 13.2
    set_status(app, 'beginner', 'completed')
    enable_advanced(app)
    assert overlay_attrs(page_context(tclient, app)['html'])['auto-track'] == 'advanced'
    post(tclient, '/tutorial/start', track_id='advanced')

    crossing = first_cross_page_step('advanced')
    steps = load_track('advanced')['steps']
    post(tclient, '/tutorial/advance', track_id='advanced', step_index=crossing - 1)
    response = post(tclient, '/tutorial/advance', track_id='advanced', step_index=crossing)
    assert response.get_json()['next_page'] == steps[crossing]['route']

    post(tclient, '/tutorial/dismiss', track_id='advanced')
    # Switching Advanced Mode off and on again does not bring the tutorial back
    enable_advanced(app, active=False)
    enable_advanced(app, active=True)
    ctx = page_context(tclient, app)
    assert ctx['tutorial_auto_track'] is None and overlay_attrs(ctx['html']) is None


def test_resume_and_replay_flow(tclient, app):
    # 13.3: a paused tutorial is offered again from the saved step on any page
    post(tclient, '/tutorial/start', track_id='beginner')
    post(tclient, '/tutorial/advance', track_id='beginner', step_index=3)
    for path in ('/dashboard', '/market', '/portfolio'):
        attrs = overlay_attrs(page_context(tclient, app, path)['html'])
        assert attrs['active-track'] == 'beginner' and attrs['active-step'] == '3', path

    # Once finished, the Help page offers Replay, which restarts at step 0
    post(tclient, '/tutorial/complete', track_id='beginner')
    help_html = page_context(tclient, app, '/help')['html']
    assert 'data-tutorial-replay="beginner"' in help_html
    post(tclient, '/tutorial/replay', track_id='beginner')
    assert get_status(app, 'beginner') == ('in_progress', 0)
    attrs = overlay_attrs(page_context(tclient, app)['html'])
    assert attrs['active-track'] == 'beginner' and attrs['active-step'] == '0'


def test_account_reset_clears_progress_and_retriggers(tclient, app):
    # 13.4
    set_status(app, 'beginner', 'completed')
    set_status(app, 'advanced', 'dismissed')
    assert page_context(tclient, app)['tutorial_auto_track'] is None

    response = tclient.post('/settings/reset', data={'confirmation': USERNAME})
    assert response.status_code == 302
    assert sql(app, 'SELECT COUNT(*) AS n FROM tutorial_progress WHERE user_id = 1')[0]['n'] == 0
    assert page_context(tclient, app)['tutorial_auto_track'] == 'beginner'


# ---------------------------------------------------------------------------
# Help page tutorial list (Property 9, rendered)
# ---------------------------------------------------------------------------

def test_help_page_lists_tracks_by_purchase_and_status(tclient, app):
    statuses = [None, 'not_started', 'in_progress', 'completed', 'dismissed']
    for purchased in (False, True):
        sql(app, 'UPDATE users SET advanced_purchased = ? WHERE id = 1', (1 if purchased else 0,))
        for beginner in statuses:
            for advanced in statuses:
                sql(app, 'DELETE FROM tutorial_progress WHERE user_id = 1')
                for track_id, status in (('beginner', beginner), ('advanced', advanced)):
                    if status:
                        set_status(app, track_id, status)
                html = page_context(tclient, app, '/help')['html']
                context = f'purchased={purchased} beginner={beginner} advanced={advanced}'

                assert 'Getting Started' in html, context
                assert ('Going Deeper</span>' in html) is purchased, context
                # A button appears for in-progress (Resume + Replay) and
                # completed/dismissed (Replay); not_started and absent tracks have none.
                expected_buttons = {track for track, status, visible in (
                    ('beginner', beginner, True), ('advanced', advanced, purchased))
                    if visible and status in ('in_progress', 'completed', 'dismissed')}
                found = set(re.findall(r'data-tutorial-replay="([a-z]+)"', html))
                assert found == expected_buttons, context
                # In-progress tracks show both Resume and Replay
                any_in_progress = (beginner == 'in_progress') or (purchased and advanced == 'in_progress')
                if any_in_progress:
                    assert '>Resume</button>' in html and '>Replay</button>' in html, context


def test_help_page_advanced_tutorial_gated_by_mode(tclient, app):
    """Each tutorial's buttons are disabled unless the player is in the mode its
    steps are built for: Advanced needs Advanced Mode ON, Beginner needs it OFF."""
    enable_advanced(app, active=False)         # purchased but currently OFF
    set_status(app, 'advanced', 'completed')
    set_status(app, 'beginner', 'completed')

    def button(html, track):
        return re.search(rf'data-tutorial-replay="{track}"[^>]*>', html).group(0)

    # Advanced Mode OFF: beginner enabled, advanced disabled
    html = page_context(tclient, app, '/help')['html']
    assert html.count('data-tutorial-replay="advanced"') == 1
    assert html.count('data-tutorial-replay="beginner"') == 1
    assert 'disabled' in button(html, 'advanced') and 'Advanced Mode' in button(html, 'advanced')
    assert 'disabled' not in button(html, 'beginner')

    # Advanced Mode ON: the gating flips — advanced enabled, beginner disabled
    enable_advanced(app, active=True)
    html = page_context(tclient, app, '/help')['html']
    assert 'disabled' not in button(html, 'advanced')
    assert 'disabled' in button(html, 'beginner') and 'Advanced Mode' in button(html, 'beginner')


def test_help_page_when_logged_out(client):
    html = client.get('/help').data.decode()
    assert 'data-tutorial-replay' not in html
    assert 'logged-in players' in html


# What tutorial.js and the overlay do in a browser (htmx swaps, Escape, the step
# card, focus, the skip confirmation) is checked in test_tutorial_browser.py.
