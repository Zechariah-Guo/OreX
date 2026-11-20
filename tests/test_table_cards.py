"""Markup tests for the phone card layouts of the Portfolio, History and Leaderboard tables.

Below the card breakpoint the tables are restyled with CSS only, so the markup must
keep every cell labelled (data-label) and keep the table roles, while the data and
the forms/buttons stay exactly as the desktop table renders them.
"""

import re
import sqlite3

import pytest

pytestmark = pytest.mark.portfolio


def _db(app):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    return conn


def _user_id(app, username='TestUser1'):
    conn = _db(app)
    row = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    return row['id']


def _make_advanced(app):
    conn = _db(app)
    conn.execute('UPDATE users SET advanced_eligible=1, advanced_purchased=1, advanced_active=1, '
                 'balance=100000 WHERE username=?', ('TestUser1',))
    conn.commit()
    conn.close()


def _add_holding(app, ore_id=1, quantity=5, avg=10.0, sl=None, tp=None):
    conn = _db(app)
    cur = conn.execute('INSERT INTO holdings (user_id, ore_id, quantity, avg_purchase_price) VALUES (?,?,?,?)',
                       (_user_id(app), ore_id, quantity, avg))
    holding_id = cur.lastrowid
    if sl is not None or tp is not None:
        conn.execute('INSERT INTO stop_loss_take_profit (holding_id, stop_loss, take_profit, active) '
                     'VALUES (?,?,?,1)', (holding_id, sl, tp))
    conn.commit()
    conn.close()
    return holding_id


def _cells(html, tag='td'):
    return re.findall(r'<%s [^>]*data-label="([^"]+)"' % tag, html)


class TestPortfolioCards:
    def test_standard_holdings_cells_are_labelled(self, app, authenticated_client):
        _add_holding(app)
        html = authenticated_client.get('/portfolio').data.decode()
        assert '<table class="holdings-table" role="table">' in html
        labels = _cells(html)
        assert labels == ['Ore', 'Quantity', 'Avg. price', 'Current price', 'Value', 'Profit / Loss', 'Trade']
        # the same data and the Qty + Buy + Sell controls are still there
        assert 'Coal' in html and '10.00' in html
        assert 'class="quick-trade-input"' in html and 'hx-preserve="true"' in html
        assert html.count('class="qt-form"') == 2
        assert 'Edit SL/TP' not in html

    def test_advanced_holdings_show_only_set_sltp_parts(self, app, authenticated_client):
        _make_advanced(app)
        _add_holding(app, ore_id=1, sl=8.0, tp=None)
        html = authenticated_client.get('/portfolio').data.decode()
        assert _cells(html) == ['Ore', 'Quantity', 'Avg. price', 'Current price', 'Value',
                                'Profit / Loss', 'SL / TP', 'Actions']
        sltp = re.search(r'<td [^>]*data-label="SL / TP">(.*?)</td>', html, re.DOTALL).group(1)
        assert '8.00' in sltp
        # SL is set, TP is not: only the TP part is flagged as unset
        parts = re.findall(r'<span class="sltp-part( sltp-part--unset)?">', sltp)
        assert parts == ['', ' sltp-part--unset']
        assert 'Edit SL/TP' in html and 'openSltpModal(this)' in html
        assert 'data-type="long"' in html

    def test_holding_without_sltp_is_flagged_empty(self, app, authenticated_client):
        _make_advanced(app)
        _add_holding(app)
        html = authenticated_client.get('/portfolio').data.decode()
        assert 'sltp-cell--empty' in html

    def test_short_rows_are_labelled_and_carry_the_hint(self, app, authenticated_client):
        _make_advanced(app)
        conn = _db(app)
        conn.execute('INSERT INTO short_positions (user_id, ore_id, share_quantity, entry_price, locked_collateral,'
                     ' stop_loss_price, take_profit_price, cumulative_fees_paid) VALUES (?,?,?,?,?,?,?,?)',
                     (_user_id(app), 1, 4, 12.0, 72.0, 15.0, None, 0.5))
        conn.commit()
        conn.close()
        html = authenticated_client.get('/portfolio?tab=shorts').data.decode()
        assert '<table class="shorts-table" role="table">' in html
        shorts = html.split('<table class="shorts-table"', 1)[1]
        assert _cells(shorts) == ['Ore', 'Quantity', 'Entry price', 'Current price', 'Net P/L',
                                  'Squeeze price', 'SL / TP', 'Actions']
        assert 'Unrealized price P/L minus cumulative fees paid' in shorts.split('data-label="Net P/L"', 1)[1]
        assert 'data-type="short"' in shorts and 'Close</button>' in shorts


