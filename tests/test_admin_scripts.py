"""Tests for the production admin scripts (scripts/admin) and account suspension.

Every test runs against the suite's temporary database (the `app` fixture is
reset before each test); nothing here touches src/data/orex.db or the real
avatar folder.
"""

import contextlib
import json
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from conftest import login_user, register_user

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'admin'))

import export_user_data  # noqa: E402
import remove_avatar  # noqa: E402
import rename_user  # noqa: E402
import reset_economy  # noqa: E402
import reset_password  # noqa: E402
import suspend_user  # noqa: E402
import unsuspend_user  # noqa: E402

from app.models import enable_2fa, get_leaderboard, store_backup_codes  # noqa: E402
from app.storage import LocalStorage  # noqa: E402

PASSWORD = 'Password123!'
SUSPENDED_MESSAGE = 'This account has been suspended. Contact orexsupport@gmail.com.'


@pytest.fixture(autouse=True)
def clean_session(client, app):
    """The test client is session-scoped; drop cookies/session between tests."""
    client.delete_cookie('remember_token')
    with client.session_transaction() as sess:
        sess.clear()
    # db_reset does not drop the advancements table, and user ids repeat after a
    # reset, so rows left by an earlier test would collide with this test's rows.
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.execute('DELETE FROM advancements')
    conn.commit()
    conn.close()
    yield
    client.delete_cookie('remember_token')
    with client.session_transaction() as sess:
        sess.clear()


@contextlib.contextmanager
def _db(app):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _make_user(client, name):
    """Register a player and sign them out again."""
    assert register_user(client, name, PASSWORD).status_code == 302
    client.get('/logout')


def _user(app, name):
    with _db(app) as conn:
        return conn.execute('SELECT * FROM users WHERE username = ?', (name,)).fetchone()


# ---------------------------------------------------------------------------
# Suspension in the app
# ---------------------------------------------------------------------------

class TestSuspension:
    def test_login_refused_with_message(self, client, app):
        _make_user(client, 'Sus')
        suspend_user.main(['Sus', '--reason', 'testing'], app=app)
        resp = login_user(client, 'Sus', PASSWORD)
        assert resp.status_code == 200
        assert SUSPENDED_MESSAGE in resp.data.decode()
        assert client.get('/dashboard').status_code == 302

    def test_wrong_password_does_not_reveal_suspension(self, client, app):
        _make_user(client, 'Sus')
        suspend_user.main(['Sus'], app=app)
        resp = login_user(client, 'Sus', 'WrongPassword1!')
        assert SUSPENDED_MESSAGE not in resp.data.decode()

    def test_suspend_signs_out_existing_session(self, client, app):
        register_user(client, 'Sus', PASSWORD)
        assert client.get('/dashboard').status_code == 200
        suspend_user.main(['Sus'], app=app)
        resp = client.get('/dashboard')
        assert resp.status_code == 302 and '/login' in resp.headers['Location']

    def test_loader_rejects_suspended_even_with_current_session_version(self, client, app):
        register_user(client, 'Sus', PASSWORD)
        with _db(app) as conn:  # suspended without raising session_version
            conn.execute("UPDATE users SET suspended_at = '2024-01-01T00:00:00' WHERE username = 'Sus'")
        resp = client.get('/dashboard')
        assert resp.status_code == 302 and '/login' in resp.headers['Location']

    def test_suspend_records_reason_and_raises_session_version(self, client, app):
        _make_user(client, 'Sus')
        before = _user(app, 'Sus')['session_version']
        suspend_user.main(['Sus', '--reason', 'Offensive username'], app=app)
        row = _user(app, 'Sus')
        assert row['suspended_at'] and row['suspended_reason'] == 'Offensive username'
        assert row['session_version'] == before + 1

    def test_suspend_twice_is_a_no_op(self, client, app, capsys):
        _make_user(client, 'Sus')
        suspend_user.main(['Sus'], app=app)
        version = _user(app, 'Sus')['session_version']
        suspend_user.main(['Sus'], app=app)
        assert 'already suspended' in capsys.readouterr().out
        assert _user(app, 'Sus')['session_version'] == version

    def test_unsuspend_restores_login(self, client, app):
        _make_user(client, 'Sus')
        suspend_user.main(['Sus', '--reason', 'x'], app=app)
        unsuspend_user.main(['Sus'], app=app)
        row = _user(app, 'Sus')
        assert row['suspended_at'] is None and row['suspended_reason'] is None
        assert '/dashboard' in login_user(client, 'Sus', PASSWORD).headers['Location']

    def test_unknown_user_exits_1(self, app):
        for module in (suspend_user, unsuspend_user):
            with pytest.raises(SystemExit) as exc:
                module.main(['Ghost'], app=app)
            assert exc.value.code == 1

    def test_bot_cannot_be_suspended(self, app):
        from app.market.bots import ensure_bots_exist
        with _db(app) as conn:
            ensure_bots_exist(conn, 10000)
        with pytest.raises(SystemExit) as exc:
            suspend_user.main(['SteveBot'], app=app)
        assert exc.value.code == 1

    def test_hidden_from_leaderboard(self, client, app):
        _make_user(client, 'Visible')
        _make_user(client, 'Hidden')
        with app.app_context():
            assert {r['username'] for r in get_leaderboard()} == {'Visible', 'Hidden'}
        suspend_user.main(['Hidden'], app=app)
        with app.app_context():
            assert {r['username'] for r in get_leaderboard()} == {'Visible'}
        register_user(client, 'Viewer', PASSWORD)
        assert 'Hidden' not in client.get('/leaderboard').data.decode()

    def test_hidden_from_public_profile(self, client, app):
        _make_user(client, 'Target')
        register_user(client, 'Viewer', PASSWORD)
        assert client.get('/player/Target').status_code == 200
        suspend_user.main(['Target'], app=app)
        assert client.get('/player/Target').status_code == 404
        unsuspend_user.main(['Target'], app=app)
        assert client.get('/player/Target').status_code == 200


