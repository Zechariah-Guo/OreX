"""Tests for the Advanced tutorial's throwaway "demo short".

The tour opens a one-unit short so its position-dependent pages show live data,
then removes it, leaving the account exactly as it was. These tests pin down the
two guarantees that matter: the position is flagged and real-positions are never
touched, and opening-then-closing is net-zero on the balance (no money glitch,
even on replay).
"""

import sqlite3

import pytest

pytestmark = pytest.mark.tutorial

USERNAME = 'TestUser1'


@pytest.fixture()
def tclient(authenticated_client, app):
    """Authenticated client with CSRF off and Advanced Mode active."""
    app.config['WTF_CSRF_ENABLED'] = False
    _sql(app, 'UPDATE users SET advanced_eligible = 1, advanced_purchased = 1, '
              'advanced_active = 1, balance = ? WHERE id = 1', (1_000_000,))
    yield authenticated_client
    app.config['WTF_CSRF_ENABLED'] = True


def _sql(app, query, params=()):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def _balance(app, user_id=1):
    return _sql(app, 'SELECT balance FROM users WHERE id = ?', (user_id,))[0]['balance']


def _demo_rows(app, user_id=1):
    return _sql(app, 'SELECT * FROM short_positions WHERE user_id = ? AND is_demo = 1', (user_id,))


def _all_shorts(app, user_id=1):
    return _sql(app, 'SELECT * FROM short_positions WHERE user_id = ?', (user_id,))


# ---------------------------------------------------------------------------
# Endpoint gating
# ---------------------------------------------------------------------------

def test_demo_short_requires_advanced_active(authenticated_client, app):
    """Without Advanced Mode active the open endpoint refuses with 409."""
    app.config['WTF_CSRF_ENABLED'] = False
    try:
        # advanced not active (default seeded user)
        resp = authenticated_client.post('/tutorial/advanced/demo-short', json={})
        assert resp.status_code == 409
        assert resp.get_json()['ok'] is False
        assert not _all_shorts(app)
    finally:
        app.config['WTF_CSRF_ENABLED'] = True


