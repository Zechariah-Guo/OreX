"""Tests for the logged-out landing page: live ticker, config-driven numbers, routing."""

import re
import sqlite3

from conftest import register_user


class TestLandingPage:

    def test_renders_for_visitors_with_config_numbers(self, client):
        html = client.get('/').data.decode('utf-8')
        assert 'Start with $10,000' in html
        assert 'Reach $100,000 net worth' in html
        assert 'Advanced Mode for $50,000' in html
        # Beginner bonus total comes from BONUS_AMOUNTS (1k + 10k + 50k)
        assert "$1,000, $10,000, $50,000" in html
        assert "That's $61,000 extra" in html
        # Screenshots and the final call to action
        for name in ('market', 'chart', 'advanced'):
            assert f'images/landing/{name}.webp' in html
        assert html.count('Create Account') >= 2

    def test_screenshot_files_exist(self, app):
        import os
        folder = os.path.join(app.static_folder, 'images', 'landing')
        for name in ('market.webp', 'chart.webp', 'advanced.webp'):
            assert os.path.exists(os.path.join(folder, name)), name

    def test_logged_in_players_are_redirected(self, client):
        register_user(client, 'LandingUser', 'Password123!')
        resp = client.get('/')
        assert resp.status_code == 302
        assert '/dashboard' in resp.headers['Location']


class TestLandingTicker:

    def test_ticker_lists_all_ores_with_prices_and_is_doubled_for_looping(self, client, app):
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        conn.execute("UPDATE ores SET current_price = 123.45 WHERE name = 'Diamond'")
        conn.commit()
        conn.close()

        html = client.get('/').data.decode('utf-8')
        assert 'id="lp-ticker"' in html
        # 9 ores, rendered twice for the seamless marquee loop
        assert html.count('class="lp-ticker__item"') == 18
        assert '$123.45' in html
        # The duplicate list is hidden from assistive tech
        assert html.count('class="lp-ticker__list" aria-hidden="true"') == 1

    def test_htmx_refresh_returns_only_the_ticker(self, client):
        resp = client.get('/', headers={'HX-Request': 'true'})
        html = resp.data.decode('utf-8')
        assert resp.status_code == 200
        assert '<!DOCTYPE' not in html
        assert 'id="lp-ticker"' in html
        assert 'How it works' not in html

    def test_ticker_exposes_only_public_ore_fields(self, client):
        html = client.get('/').data.decode('utf-8')
        # Names, icons, prices, trends only: no volatility, base price or ids
        ticker = html[html.index('id="lp-ticker"'):html.index('How it works')]
        assert 'Vol' not in ticker and 'Base' not in ticker
        assert re.search(r'lp-ticker__trend--(rise|fall|hold)', ticker)
