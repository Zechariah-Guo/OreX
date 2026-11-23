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