# ---------------------------------------------------------------------------
# rename_user
# ---------------------------------------------------------------------------

class TestSuspendRemovesPush:
    def test_suspend_deletes_push_rows_of_that_player_only(self, client, app):
        _make_user(client, 'Sus')
        _make_user(client, 'Other')
        with _db(app) as conn:
            for name, endpoint in (('Sus', 'https://push.example/a'), ('Other', 'https://push.example/b')):
                uid = conn.execute('SELECT id FROM users WHERE username = ?', (name,)).fetchone()['id']
                conn.execute(
                    "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (?, ?, 'k', 'a')",
                    (uid, endpoint))
                conn.execute(
                    "INSERT INTO push_presence (user_id, client_id, seen_at) VALUES (?, 'page', 1)", (uid,))
        suspend_user.main(['Sus'], app=app)
        with _db(app) as conn:
            rows = conn.execute(
                'SELECT u.username FROM push_subscriptions s JOIN users u ON u.id = s.user_id').fetchall()
            presence = conn.execute(
                'SELECT u.username FROM push_presence p JOIN users u ON u.id = p.user_id').fetchall()
        assert [r['username'] for r in rows] == ['Other']
        assert [r['username'] for r in presence] == ['Other']


class TestResetPasswordTwoFactor:
    def _with_2fa(self, client, app, name):
        _make_user(client, name)
        uid = _user(app, name)['id']
        with app.app_context():
            enable_2fa(uid, 'encrypted-secret')
            store_backup_codes(uid, ['hash1', 'hash2'])
        return uid

    def _state(self, app, name):
        with _db(app) as conn:
            row = conn.execute(
                'SELECT id, totp_enabled, totp_secret_encrypted, session_version FROM users WHERE username = ?',
                (name,)).fetchone()
            codes = conn.execute('SELECT COUNT(*) FROM backup_codes WHERE user_id = ?', (row['id'],)).fetchone()[0]
        return row['totp_enabled'], row['totp_secret_encrypted'], codes, row['session_version']

    def test_default_keeps_2fa_and_raises_session_version(self, client, app, capsys):
        self._with_2fa(client, app, 'Lost')
        before = self._state(app, 'Lost')
        reset_password.reset_password('Lost', 'NewPassword123!', app=app)
        after = self._state(app, 'Lost')
        assert after[:3] == before[:3] == (1, 'encrypted-secret', 2)
        assert after[3] == before[3] + 1
        assert 'Two-factor' not in capsys.readouterr().out

    def test_flag_turns_2fa_off_like_settings(self, client, app, capsys):
        self._with_2fa(client, app, 'Lost')
        before = self._state(app, 'Lost')
        reset_password.reset_password('Lost', 'NewPassword123!', app=app, turn_off_2fa=True)
        enabled, secret, codes, version = self._state(app, 'Lost')
        assert (enabled, secret, codes) == (0, None, 0)
        assert version == before[3] + 1
        out = capsys.readouterr().out
        assert 'Two-factor authentication was turned off' in out and 'Settings' in out
        assert '/dashboard' in login_user(client, 'Lost', 'NewPassword123!').headers['Location']

    def test_main_flag_and_help(self, client, app, capsys):
        self._with_2fa(client, app, 'Lost')
        with patch.object(reset_password, 'create_app', return_value=app):
            reset_password.main(['reset_password.py', 'Lost', '--random', '--disable-2fa'])
        assert self._state(app, 'Lost')[:3] == (0, None, 0)
        capsys.readouterr()
        with pytest.raises(SystemExit):
            reset_password.main(['reset_password.py', '--help'])
        assert '--disable-2fa' in capsys.readouterr().out


