"""Shared pytest fixtures for the OreX test suite.

Provides session-scoped app and client fixtures with an isolated temporary
SQLite database. The market engine is monkeypatched to a no-op to ensure
deterministic test execution.
"""

import os
import re
import sqlite3
import sys
import tempfile

import pytest
import werkzeug.security

# Add src/ to the Python path so that `from app import create_app` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

# The default scrypt hash costs ~145 ms per call, and tests hash on every
# registration, login and backup code. Use a 1-iteration PBKDF2 hash instead
# (~3 ms). check_password_hash reads the method from the stored hash, so
# verification is unchanged. This must run before any app module is imported,
# because they bind generate_password_hash with `from werkzeug.security import`.
_real_generate_password_hash = werkzeug.security.generate_password_hash


def _fast_generate_password_hash(password, method='pbkdf2:sha256:1', salt_length=16):
    return _real_generate_password_hash(password, method=method, salt_length=salt_length)


werkzeug.security.generate_password_hash = _fast_generate_password_hash


@pytest.fixture(scope='session')
def app():
    """Create a Flask application configured for testing.

    Uses a unique temporary SQLite file as the database, sets TESTING=True,
    and monkeypatches start_engine to a no-op to prevent the background
    market engine thread from starting.
    """
    # Create a unique temp DB file for this test session
    db_fd, db_path = tempfile.mkstemp(suffix='.db', prefix='orex_test_')
    os.close(db_fd)

    # Monkeypatch start_engine to a no-op before importing create_app
    import app.market.engine as engine_module
    original_start_engine = engine_module.start_engine
    engine_module.start_engine = lambda app: None

    from app import create_app

    test_app = create_app({
        'TESTING': True,
        'DATABASE_PATH': db_path,
        'SECRET_KEY': 'test-secret-key',
    })

    # Re-initialise the database with the test DB path since create_app()
    # already called init_db with the original config. We need to init
    # against our temp DB.
    from app.database import init_db
    init_db(test_app)

    yield test_app

    # Session teardown: restore original start_engine and remove temp DB
    engine_module.start_engine = original_start_engine
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(scope='session')
def client(app):
    """Provide a Flask test client bound to the test application."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_csrf_token(response):
    """Parse an HTML response and extract the csrf_token hidden input value.

    Raises ValueError if the token cannot be found.
    """
    html = response.data.decode('utf-8')
    match = re.search(r'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"', html)
    if not match:
        # Try alternative attribute ordering (value before name)
        match = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="csrf_token"', html)
    if not match:
        raise ValueError(
            'Could not find csrf_token hidden input in the response HTML.'
        )
    return match.group(1)


def register_user(client, username, password):
    """Register a new user via POST /register with CSRF token handling.

    GETs the registration page to obtain a CSRF token, then POSTs the
    registration form. Returns the POST response.
    """
    get_resp = client.get('/register')
    token = get_csrf_token(get_resp)
    return client.post('/register', data={
        'username': username,
        'password': password,
        'confirm_password': password,
        'csrf_token': token,
    }, follow_redirects=False)


def login_user(client, username, password):
    """Log in a user via POST /login with CSRF token handling.

    GETs the login page to obtain a CSRF token, then POSTs the login form.
    Returns the POST response.
    """
    get_resp = client.get('/login')
    token = get_csrf_token(get_resp)
    return client.post('/login', data={
        'username': username,
        'password': password,
        'csrf_token': token,
    }, follow_redirects=False)


# ---------------------------------------------------------------------------
# Function-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def db_reset(app, client):
    """Reset the test database to its seeded state before each test.

    Drops all tables, re-executes schema.sql and seed.sql, and clears
    the in-memory rate limiter to prevent cross-test contamination. The shared
    client also forgets its remember cookie: user ids repeat after a reset, so a
    leftover cookie would sign the next test in as someone else.
    """
    client.delete_cookie('remember_token')
    from app.routes.auth import _login_attempts

    db_path = app.config['DATABASE_PATH']
    src_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'
    )
    schema_path = os.path.join(src_dir, 'schema.sql')
    seed_path = os.path.join(src_dir, 'seed.sql')

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=OFF")

    # Drop tables in reverse FK order
    for table in ('notification_pushes', 'push_subscriptions', 'push_settings', 'push_presence', 'notifications', 'tutorial_progress', 'short_positions', 'stop_loss_take_profit', 'price_history', 'transactions', 'holdings', 'backup_codes', 'recovery_keys', 'ores', 'users'):
        conn.execute(f'DROP TABLE IF EXISTS {table}')

    # Re-create schema
    with open(schema_path, 'r') as f:
        conn.executescript(f.read())

    # Re-seed data
    with open(seed_path, 'r') as f:
        conn.executescript(f.read())

    conn.close()

    # Clear rate limiter state
    _login_attempts.clear()

    yield


@pytest.fixture(scope='session')
def live_server(app):
    """The test app served over real HTTP on a free port, for browser tests.

    It shares the session's temp database, so the autouse db_reset still gives
    every test a clean state. Yields the base URL.
    """
    import threading
    from werkzeug.serving import make_server

    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()


@pytest.fixture(scope='session')
def pw_browser():
    """Headless system Chrome (or Edge) driven by Playwright. Skips when neither is installed."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip('Playwright is not installed')
    manager = sync_playwright().start()
    browser = None
    for channel in ('chrome', 'msedge'):
        try:
            browser = manager.chromium.launch(channel=channel)
            break
        except Exception:
            continue
    if browser is None:
        manager.stop()
        pytest.skip('Chrome/Edge not found')
    yield browser
    browser.close()
    manager.stop()


@pytest.fixture()
def browser_context(pw_browser):
    """A fresh browser profile (cookies, storage, service workers) for one test."""
    context = pw_browser.new_context(viewport={'width': 1280, 'height': 800})
    context.set_default_timeout(10_000)
    yield context
    context.close()


def browser_login(page, base_url, app, username='BrowserUser', password='Password123!'):
    """Create a player with both tutorials finished, then sign in through the real login form.

    Returns the new user's id.
    """
    from app.database import get_db
    from app.models import create_user

    with app.app_context():
        user_id = create_user(username, password)
        db = get_db()
        for track in ('beginner', 'advanced'):
            db.execute("INSERT INTO tutorial_progress (user_id, track_id, status) VALUES (?, ?, 'completed')",
                       (user_id, track))
        db.commit()
    page.goto(base_url + '/login')
    page.fill('#username', username)
    page.fill('#password', password)
    page.click('button[type="submit"]')
    page.wait_for_url('**/dashboard')
    return user_id


@pytest.fixture()
def authenticated_client(client):
    """Register and log in a test user, yielding an authenticated client.

    Uses TestUser1 / Password123! credentials. Registration auto-logs in
    the user, so no separate login call is needed. Database cleanup is
    handled by the autouse db_reset fixture.
    """
    register_user(client, 'TestUser1', 'Password123!')
    # register_user auto-logs in the user via the register route
    yield client
