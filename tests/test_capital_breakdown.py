"""Tests for the Finances page Capital Breakdown allocation bar.

Unit tests cover build_capital_breakdown()'s geometry, especially negative
short equity (the case a plain stacked bar or donut can't draw). Integration
tests render /finances and check the bar, overlay and legend.
"""

import sqlite3

import pytest

from app.finances import build_capital_breakdown

pytestmark = pytest.mark.finances


def _pcts(cb):
    return {s['key']: s['pct'] for s in cb['segments']}


# ---------------------------------------------------------------------------
# Unit: build_capital_breakdown
# ---------------------------------------------------------------------------

class TestBuildCapitalBreakdown:

    def test_no_shorts_segments_are_share_of_net_worth(self):
        cb = build_capital_breakdown(750.0, 250.0, 0.0, has_shorts=False)
        assert _pcts(cb) == {'free_cash': 75.0, 'holdings': 25.0}
        assert cb['assets'] == 1000.0
        assert cb['loss'] == 0.0 and cb['loss_pct'] == 0.0
        assert cb['net_pct'] is None
        assert cb['show_shorts'] is False

    def test_profitable_short_is_a_third_segment(self):
        cb = build_capital_breakdown(500.0, 300.0, 200.0, has_shorts=True)
        assert _pcts(cb) == {'free_cash': 50.0, 'holdings': 30.0, 'short_equity': 20.0}
        assert sum(_pcts(cb).values()) == pytest.approx(100.0)
        assert cb['net_pct'] is None

    def test_losing_short_is_an_overlay_not_a_segment(self):
        # Assets 1000, short equity -200 -> net worth 800
        cb = build_capital_breakdown(600.0, 400.0, -200.0, has_shorts=True)
        assert 'short_equity' not in _pcts(cb)
        assert _pcts(cb) == {'free_cash': 60.0, 'holdings': 40.0}
        assert cb['loss'] == 200.0
        assert cb['loss_pct'] == pytest.approx(20.0)
        assert cb['net_pct'] == pytest.approx(80.0)  # 800 / 1000 assets

    def test_loss_larger_than_assets_is_clamped(self):
        cb = build_capital_breakdown(50.0, 0.0, -500.0, has_shorts=True)
        assert cb['loss_pct'] == 100.0
        assert cb['net_pct'] == 0.0

    def test_loss_with_no_assets_fills_the_bar(self):
        cb = build_capital_breakdown(0.0, 0.0, -10.0, has_shorts=True)
        assert cb['assets'] == 0.0
        assert all(s['pct'] == 0.0 for s in cb['segments'])
        assert cb['loss_pct'] == 100.0 and cb['net_pct'] == 0.0

    def test_everything_zero_is_an_empty_bar(self):
        cb = build_capital_breakdown(0.0, 0.0, 0.0, has_shorts=False)
        assert all(s['pct'] == 0.0 for s in cb['segments'])
        assert cb['loss_pct'] == 0.0 and cb['net_pct'] is None

    def test_breakeven_short_adds_no_segment(self):
        cb = build_capital_breakdown(100.0, 0.0, 0.0, has_shorts=True)
        assert 'short_equity' not in _pcts(cb)
        assert cb['show_shorts'] is True  # legend line still shown
        assert cb['loss'] == 0.0


# ---------------------------------------------------------------------------
# Integration: rendered /finances
# ---------------------------------------------------------------------------

def _make_advanced(app, balance):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.execute(
        """UPDATE users SET advanced_eligible = 1, advanced_purchased = 1,
               advanced_active = 1, balance = ? WHERE username = 'TestUser1'""",
        (balance,),
    )
    user_id = conn.execute("SELECT id FROM users WHERE username = 'TestUser1'").fetchone()[0]
    conn.commit()
    conn.close()
    return user_id


def _add_short(app, user_id, locked_collateral):
    """10 Diamond shares; seeded Diamond price is $100, so buyback = $1,000."""
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.execute("UPDATE ores SET current_price = 100.0 WHERE id = 8")
    conn.execute(
        """INSERT INTO short_positions
           (user_id, ore_id, share_quantity, entry_price, locked_collateral,
            cumulative_fees_paid, status, open_factor)
           VALUES (?, 8, 10, 100.0, ?, 0.0, 'active', 1.5)""",
        (user_id, locked_collateral),
    )
    conn.commit()
    conn.close()


class TestCapitalBreakdownPage:

    def test_no_shorts_hides_short_equity_line(self, authenticated_client, app):
        _make_advanced(app, balance=5000.0)
        html = authenticated_client.get('/finances').data.decode('utf-8')
        assert 'id="finances-capital"' in html  # tutorial selector kept
        assert 'capital__headline-value">$5,000.00' in html
        assert 'capital__bar-seg--free_cash' in html
        assert 'Short Equity' not in html
        assert 'capital__bar-loss' not in html

    def test_profitable_short_renders_purple_segment(self, authenticated_client, app):
        user_id = _make_advanced(app, balance=1000.0)
        _add_short(app, user_id, locked_collateral=1500.0)  # equity +500
        html = authenticated_client.get('/finances').data.decode('utf-8')
        assert 'capital__bar-seg--short_equity' in html
        assert 'capital__bar-loss' not in html
        assert 'from $1,500.00 locked' in html
        assert 'capital__headline-value">$1,500.00' in html  # 1000 + 500

    def test_losing_short_renders_overlay_and_marker(self, authenticated_client, app):
        user_id = _make_advanced(app, balance=1000.0)
        _add_short(app, user_id, locked_collateral=800.0)  # equity -200
        html = authenticated_client.get('/finances').data.decode('utf-8')
        assert 'capital__bar-seg--short_equity' not in html
        assert 'capital__bar-loss" style="width: 20.000%' in html   # 200 / 1000 assets
        assert 'capital__bar-marker" style="left: 80.000%' in html
        assert '-$200.00' in html
        assert 'Buyback costs more than the $800.00 locked' in html
        assert 'minus a $200.00 short loss' in html  # screen-reader label
        assert 'capital__headline-value">$800.00' in html