class TestRenameUser:
    def test_renames_and_signs_out(self, client, app, capsys):
        register_user(client, 'OldName', PASSWORD)
        assert client.get('/dashboard').status_code == 200
        before = _user(app, 'OldName')
        rename_user.main(['OldName', 'New_Name'], app=app)
        assert 'Renamed' in capsys.readouterr().out
        after = _user(app, 'New_Name')
        assert after['id'] == before['id']
        assert after['session_version'] == before['session_version'] + 1
        assert after['password_hash'] == before['password_hash']
        assert _user(app, 'OldName') is None
        assert client.get('/dashboard').status_code == 302
        assert login_user(client, 'OldName', PASSWORD).status_code == 200
        assert '/dashboard' in login_user(client, 'New_Name', PASSWORD).headers['Location']

    @pytest.mark.parametrize('bad', ['ab', 'x' * 21, 'has space', 'bad-name!', ''])
    def test_invalid_new_name_rejected(self, client, app, bad):
        _make_user(client, 'OldName')
        with pytest.raises(SystemExit) as exc:
            rename_user.main(['OldName', bad], app=app)
        assert exc.value.code == 1
        assert _user(app, 'OldName') is not None

    def test_taken_name_rejected_exact_and_case_insensitive(self, client, app):
        _make_user(client, 'OldName')
        _make_user(client, 'Taken')
        for clash in ('Taken', 'taken', 'TAKEN'):
            with pytest.raises(SystemExit) as exc:
                rename_user.main(['OldName', clash], app=app)
            assert exc.value.code == 1
        assert _user(app, 'OldName') is not None

    def test_can_change_only_the_case_of_own_name(self, client, app):
        _make_user(client, 'oldname')
        rename_user.main(['oldname', 'OldName'], app=app)
        assert _user(app, 'OldName') is not None

    def test_same_name_and_unknown_user_rejected(self, client, app):
        _make_user(client, 'OldName')
        for args in (['OldName', 'OldName'], ['Ghost', 'Whatever']):
            with pytest.raises(SystemExit) as exc:
                rename_user.main(args, app=app)
            assert exc.value.code == 1

    def test_bot_cannot_be_renamed(self, app):
        from app.market.bots import ensure_bots_exist
        with _db(app) as conn:
            ensure_bots_exist(conn, 10000)
        with pytest.raises(SystemExit) as exc:
            rename_user.main(['SteveBot', 'Harmless'], app=app)
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# export_user_data
# ---------------------------------------------------------------------------

