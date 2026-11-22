"""Regression tests: achievements earned inside the market engine thread.

The engine thread has no Flask app context. Awarding an advancement there used
to lose the inbox notification (create_notification needs get_db, which needs
an app context) while the advancement row itself was kept. These tests run the
real engine loop in its real thread and check both the row and the inbox entry.
"""

import importlib.util
import signal
import sqlite3
import time

import pytest

from conftest import register_user


def _load_real_engine():
    """Fresh copy of app.market.engine (conftest replaces start_engine with a no-op)."""
    import app.market.engine as patched

    spec = importlib.util.spec_from_file_location('engine_under_test', patched.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@pytest.fixture()
def run_engine(app, monkeypatch):
    """Start the real engine thread (fast ticks), stop and join it afterwards."""
    monkeypatch.setitem(app.config, 'TICK_INTERVAL', 0.05)
    # start_engine installs signal handlers when called from the main thread
    monkeypatch.setattr(signal, 'signal', lambda *args, **kwargs: None)
    engine = _load_real_engine()
    engine.start_engine(app)
    yield engine
    engine.stop_engine()
    engine._engine_thread.join(timeout=10)
    assert not engine._engine_thread.is_alive()


def _wait_for(predicate, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _user_id(db_path, username):
    return _query(db_path, "SELECT id FROM users WHERE username = ?", (username,))[0][0]


def test_tick_net_worth_achievement_creates_row_and_one_notification(app, run_engine):
    db_path = app.config['DATABASE_PATH']
    register_user(app.test_client(), 'Rich1', 'Password123!')
    user_id = _user_id(db_path, 'Rich1')
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE users SET balance = 1500000 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    notif_sql = ("SELECT COUNT(*) FROM notifications WHERE user_id = ? "
                 "AND category = 'advancement' AND message LIKE 'Achievement unlocked: Millionaire%'")
    assert _wait_for(lambda: _query(db_path, notif_sql, (user_id,))[0][0] >= 1), \
        "no Millionaire inbox notification after engine ticks"
    time.sleep(0.5)  # several more ticks: the award must not repeat

    assert _query(db_path, "SELECT COUNT(*) FROM advancements WHERE user_id = ? "
                  "AND advancement_key = 'millionaire'", (user_id,))[0][0] == 1
    assert _query(db_path, notif_sql, (user_id,))[0][0] == 1


def test_tick_take_profit_short_close_awards_big_short_with_notification(app, run_engine):
    db_path = app.config['DATABASE_PATH']
    register_user(app.test_client(), 'Shorter1', 'Password123!')
    user_id = _user_id(db_path, 'Shorter1')
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE users SET advanced_purchased = 1, advanced_active = 1 WHERE id = ?", (user_id,))
    ore_id = conn.execute("SELECT id FROM ores ORDER BY id LIMIT 1").fetchone()[0]
    # Take profit far above the price, so the first tick closes it at a profit
    conn.execute(
        """INSERT INTO short_positions (user_id, ore_id, share_quantity, entry_price,
                                        locked_collateral, take_profit_price)
           VALUES (?, ?, 1, 100, 100000, 1000000000)""",
        (user_id, ore_id),
    )
    conn.commit()
    conn.close()

    notif_sql = ("SELECT COUNT(*) FROM notifications WHERE user_id = ? "
                 "AND category = 'advancement' AND message LIKE 'Achievement unlocked: The Big Short%'")
    assert _wait_for(lambda: _query(db_path, notif_sql, (user_id,))[0][0] >= 1), \
        "no The Big Short inbox notification after the take-profit close"
    time.sleep(0.5)

    assert _query(db_path, "SELECT COUNT(*) FROM advancements WHERE user_id = ? "
                  "AND advancement_key = 'the_big_short'", (user_id,))[0][0] == 1
    assert _query(db_path, notif_sql, (user_id,))[0][0] == 1
