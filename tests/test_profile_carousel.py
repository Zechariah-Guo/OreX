"""Phone achievements carousel on /profile and /player/<username>.

Covers the start-badge choice (most recently unlocked, first when none) and
that the carousel markup is rendered from the same achievements list on both
pages.
"""

import sqlite3

import pytest

from app.advancements import ADVANCEMENT_KEYS
from app.routes.profile import most_recent_unlock_index
from conftest import register_user
from test_public_profile import OTHER, VIEWER, _insert_user


def _ach(earned_at=None):
    return {'earned': earned_at is not None, 'earned_at': earned_at}


class TestMostRecentUnlockIndex:

    def test_none_unlocked_starts_on_first(self):
        assert most_recent_unlock_index([_ach(), _ach(), _ach()]) == 0

    def test_empty_list(self):
        assert most_recent_unlock_index([]) == 0

    def test_picks_latest_timestamp_not_list_position(self):
        items = [_ach('2024-01-03 10:00:00'), _ach(), _ach('2024-02-01 09:00:00'),
                 _ach('2024-01-20 12:00:00')]
        assert most_recent_unlock_index(items) == 2

    def test_all_unlocked_lands_on_last_earned(self):
        items = [_ach('2024-03-01 10:00:00'), _ach('2024-01-01 10:00:00'),
                 _ach('2024-02-01 10:00:00')]
        assert most_recent_unlock_index(items) == 0

    def test_tie_goes_to_later_badge(self):
        items = [_ach('2024-01-01 10:00:00'), _ach('2024-01-01 10:00:00')]
        assert most_recent_unlock_index(items) == 1


def _grant(app, user_id, key, earned_at):
    # REPLACE: the per-test DB reset does not drop the advancements table, so a
    # reused user id can still carry rows from an earlier test.
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    try:
        conn.execute(
            "INSERT OR REPLACE INTO advancements (user_id, advancement_key, earned_at) VALUES (?, ?, ?)",
            (user_id, key, earned_at),
        )
        conn.commit()
    finally:
        conn.close()


def _clear(app, user_id):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    try:
        conn.execute("DELETE FROM advancements WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def _user_id(app, username):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    try:
        return conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _start(html):
    marker = 'class="ach-carousel" data-start="'
    return int(html.split(marker, 1)[1].split('"', 1)[0])


@pytest.fixture()
def viewer(client):
    register_user(client, VIEWER, 'Password123!')
    return client


class TestCarouselMarkup:

    def test_renders_on_own_profile_with_every_achievement(self, viewer, app):
        _clear(app, _user_id(app, VIEWER))
        html = viewer.get('/profile').data.decode('utf-8')
        assert 'role="group" aria-roledescription="carousel"' in html
        assert html.count('class="ach-carousel__slide"') == len(ADVANCEMENT_KEYS)
        assert 'aria-label="Previous achievement"' in html
        assert 'aria-label="Next achievement"' in html
        assert _start(html) == 0  # nothing unlocked yet

    def test_renders_on_public_profile_and_starts_on_latest_unlock(self, viewer, app):
        other_id = _insert_user(app, OTHER)
        _clear(app, other_id)
        _grant(app, other_id, ADVANCEMENT_KEYS[2], '2024-05-01 10:00:00')
        _grant(app, other_id, ADVANCEMENT_KEYS[5], '2024-06-01 10:00:00')
        _grant(app, other_id, ADVANCEMENT_KEYS[1], '2024-04-01 10:00:00')

        html = viewer.get(f'/player/{OTHER}').data.decode('utf-8')
        assert html.count('class="ach-carousel__slide"') == len(ADVANCEMENT_KEYS)
        assert _start(html) == 5

    def test_all_unlocked_starts_on_last_earned(self, viewer, app):
        other_id = _insert_user(app, OTHER)
        _clear(app, other_id)
        for i, key in enumerate(ADVANCEMENT_KEYS):
            # Earn them in reverse list order so the first badge is the latest
            _grant(app, other_id, key, f'2024-01-{20 - i:02d} 10:00:00')

        html = viewer.get(f'/player/{OTHER}').data.decode('utf-8')
        assert _start(html) == 0
        assert 'data-earned="0"' not in html

    def test_locked_state_is_text_data(self, viewer, app):
        _clear(app, _user_id(app, VIEWER))
        html = viewer.get('/profile').data.decode('utf-8')
        assert 'data-earned="0"' in html