SECRET_HASH = 'pbkdf2:sha256:SECRET-HASH-VALUE'
TOTP_SECRET = 'ENCRYPTED-TOTP-SECRET-VALUE'
BACKUP_HASH = 'BACKUP-CODE-HASH-VALUE'
RECOVERY_HASH = 'RECOVERY-KEY-HASH-VALUE'
ENDPOINT = 'https://push.example.net/send/ENDPOINT-CAPABILITY-TOKEN'
P256DH = 'P256DH-KEY-VALUE'
AUTH_KEY = 'AUTH-KEY-VALUE'


def _fill_user(app, name):
    """Give a player a row in every kind of table, with recognisable secrets."""
    with _db(app) as conn:
        uid = conn.execute('SELECT id FROM users WHERE username = ?', (name,)).fetchone()['id']
        conn.execute("UPDATE users SET password_hash = ?, totp_enabled = 1, totp_secret_encrypted = ?, "
                     "avatar_path = ?, play_time = 77, login_streak = 4 WHERE id = ?",
                     (SECRET_HASH, TOTP_SECRET, f'static/uploads/avatars/{uid}.webp', uid))
        conn.execute("INSERT INTO backup_codes (user_id, code_hash) VALUES (?, ?)", (uid, BACKUP_HASH))
        conn.execute("INSERT OR REPLACE INTO recovery_keys (user_id, key_hash) VALUES (?, ?)", (uid, RECOVERY_HASH))
        holding = conn.execute("INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) "
                               "VALUES (?, 1, 5, 10)", (uid,)).lastrowid
        conn.execute("INSERT INTO stop_loss_take_profit (holding_id, stop_loss) VALUES (?, 8)", (holding,))
        conn.execute("INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value) "
                     "VALUES (?, 1, 'buy', 5, 10, 50)", (uid,))
        conn.execute("INSERT INTO short_positions (user_id, ore_id, share_quantity, entry_price, locked_collateral, "
                     "open_factor) VALUES (?, 2, 3, 25, 100, 1.5)", (uid,))
        conn.execute("INSERT INTO advancements (user_id, advancement_key) VALUES (?, 'test_key')", (uid,))
        conn.execute("INSERT INTO notifications (user_id, category, message) VALUES (?, 'bonus', 'hello there')", (uid,))
        conn.execute("INSERT INTO tutorial_progress (user_id, track_id, status) VALUES (?, 'beginner', 'completed')", (uid,))
        conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent) "
                     "VALUES (?, ?, ?, ?, 'TestBrowser/1.0')", (uid, ENDPOINT, P256DH, AUTH_KEY))
        conn.execute("INSERT INTO push_settings (user_id, notify_bonus) VALUES (?, 0)", (uid,))
        conn.execute("INSERT INTO push_presence (user_id, client_id, seen_at) VALUES (?, 'page1', 1.0)", (uid,))
    return uid


