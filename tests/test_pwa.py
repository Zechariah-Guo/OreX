"""Tests for the PWA pieces: manifest, service worker, offline page, head tags, install block.

The app caches NO live data. The only cached files are the offline fallback page
and its logo, so these tests also pin the service worker's precache list.
"""

import json
import os
import re

from PIL import Image


def _manifest(client):
    resp = client.get('/manifest.webmanifest')
    assert resp.status_code == 200
    return resp, json.loads(resp.data)


class TestManifest:

    def test_served_as_manifest_json_without_login(self, client):
        resp, data = _manifest(client)
        assert resp.mimetype == 'application/manifest+json'
        for key in ('name', 'short_name', 'start_url', 'scope', 'display',
                    'background_color', 'theme_color', 'description', 'icons'):
            assert data.get(key), key
        assert data['name'] == 'OreX' and data['short_name'] == 'OreX'
        assert data['start_url'] == '/' and data['scope'] == '/'
        assert data['display'] == 'standalone'
        assert data.get('prefer_related_applications') is not True

    def test_has_192_and_512_icons_for_any_and_maskable(self, client):
        _, data = _manifest(client)
        pairs = {(i['sizes'], i['purpose']) for i in data['icons']}
        for size in ('192x192', '512x512'):
            assert (size, 'any') in pairs
            assert (size, 'maskable') in pairs

    def test_every_image_resolves_with_declared_size(self, client):
        _, data = _manifest(client)
        images = data['icons'] + data['screenshots']
        assert len(images) == 10
        for image in images:
            assert image['src'].startswith('/static/')
            resp = client.get(image['src'])
            assert resp.status_code == 200, image['src']
            path = os.path.join(client.application.static_folder, image['src'][len('/static/'):])
            with Image.open(path) as img:
                assert f'{img.width}x{img.height}' == image['sizes'], image['src']
            resp.close()

    def test_screenshot_form_factors(self, client):
        _, data = _manifest(client)
        assert {s['form_factor'] for s in data['screenshots']} == {'wide', 'narrow'}


class TestServiceWorker:

    def test_served_from_root_as_javascript_with_no_cache(self, client):
        resp = client.get('/sw.js')
        assert resp.status_code == 200
        assert resp.mimetype in ('text/javascript', 'application/javascript')
        assert resp.headers['Cache-Control'] == 'no-cache'
        resp.close()

    def test_precaches_only_the_offline_page_and_logo(self, client):
        source = client.get('/sw.js').data.decode('utf-8')
        block = re.search(r'PRECACHE_URLS\s*=\s*\[(.*?)\]', source, re.S).group(1)
        urls = re.findall(r"'([^']+)'", block)
        assert urls == ['/static/images/logo.webp']
        assert block.split(',')[0].strip() == 'OFFLINE_URL'
        assert "OFFLINE_URL = '/static/offline.html'" in source
        # The only cache writes are the install-time precache
        assert source.count('cache.addAll') == 1
        assert 'cache.put' not in source

    def test_handles_navigations_and_the_precached_logo_only(self, client):
        source = client.get('/sw.js').data.decode('utf-8')
        # Navigations get the offline fallback when the network fails
        assert "request.mode !== 'navigate'" in source
        # The only other answered requests are the precached assets (the
        # offline page's logo), so its <img> loads while offline
        assert 'CACHED_ASSET_PATHS' in source
        assert 'url !== OFFLINE_URL' in source
        assert "request.method === 'GET'" in source
        assert 'self.location.origin' in source
        # Exactly two answered paths: precached asset, navigation fallback
        assert source.count('event.respondWith(') == 2
        assert 'skipWaiting' in source and 'clients.claim' in source


class TestOfflinePage:

    def test_reachable_without_login(self, client):
        resp = client.get('/static/offline.html')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert "OreX can't be reached" in html
        assert 'Retry' in html
        assert "addEventListener('online'" in html
        # Self-contained: inline CSS, no stylesheet links, logo only
        assert '<style>' in html and 'rel="stylesheet"' not in html
        resp.close()

    def test_maintenance_page_is_separate(self, client):
        resp = client.get('/static/maintenance.html')
        assert resp.status_code == 200
        assert 'down for maintenance' in resp.data.decode('utf-8')
        resp.close()


class TestHeadTags:

    def _assert_head(self, html):
        # use-credentials so cookie-gated proxies (ngrok's warning page) serve the JSON
        assert ('<link rel="manifest" href="/manifest.webmanifest" '
                'crossorigin="use-credentials">') in html
        assert '<meta name="theme-color"' in html
        # static URLs carry a ?v=<mtime> cache-busting suffix
        assert re.search(r'rel="apple-touch-icon" href="/static/images/pwa/apple-touch-icon\.png(\?v=\d+)?"', html)
        assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
        assert '<meta name="apple-mobile-web-app-title" content="OreX">' in html
        assert 'name="apple-mobile-web-app-status-bar-style"' in html
        assert "navigator.serviceWorker.register('/sw.js', { scope: '/' })" in html

    def test_logged_out_page(self, client):
        self._assert_head(client.get('/').data.decode('utf-8'))

    def test_logged_in_page(self, authenticated_client):
        self._assert_head(authenticated_client.get('/dashboard').data.decode('utf-8'))

    def test_login_page(self, client):
        self._assert_head(client.get('/login').data.decode('utf-8'))


class TestInstallBlock:

    def test_hidden_by_default_first_in_the_this_device_section(self, authenticated_client):
        html = authenticated_client.get('/settings').data.decode('utf-8')
        card = re.search(r'<div class="settings-card" id="install-card" hidden>.*?</div>', html, re.S)
        assert card, 'install card missing or not hidden by default'
        block = card.group(0)
        assert 'Install OreX' in block
        assert re.search(r'<button[^>]*id="install-btn"[^>]*\bhidden\b', block)
        assert re.search(r'<p[^>]*id="install-ios-hint"[^>]*\bhidden\b', block)
        assert 'tap Share then Add to Home Screen' in block
        # Order: Change Password (Account section), then the This device section with Install first
        assert (html.index('<h3>Change Password</h3>') < html.index('id="device"')
                < html.index('id="install-card"') < html.index('id="push-card"'))
        # Nothing sits between the section heading and the Install card
        between = html[html.index('id="device-heading"'):html.index('id="install-card"')]
        assert between.count('<div class="settings-card') == 1  # only the install card's own opening tag
