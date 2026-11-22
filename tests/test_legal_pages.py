"""Legal pages, footer links, Minecraft notice, and self-hosted vendor libraries."""

import os
import re

import pytest

EMAIL = 'orexsupport@gmail.com'
NOTICE = 'NOT AN OFFICIAL MINECRAFT PRODUCT. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT.'
CDN_HOSTS = ('unpkg.com', 'jsdelivr', 'cdnjs')

VENDOR_FILES = (
    'vendor/htmx/1.9.12/htmx.min.js',
    'vendor/htmx/1.9.12/LICENSE',
    'vendor/alpinejs/3.17.5/cdn.min.js',
    'vendor/alpinejs/3.17.5/LICENSE',
    'vendor/apexcharts/4.7.0/apexcharts.min.js',
    'vendor/apexcharts/4.7.0/LICENSE',
    'vendor/cropperjs/1.6.2/cropper.min.js',
    'vendor/cropperjs/1.6.2/cropper.min.css',
    'vendor/cropperjs/1.6.2/LICENSE',
)


@pytest.mark.parametrize('path', ['/privacy', '/terms'])
class TestLegalPages:
    def test_logged_out(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 200
        html = resp.data.decode()
        assert EMAIL in html
        assert NOTICE in html
        assert re.search(r'Last updated: \d{1,2} \w+ \d{4}', html)
        assert 'good faith' in html

    def test_logged_in(self, authenticated_client, path):
        resp = authenticated_client.get(path)
        assert resp.status_code == 200
        html = resp.data.decode()
        assert EMAIL in html and NOTICE in html


def _text(client, path):
    """Page text with tags removed and whitespace collapsed."""
    html = client.get(path).data.decode()
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).replace('&rsquo;', '\u2019')


class TestPrivacyWording:
    def test_game_data_push_and_logs(self, client):
        text = _text(client, '/privacy')
        for needle in ('stop loss and take profit orders', 'peak net worth', 'Advanced Mode status',
                       'daily bonus progress', 'Google, Apple, Microsoft or Mozilla',
                       'Cloudflare, which sits in front of the server, also keeps its own logs'):
            assert needle in text

    def test_other_players_and_no_avatar_privacy_claim(self, client):
        text = _text(client, '/privacy')
        assert 'Other players can see your username and avatar' in text
        assert 'signed-in players can see the leaderboard and profile pages' in text
        assert 'without signing in' not in text

    def test_cookie_paragraph_has_no_table(self, client):
        html = client.get('/privacy').data.decode()
        html = html[html.index('class="static-page"'):]
        html = html[:html.index('<footer')] if '<footer' in html else html
        text = _text(client, '/privacy')
        assert 'sign-in cookie' in text and '30 days' in text and 'no cookie banner' in text
        assert '<table' not in html
        for name in ('remember_token', 'orex-theme', 'sessionStorage', 'localStorage'):
            assert name not in html

    def test_reset_economy_suspension_and_backups(self, client):
        text = _text(client, '/privacy')
        assert 'reset the whole game' in text
        assert 'the same result as Reset Account' in text
        assert 'suspends your account, you cannot sign in' in text
        assert 'Nothing is deleted, and a suspension can be lifted' in text
        assert ('A nightly backup of the database is kept for up to 14 days, so data from a deleted '
                'account can remain in a backup until it expires.') in text
        assert 'unlocked themes' in text and 'restarts the daily bonus cycle' in text

    def test_rights_have_no_reply_time_promise(self, client):
        text = _text(client, '/privacy')
        rights = text[text.index('Your choices and rights'):text.index('Children')]
        assert 'turn off two-factor authentication if you have lost access to it' in rights
        assert 'secrets such as your password are not included' in rights
        assert 'sign out your other devices' in rights
        assert not re.search(r'within\b[^.]*\b(days?|weeks?|hours?|business)', rights, re.I)
        assert 'aim to reply' not in rights