class TestHistoryCards:
    def test_history_rows_are_labelled_and_keep_their_data(self, app, authenticated_client):
        conn = _db(app)
        uid = _user_id(app)
        for t in ('buy', 'sell', 'short_open', 'short_close', 'short_liquidated'):
            conn.execute('INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value, '
                         'created_at) VALUES (?,?,?,?,?,?,?)', (uid, 1, t, 3, 10.0, 30.0, '2026-01-02T03:04:05'))
        conn.commit()
        conn.close()
        html = authenticated_client.get('/history').data.decode()
        assert '<table class="history-table" role="table">' in html
        row = re.search(r'<tr role="row" class="[^"]*">\s*<td [^>]*data-label="Date">', html)
        assert row
        assert _cells(html)[:6] == ['Date', 'Ore', 'Type', 'Quantity', 'Price', 'Total']
        for badge in ('BUY', 'SELL', 'OPEN SHORT', 'CLOSE SHORT', 'LIQUIDATED'):
            assert badge in html
        assert '2026-01-02 03:04' in html and '$30.00' in html

    def test_history_ore_has_an_icon_before_the_name(self, app, authenticated_client):
        conn = _db(app)
        conn.execute('INSERT INTO transactions (user_id, ore_id, type, quantity, price_at_trade, total_value) '
                     'VALUES (?,?,?,?,?,?)', (_user_id(app), 1, 'buy', 1, 10.0, 10.0))
        conn.commit()
        conn.close()
        html = authenticated_client.get('/history').data.decode()
        assert re.search(r'data-label="Ore"><span class="ore-inline"><img src="[^"]*images/ores/Coal\.webp" '
                         r'alt="" class="ore-inline-icon"[^>]*><span>Coal</span>', html)


class TestPortfolioOreIcons:
    def test_longs_have_an_icon_before_the_name(self, app, authenticated_client):
        _add_holding(app)
        html = authenticated_client.get('/portfolio').data.decode()
        assert re.search(r'<img src="[^"]*images/ores/Coal\.webp" alt="" class="ore-inline-icon"[^>]*><span>Coal</span></a>', html)

    def test_shorts_have_an_icon_before_the_name(self, app, authenticated_client):
        _make_advanced(app)
        conn = _db(app)
        conn.execute('INSERT INTO short_positions (user_id, ore_id, share_quantity, entry_price, locked_collateral) '
                     'VALUES (?,?,?,?,?)', (_user_id(app), 1, 4, 12.0, 72.0))
        conn.commit()
        conn.close()
        html = authenticated_client.get('/portfolio?tab=shorts').data.decode()
        shorts = html.split('<table class="shorts-table"', 1)[1]
        assert re.search(r'<img src="[^"]*images/ores/Coal\.webp" alt="" class="ore-inline-icon"[^>]*><span>Coal</span></a>', shorts)


class TestLeaderboardRows:
    def _page(self, app, authenticated_client):
        from app.database import get_db
        from app.market.bots import ensure_bots_exist
        with app.app_context():
            ensure_bots_exist(get_db(), app.config['DEFAULT_BALANCE'])
        return authenticated_client.get('/leaderboard').data.decode()

    def test_every_row_is_expandable_with_a_chevron_button(self, app, authenticated_client):
        html = self._page(app, authenticated_client)
        rows = re.findall(r'<tr role="row" class="[^"]*" data-player-id="(\d+)">', html)
        assert len(rows) > 1 and len(set(rows)) == len(rows)
        assert html.count('class="leaderboard-table__chevron"') == len(rows)
        assert html.count('class="leaderboard-table__chevron" aria-expanded="false"') == len(rows)
        for label in ('Balance', 'Holdings', 'Short equity', 'Total value'):
            assert 'data-label="%s"' % label in html

    def test_player_link_stays_and_bots_stay_unlinked(self, app, authenticated_client):
        html = self._page(app, authenticated_client)
        me = re.search(r'<tr [^>]*leaderboard-table__row--current[^>]*>.*?</tr>', html, re.DOTALL).group(0)
        assert 'href="/profile"' in me
        bot_rows = [r for r in re.findall(r'<tr .*?</tr>', html, re.DOTALL) if 'leaderboard-avatar--bot' in r]
        assert bot_rows
        assert all('leaderboard__player-link' not in r for r in bot_rows)

    def test_leaderboard_page_has_the_expand_script(self, app, authenticated_client):
        html = authenticated_client.get('/leaderboard').data.decode()
        assert 'htmx:afterSwap' in html and 'data-player-id' in html