class TestExportUserData:
    def test_export_contents_and_no_secrets(self, client, app, tmp_path):
        _make_user(client, 'Exporter')
        _make_user(client, 'Other')
        uid = _fill_user(app, 'Exporter')
        other = _user(app, 'Other')['id']
        with _db(app) as conn:  # another player's rows must not leak in
            conn.execute("INSERT INTO notifications (user_id, category, message) VALUES (?, 'bonus', 'NOT-YOURS')", (other,))
        out = tmp_path / 'export.json'
        export_user_data.main(['Exporter', '--output', str(out)], app=app)

        text = out.read_text(encoding='utf-8')
        data = json.loads(text)
        for secret in (SECRET_HASH, TOTP_SECRET, BACKUP_HASH, RECOVERY_HASH, P256DH, AUTH_KEY,
                       ENDPOINT, 'ENDPOINT-CAPABILITY-TOKEN', 'NOT-YOURS'):
            assert secret not in text

        user = data['user']
        assert user['username'] == 'Exporter' and user['id'] == uid
        assert user['play_time'] == 77 and user['login_streak'] == 4
        assert user['password_hash'] == 'present'
        assert user['totp_secret_encrypted'] == 'present'
        assert user['session_version'] == 'present'
        assert data['avatar'] == {'has_uploaded_avatar': True,
                                  'avatar_path': f'static/uploads/avatars/{uid}.webp',
                                  'fallback_colour': user['avatar_color']}

        tables = data['tables']
        assert tables['backup_codes'][0]['code_hash'] == 'present'
        assert tables['recovery_keys'][0]['key_hash'] == 'present'
        sub = tables['push_subscriptions'][0]
        assert sub['endpoint_host'] == 'push.example.net'
        assert sub['p256dh'] == 'present' and sub['auth'] == 'present'
        assert 'endpoint' not in sub and sub['user_agent'] == 'TestBrowser/1.0'
        assert tables['holdings'][0]['ore_name'] == 'Coal'
        assert tables['stop_loss_take_profit'][0]['stop_loss'] == 8
        assert tables['transactions'][0]['type'] == 'buy'
        assert tables['short_positions'][0]['share_quantity'] == 3
        assert 'test_key' in [a['advancement_key'] for a in tables['advancements']]
        assert tables['notifications'][0]['message'] == 'hello there'
        assert tables['tutorial_progress'][0]['status'] == 'completed'
        assert tables['push_settings'][0]['notify_bonus'] == 0
        assert len(tables['push_presence']) == 1

    def test_every_user_id_table_is_covered(self, client, app, tmp_path):
        _make_user(client, 'Exporter')
        out = tmp_path / 'export.json'
        export_user_data.main(['Exporter', '--output', str(out)], app=app)
        exported = set(json.loads(out.read_text(encoding='utf-8'))['tables'])
        with _db(app) as conn:
            names = [r['name'] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
            with_user_id = {n for n in names if n != 'users'
                            and 'user_id' in [c['name'] for c in conn.execute(f'PRAGMA table_info("{n}")')]}
        assert with_user_id  # sanity: the schema really has such tables
        assert with_user_id <= exported
        assert 'stop_loss_take_profit' in exported

    def test_default_output_file_and_unknown_user(self, client, app, tmp_path, monkeypatch):
        _make_user(client, 'Exporter')
        monkeypatch.chdir(tmp_path)
        export_user_data.main(['Exporter'], app=app)
        files = list(tmp_path.glob('orex-export-Exporter-*.json'))
        assert len(files) == 1
        with pytest.raises(SystemExit) as exc:
            export_user_data.main(['Ghost'], app=app)
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# remove_avatar
# ---------------------------------------------------------------------------

class TestRemoveAvatar:
    def _setup(self, client, app, tmp_path, monkeypatch):
        _make_user(client, 'Pic')
        uid = _user(app, 'Pic')['id']
        storage = LocalStorage(str(tmp_path))
        storage.store(f'{uid}.webp', b'RIFFfake', 'image/webp')
        with _db(app) as conn:
            conn.execute("UPDATE users SET avatar_path = ? WHERE id = ?", (f'static/uploads/avatars/{uid}.webp', uid))
        monkeypatch.setattr(remove_avatar, 'get_storage_backend', lambda app: storage)
        return uid

    def test_deletes_file_and_clears_path(self, client, app, tmp_path, monkeypatch):
        uid = self._setup(client, app, tmp_path, monkeypatch)
        assert (tmp_path / f'{uid}.webp').exists()
        remove_avatar.main(['Pic'], app=app)
        assert not (tmp_path / f'{uid}.webp').exists()
        assert _user(app, 'Pic')['avatar_path'] is None

    def test_missing_file_still_clears_path(self, client, app, tmp_path, monkeypatch):
        uid = self._setup(client, app, tmp_path, monkeypatch)
        (tmp_path / f'{uid}.webp').unlink()
        remove_avatar.main(['Pic'], app=app)
        assert _user(app, 'Pic')['avatar_path'] is None

    def test_no_avatar_is_a_no_op(self, client, app, capsys):
        _make_user(client, 'Plain')
        remove_avatar.main(['Plain'], app=app)
        assert 'no uploaded avatar' in capsys.readouterr().out

    def test_storage_error_keeps_path_and_exits_1(self, client, app, tmp_path, monkeypatch):
        self._setup(client, app, tmp_path, monkeypatch)

        class Broken:
            def delete(self, filename):
                raise RuntimeError('bucket unreachable')

        monkeypatch.setattr(remove_avatar, 'get_storage_backend', lambda app: Broken())
        with pytest.raises(SystemExit) as exc:
            remove_avatar.main(['Pic'], app=app)
        assert exc.value.code == 1
        assert _user(app, 'Pic')['avatar_path']

    def test_unknown_user_exits_1(self, app):
        with pytest.raises(SystemExit) as exc:
            remove_avatar.main(['Ghost'], app=app)
        assert exc.value.code == 1

    def test_app_uses_local_storage_by_default(self, app):
        from app.storage import get_storage_backend
        assert isinstance(get_storage_backend(app), LocalStorage)


# ---------------------------------------------------------------------------
# reset_economy
# ---------------------------------------------------------------------------

def _economy_state(app):
    """A player with holdings, a short and trades, a bot with a holding, moved prices."""
    from app.market.bots import ensure_bots_exist
    with _db(app) as conn:
        ensure_bots_exist(conn, 10000)
        player = conn.execute("SELECT id FROM users WHERE username = 'Player'").fetchone()['id']
        bot = conn.execute("SELECT id FROM users WHERE username = 'SteveBot'").fetchone()['id']
        conn.execute("UPDATE users SET balance = 123456, advanced_purchased = 1, avatar_path = 'static/uploads/avatars/x.webp', "
                     "play_time = 50, login_streak = 3, bonus_cycle_day = 3 WHERE id = ?", (player,))
        conn.execute("UPDATE users SET balance = 5 WHERE id = ?", (bot,))
        for uid in (player, bot):
            holding = conn.execute("INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) VALUES (?, 1, 4, 10)",
                                   (uid,)).lastrowid
            conn.execute("INSERT INTO stop_loss_take_profit (holding_id, stop_loss) VALUES (?, 5)", (holding,))
            conn.execute("INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value) "
                         "VALUES (?, 1, 'buy', 4, 10, 40)", (uid,))
            conn.execute("INSERT INTO short_positions (user_id, ore_id, share_quantity, entry_price, locked_collateral, "
                         "open_factor) VALUES (?, 2, 1, 25, 40, 1.6)", (uid,))
        conn.execute("INSERT INTO advancements (user_id, advancement_key) VALUES (?, 'test_key')", (player,))
        conn.execute("INSERT INTO notifications (user_id, category, message) VALUES (?, 'bonus', 'hi')", (player,))
        conn.execute("INSERT INTO tutorial_progress (user_id, track_id, status) VALUES (?, 'beginner', 'completed')", (player,))
        conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (?, 'https://e.example/1', 'k', 'a')", (player,))
        conn.execute("UPDATE ores SET current_price = base_price * 2, trend_log = '[\"rise\",\"rise\",\"rise\",\"rise\",\"rise\"]'")
        conn.execute("INSERT INTO price_history (ore_id, price, movement) VALUES (1, 20, 'rise')")
    return player, bot


def _snapshot(app):
    with _db(app) as conn:
        return {
            'users': [tuple(r) for r in conn.execute('SELECT * FROM users ORDER BY id')],
            'ores': [tuple(r) for r in conn.execute('SELECT * FROM ores ORDER BY id')],
            'holdings': conn.execute('SELECT COUNT(*) FROM holdings').fetchone()[0],
            'transactions': [tuple(r) for r in conn.execute('SELECT * FROM transactions ORDER BY id')],
            'price_history': conn.execute('SELECT COUNT(*) FROM price_history').fetchone()[0],
        }


class TestResetEconomy:
    def test_dry_run_prints_counts_and_changes_nothing(self, client, app, capsys):
        _make_user(client, 'Player')
        _economy_state(app)
        before = _snapshot(app)
        reset_economy.main(['--dry-run'], app=app)
        out = capsys.readouterr().out
        assert 'dry run' in out
        assert 'players: 1' in out and 'bots: 9' in out and 'holdings: 2' in out and 'active_shorts: 2' in out
        assert _snapshot(app) == before

    def test_real_run_matches_account_reset_and_resets_prices_and_bots(self, client, app, capsys):
        _make_user(client, 'Player')
        player, bot = _economy_state(app)
        before = _user(app, 'Player')
        reset_economy.main(['--yes'], app=app)
        assert 'Reset 1 players, 9 bots and 9 ores' in capsys.readouterr().out

        with _db(app) as conn:
            default = app.config['DEFAULT_BALANCE']
            after = conn.execute('SELECT * FROM users WHERE id = ?', (player,)).fetchone()
            assert after['balance'] == default
            assert after['advanced_purchased'] == 0 and after['bonus_cycle_day'] == 1
            assert after['session_version'] == before['session_version'] + 1
            # Kept, as with Settings > Reset Account
            assert after['username'] == 'Player' and after['password_hash'] == before['password_hash']
            assert after['avatar_path'] == 'static/uploads/avatars/x.webp'
            assert after['play_time'] == 50 and after['login_streak'] == 3
            assert conn.execute('SELECT COUNT(*) FROM advancements WHERE user_id = ? AND advancement_key = ?', (player, 'test_key')).fetchone()[0] == 1
            # Cleared
            for table in ('holdings', 'short_positions', 'notifications', 'tutorial_progress', 'push_subscriptions'):
                assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0, table
            assert conn.execute('SELECT COUNT(*) FROM stop_loss_take_profit').fetchone()[0] == 0
            # Player history is archived, not deleted; bot history is gone
            assert conn.execute('SELECT archived FROM transactions WHERE user_id = ?', (player,)).fetchone()[0] == 1
            assert conn.execute('SELECT COUNT(*) FROM transactions WHERE user_id = ?', (bot,)).fetchone()[0] == 0
            # Bots back to a new database; prices back to base
            assert conn.execute('SELECT balance FROM users WHERE id = ?', (bot,)).fetchone()[0] == default
            assert conn.execute('SELECT COUNT(*) FROM ores WHERE current_price != base_price').fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM ores WHERE trend_log != '[\"hold\",\"hold\",\"hold\",\"hold\",\"hold\"]'").fetchone()[0] == 0
            assert conn.execute('SELECT COUNT(*) FROM price_history').fetchone()[0] == 0

    def test_signs_players_out(self, client, app):
        register_user(client, 'Player', PASSWORD)
        assert client.get('/dashboard').status_code == 200
        reset_economy.main(['--yes'], app=app)
        assert client.get('/dashboard').status_code == 302

    def test_suspension_is_kept(self, client, app):
        _make_user(client, 'Player')
        suspend_user.main(['Player'], app=app)
        reset_economy.main(['--yes'], app=app)
        assert _user(app, 'Player')['suspended_at']

    def test_wrong_confirmation_changes_nothing(self, client, app):
        _make_user(client, 'Player')
        _economy_state(app)
        before = _snapshot(app)
        with pytest.raises(SystemExit) as exc:
            reset_economy.main([], app=app, input_fn=lambda prompt: 'reset')
        assert exc.value.code == 1
        assert _snapshot(app) == before

    def test_typed_reset_confirms(self, client, app):
        _make_user(client, 'Player')
        _economy_state(app)
        reset_economy.main([], app=app, input_fn=lambda prompt: 'RESET')
        assert _snapshot(app)['holdings'] == 0