class TestTermsWording:
    def test_accounts_section(self, client):
        text = _text(client, '/terms')
        assert 'rename a username or remove an avatar' in text
        assert 'A suspension can be lifted' in text
        assert 'A wipe resets every player\u2019s balance, holdings and Advanced Mode' in text


class TestFooterAndRegister:
    @pytest.mark.parametrize('path', ['/', '/login', '/register', '/about', '/privacy', '/terms'])
    def test_footer_links_logged_out(self, client, path):
        html = client.get(path).data.decode()
        footer = html[html.index('<footer'):]
        assert 'href="/privacy"' in footer and 'href="/terms"' in footer
        assert NOTICE in footer

    @pytest.mark.parametrize('path', ['/dashboard', '/settings', '/market', '/profile'])
    def test_footer_links_logged_in(self, authenticated_client, path):
        html = authenticated_client.get(path, follow_redirects=True).data.decode()
        footer = html[html.index('<footer'):]
        assert 'href="/privacy"' in footer and 'href="/terms"' in footer
        assert NOTICE in footer

    def test_register_agreement_line(self, client):
        html = client.get('/register').data.decode()
        assert 'By creating an account you agree to the' in html
        line = html[html.index('By creating an account'):]
        line = line[:line.index('</p>')]
        assert 'href="/terms"' in line and 'href="/privacy"' in line

    def test_about_has_notice_and_credits(self, client):
        html = client.get('/about').data.decode()
        assert NOTICE in html
        assert 'minecraft.wiki' in html and 'Apache License 2.0' in html

    def test_naming(self, client):
        landing = client.get('/').data.decode()
        assert '<title>OreX - Gamified Stock Market</title>' in landing
        assert 'Gamified Stock Market Simulation' in landing
        assert 'Minecraft Stock Market' not in landing
        manifest = client.get('/manifest.webmanifest').get_json()
        assert 'gamified stock market' in manifest['description']


class TestSelfHostedLibraries:
    @pytest.mark.parametrize('name', VENDOR_FILES)
    def test_vendor_file_served(self, client, name):
        resp = client.get('/static/' + name)
        assert resp.status_code == 200
        assert len(resp.data) > 500
        resp.close()

    def test_vendor_readme_lists_each_library(self, app):
        with open(os.path.join(app.static_folder, 'vendor', 'README.md'), encoding='utf-8') as f:
            text = f.read()
        for needle in ('htmx', 'Alpine.js', 'ApexCharts', 'Cropper.js', 'sha384-'):
            assert needle in text

    def test_templates_reference_no_cdn(self, app):
        template_dir = os.path.join(os.path.dirname(app.static_folder), 'templates')
        offenders = []
        for root, _, files in os.walk(template_dir):
            for name in files:
                with open(os.path.join(root, name), encoding='utf-8') as f:
                    text = f.read()
                offenders += [f'{name}: {h}' for h in CDN_HOSTS if h in text]
        assert not offenders

    def test_base_pages_use_local_scripts(self, client):
        html = client.get('/login').data.decode()
        assert '/static/vendor/htmx/1.9.12/htmx.min.js?v=' in html
        for host in CDN_HOSTS:
            assert host not in html

    def test_profile_and_ore_pages_have_no_cdn(self, authenticated_client):
        profile = authenticated_client.get('/profile').data.decode()
        assert '/static/vendor/cropperjs/1.6.2/cropper.min.js?v=' in profile
        assert '/static/vendor/cropperjs/1.6.2/cropper.min.css?v=' in profile
        ore = authenticated_client.get('/market/1').data.decode()
        for page in (profile, ore):
            for host in CDN_HOSTS:
                assert host not in page

    def test_csp_has_no_cdn_hosts(self, client):
        csp = client.get('/login').headers['Content-Security-Policy']
        for host in CDN_HOSTS + ('cloudflare',):
            assert host not in csp
        assert "script-src 'self' 'unsafe-inline' 'unsafe-eval';" in csp
