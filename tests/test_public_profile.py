"""Integration tests for public player profiles (/player/<username>).

Covers: read-only rendering of another player's profile (no daily bonus, no
avatar upload), the owner's colours/avatar rather than the viewer's, routing
rules (own name -> /profile, bots -> 404, unknown -> 404, case-insensitive
redirect only when unambiguous), login requirement, and leaderboard links.
"""

import sqlite3
from datetime import datetime

import pytest

from app.avatar import get_avatar_color_hex
from conftest import register_user


VIEWER = 'ViewerUser'
OTHER = 'OtherPlayer'


def _insert_user(app, username, password_hash='not-a-real-hash', avatar_color='coal',
                 login_streak=0, play_time=0):
    """Insert a user directly (register_user would log the client in as them)."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    cursor = conn.execute(
        """INSERT INTO users (username, password_hash, balance, created_at, avatar_color,
                              login_streak, play_time)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (username, password_hash, app.config['DEFAULT_BALANCE'],
         datetime.now().isoformat(), avatar_color, login_streak, play_time),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


@pytest.fixture()
def viewer(client):
    register_user(client, VIEWER, 'Password123!')
    return client


class TestOtherPlayersProfile:

    def test_renders_their_profile_read_only(self, viewer, app):
        _insert_user(app, OTHER, login_streak=4)
        resp = viewer.get(f'/player/{OTHER}')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')

        assert OTHER in html
        assert f'<title>{OTHER} - OreX</title>' in html
        assert '4 days' in html  # their login streak, not the viewer's

        # No daily bonus and no way to change their avatar
        assert 'profile-bonus-section' not in html
        assert 'avatar-upload-trigger' not in html
        assert 'avatar-file-input' not in html
        assert 'id="avatar-crop-backdrop"' not in html
        assert 'cropper.min.js' not in html

    def test_uses_the_owners_avatar_colour(self, viewer, app):
        _insert_user(app, OTHER, avatar_color='diamond')
        html = viewer.get(f'/player/{OTHER}').data.decode('utf-8')
        assert f'background-color: {get_avatar_color_hex("diamond")};' in html

    def test_shows_the_owners_uploaded_avatar(self, viewer, app):
        other_id = _insert_user(app, OTHER)
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute("UPDATE users SET avatar_path = ? WHERE id = ?",
                     (f'static/uploads/avatars/{other_id}.webp', other_id))
        conn.commit()
        conn.close()

        html = viewer.get(f'/player/{OTHER}').data.decode('utf-8')
        assert f'uploads/avatars/{other_id}.webp' in html

    def test_own_profile_keeps_bonus_and_avatar_upload(self, viewer):
        html = viewer.get('/profile').data.decode('utf-8')
        assert 'profile-bonus-section' in html  # new account: bonus not complete
        assert 'avatar-upload-trigger' in html
        assert 'cropper.min.js' in html


class TestPlayerRouting:

    def test_own_username_redirects_to_profile(self, viewer):
        resp = viewer.get(f'/player/{VIEWER}')
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/profile')

    def test_unknown_player_is_404(self, viewer):
        assert viewer.get('/player/NoSuchPlayer').status_code == 404

    def test_bots_have_no_profile(self, viewer, app):
        _insert_user(app, 'SteveBot', password_hash='BOT_NO_LOGIN')
        assert viewer.get('/player/SteveBot').status_code == 404

    def test_wrong_case_redirects_to_canonical_url(self, viewer, app):
        _insert_user(app, OTHER)
        resp = viewer.get(f'/player/{OTHER.lower()}')
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/player/{OTHER}')

    def test_ambiguous_case_is_404(self, viewer, app):
        # Registration is case-sensitive, so these can both exist
        _insert_user(app, 'Dupe')
        _insert_user(app, 'dupe')
        assert viewer.get('/player/DUPE').status_code == 404
        # Exact matches still work
        assert viewer.get('/player/Dupe').status_code == 200
        assert viewer.get('/player/dupe').status_code == 200

    def test_requires_login(self, app):
        _insert_user(app, OTHER)
        # Fresh client: the shared `client` fixture can carry a login cookie
        # from an earlier test, whose user id may now belong to someone else.
        resp = app.test_client().get(f'/player/{OTHER}')
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']


class TestLeaderboardLinks:

    def test_players_link_to_profiles_and_bots_do_not(self, viewer, app):
        _insert_user(app, OTHER)
        _insert_user(app, 'SteveBot', password_hash='BOT_NO_LOGIN')
        html = viewer.get('/leaderboard').data.decode('utf-8')

        assert f'href="/player/{OTHER}"' in html
        assert '/player/SteveBot' not in html
        # Your own row links to your own editable profile
        assert 'href="/profile"' in html
        assert f'/player/{VIEWER}' not in html