def test_demo_endpoints_require_login(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    try:
        for path in ('demo-short', 'demo-clear'):
            resp = client.post(f'/tutorial/advanced/{path}', json={})
            assert resp.status_code == 302
            assert '/login' in resp.headers['Location']
    finally:
        app.config['WTF_CSRF_ENABLED'] = True


# ---------------------------------------------------------------------------
# Open
# ---------------------------------------------------------------------------

def test_open_creates_exactly_one_flagged_demo_short(tclient, app):
    resp = tclient.post('/tutorial/advanced/demo-short', json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True and body['created'] is True

    rows = _demo_rows(app)
    assert len(rows) == 1
    pos = rows[0]
    assert pos['is_demo'] == 1
    assert pos['share_quantity'] == 1
    assert pos['status'] == 'active'
    # Sample SL/TP are populated so the portfolio/finances rows aren't empty
    assert pos['stop_loss_price'] is not None
    assert pos['take_profit_price'] is not None


def test_open_is_idempotent_never_stacks(tclient, app):
    """Opening repeatedly leaves exactly one demo short, not a growing stack."""
    for _ in range(3):
        tclient.post('/tutorial/advanced/demo-short', json={})
    assert len(_demo_rows(app)) == 1


def test_reopen_is_a_true_noop_same_row_same_balance(tclient, app):
    """Re-firing open (e.g. navigating backward then forward through the tour)
    must NOT clear-and-recreate the short: the row and the balance stay identical,
    so there is no churn and no repeated margin movement."""
    first = tclient.post('/tutorial/advanced/demo-short', json={})
    assert first.get_json()['created'] is True
    rows1 = _demo_rows(app)
    assert len(rows1) == 1
    row_id, bal = rows1[0]['id'], _balance(app)

    # Re-open several times, as back/forward navigation would.
    for _ in range(4):
        r = tclient.post('/tutorial/advanced/demo-short', json={})
        body = r.get_json()
        assert body['created'] is False and body['reason'] == 'already open'

    rows2 = _demo_rows(app)
    assert len(rows2) == 1
    assert rows2[0]['id'] == row_id          # same row, never deleted/recreated
    assert _balance(app) == bal              # balance untouched by the re-opens


def test_open_deducts_margin_from_balance(tclient, app):
    before = _balance(app)
    tclient.post('/tutorial/advanced/demo-short', json={})
    after = _balance(app)
    # Some margin was locked, so free cash drops
    assert after < before


# ---------------------------------------------------------------------------
# Clear / net-zero
# ---------------------------------------------------------------------------

def test_open_then_clear_is_net_zero(tclient, app):
    """The whole point: a tour run must not move the balance by a cent."""
    before = _balance(app)
    tclient.post('/tutorial/advanced/demo-short', json={})
    clear = tclient.post('/tutorial/advanced/demo-clear', json={})
    assert clear.status_code == 200
    assert clear.get_json() == {'ok': True, 'removed': 1}

    assert _demo_rows(app) == []
    assert round(_balance(app), 2) == round(before, 2)


def test_clear_when_none_exists_is_a_noop(tclient, app):
    before = _balance(app)
    resp = tclient.post('/tutorial/advanced/demo-clear', json={})
    assert resp.get_json() == {'ok': True, 'removed': 0}
    assert _balance(app) == before


def test_replay_open_clear_cycles_never_gain_money(tclient, app):
    """Repeated tour runs (replays) must stay net-zero: no infinite-money glitch."""
    before = _balance(app)
    for _ in range(5):
        tclient.post('/tutorial/advanced/demo-short', json={})
        tclient.post('/tutorial/advanced/demo-clear', json={})
    assert _demo_rows(app) == []
    assert round(_balance(app), 2) == round(before, 2)


# ---------------------------------------------------------------------------
# Real positions are never touched
# ---------------------------------------------------------------------------

def test_clear_leaves_real_shorts_untouched(tclient, app):
    """A real (is_demo=0) short must survive both open and clear of a demo short."""
    _sql(app,
         "INSERT INTO short_positions (user_id, ore_id, share_quantity, entry_price, "
         "locked_collateral, is_demo, open_factor) VALUES (1, 1, 5, 100.0, 750.0, 0, 1.5)")
    real_before = _sql(app, 'SELECT * FROM short_positions WHERE is_demo = 0')
    assert len(real_before) == 1
    real_id = real_before[0]['id']

    tclient.post('/tutorial/advanced/demo-short', json={})
    tclient.post('/tutorial/advanced/demo-clear', json={})

    real_after = _sql(app, 'SELECT * FROM short_positions WHERE id = ?', (real_id,))
    assert len(real_after) == 1
    assert real_after[0]['share_quantity'] == 5
    assert real_after[0]['is_demo'] == 0


# ---------------------------------------------------------------------------
# Lifecycle hooks: complete / dismiss clear the demo short
# ---------------------------------------------------------------------------

def test_complete_advanced_clears_demo_short(tclient, app):
    tclient.post('/tutorial/replay', json={'track_id': 'advanced'})
    tclient.post('/tutorial/advanced/demo-short', json={})
    assert len(_demo_rows(app)) == 1
    before = _balance(app)
    # account for the margin currently locked by the open demo short
    tclient.post('/tutorial/complete', json={'track_id': 'advanced'})
    assert _demo_rows(app) == []
    # Completing refunds the locked margin, so balance goes back up
    assert _balance(app) >= before


def test_dismiss_advanced_clears_demo_short(tclient, app):
    tclient.post('/tutorial/replay', json={'track_id': 'advanced'})
    tclient.post('/tutorial/advanced/demo-short', json={})
    assert len(_demo_rows(app)) == 1
    tclient.post('/tutorial/dismiss', json={'track_id': 'advanced'})
    assert _demo_rows(app) == []


# ---------------------------------------------------------------------------
# Server backstop: a dangling demo short (crash remnant) is swept on page load
# whenever the Advanced tour is not in progress.
# ---------------------------------------------------------------------------

def _set_advanced_status(app, status, step=0, user_id=1):
    _sql(app,
         "INSERT INTO tutorial_progress (user_id, track_id, status, current_step_index) "
         "VALUES (?, 'advanced', ?, ?) ON CONFLICT(user_id, track_id) DO UPDATE SET "
         "status = excluded.status, current_step_index = excluded.current_step_index",
         (user_id, status, step))


def test_backstop_clears_demo_short_when_tour_not_in_progress(tclient, app):
    """A demo short left dangling (e.g. after a crash) is cleared on the next page
    load once the Advanced tour is no longer in progress, with the margin refunded."""
    before = _balance(app)
    tclient.post('/tutorial/advanced/demo-short', json={})
    assert len(_demo_rows(app)) == 1
    # Simulate the tour having ended without the client clearing (crash remnant):
    # the short still exists but the track is not in progress.
    _set_advanced_status(app, 'completed')

    # Any normal GET page load triggers the before_request backstop.
    assert tclient.get('/dashboard').status_code == 200
    assert _demo_rows(app) == []
    assert round(_balance(app), 2) == round(before, 2)      # margin refunded: net-zero


def test_backstop_leaves_demo_short_while_tour_in_progress(tclient, app):
    """While the Advanced tour is in progress the demo short is legitimate (the
    overlay re-opens it each page), so the backstop must not remove it."""
    tclient.post('/tutorial/advanced/demo-short', json={})
    _set_advanced_status(app, 'in_progress', step=3)
    assert tclient.get('/dashboard').status_code == 200
    assert len(_demo_rows(app)) == 1                        # kept during an active tour


def test_backstop_does_not_run_on_tutorial_api_calls(tclient, app):
    """The backstop must not interfere with the tutorial's own endpoints, which
    manage the demo short deliberately (it only sweeps on ordinary page GETs)."""
    tclient.post('/tutorial/advanced/demo-short', json={})
    _set_advanced_status(app, 'completed')
    # Hitting a tutorial API endpoint must not trigger the sweep.
    tclient.get('/tutorial/state')
    assert len(_demo_rows(app)) == 1


def test_demo_clear_endpoint_is_csrf_exempt(authenticated_client, app):
    """The clear endpoint is fired by sendBeacon on unload (no CSRF header), so it
    must succeed with CSRF protection ENABLED and no token supplied."""
    _sql(app, 'UPDATE users SET advanced_eligible=1, advanced_purchased=1, '
              'advanced_active=1, balance=1000000 WHERE id=1')
    # Open a demo short with CSRF off, then clear it with CSRF on and no token.
    app.config['WTF_CSRF_ENABLED'] = False
    authenticated_client.post('/tutorial/advanced/demo-short', json={})
    assert len(_demo_rows(app)) == 1
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        resp = authenticated_client.post('/tutorial/advanced/demo-clear', json={})
        assert resp.status_code == 200
        assert resp.get_json() == {'ok': True, 'removed': 1}
        assert _demo_rows(app) == []
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
