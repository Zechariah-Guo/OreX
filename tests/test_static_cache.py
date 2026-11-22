"""Static asset caching: Cache-Control policy and ?v= cache-busting URLs."""

import io
import os
import re

from PIL import Image

from conftest import get_csrf_token

LONG = 'public, max-age=31536000, immutable'


def _static_urls(html):
    return re.findall(r'(?:src|href)="(/static/[^"]+)"', html)


class TestStaticCacheHeaders:
    def test_versioned_static_is_long_lived_immutable(self, client):
        html = client.get('/login').data.decode()
        css = [u for u in _static_urls(html) if '.css' in u]
        assert css, 'login page should link app CSS'
        for url in css:
            assert '?v=' in url
            resp = client.get(url)
            assert resp.status_code == 200
            assert resp.headers['Cache-Control'] == LONG
            resp.close()

    def test_versioned_revalidation_keeps_the_header(self, client):
        url = next(u for u in _static_urls(client.get('/login').data.decode()) if '.css' in u)
        first = client.get(url)
        again = client.get(url, headers={'If-None-Match': first.headers['ETag']})
        assert again.status_code == 304
        assert again.headers['Cache-Control'] == LONG
        first.close()
        again.close()

    def test_unversioned_static_gets_short_max_age(self, client):
        resp = client.get('/static/images/logo.webp')
        assert resp.headers['Cache-Control'] == 'public, max-age=3600'
        resp.close()

    def test_html_in_static_is_always_revalidated(self, client):
        resp = client.get('/static/offline.html')
        assert resp.headers['Cache-Control'] == 'no-cache'
        resp.close()

    def test_service_worker_stays_no_cache(self, client):
        resp = client.get('/sw.js')
        assert resp.headers['Cache-Control'] == 'no-cache'
        resp.close()

    def test_manifest_and_pages_are_not_given_static_headers(self, client):
        assert client.get('/manifest.webmanifest').headers.get('Cache-Control') != LONG
        assert client.get('/login').headers.get('Cache-Control') != LONG

    def test_service_worker_precache_paths_stay_plain(self, client):
        source = client.get('/sw.js').data.decode()
        assert '?v=' not in source


class TestVersionedUrls:
    def test_template_static_urls_carry_the_file_mtime(self, app, client):
        html = client.get('/login').data.decode()
        url = next(u for u in _static_urls(html) if u.split('?')[0].endswith('global.css'))
        path = os.path.join(app.static_folder, 'css', 'global.css')
        expected = str(os.stat(path).st_mtime_ns // 1_000_000)
        assert url.endswith(f'?v={expected}')

    def test_missing_file_gets_no_version(self, app):
        with app.test_request_context():
            from app.static_cache import _url_for
            assert _url_for('static', filename='nope/missing.css') == '/static/nope/missing.css'

    def test_changed_file_changes_url(self, app):
        target = os.path.join(app.static_folder, 'sf_cache_probe.txt')
        try:
            with open(target, 'w') as f:
                f.write('one')
            with app.test_request_context():
                from app.static_cache import _url_for
                first = _url_for('static', filename='sf_cache_probe.txt')
            os.utime(target, ns=(1_700_000_000_000_000_000, 1_700_000_001_000_000_000))
            with app.test_request_context():
                second = _url_for('static', filename='sf_cache_probe.txt')
            assert first != second
        finally:
            if os.path.exists(target):
                os.remove(target)


class TestAvatarUrlChangesOnUpload:
    def _upload(self, client, color):
        token = get_csrf_token(client.get('/profile'))
        buf = io.BytesIO()
        Image.new('RGB', (120, 120), color).save(buf, format='PNG')
        buf.seek(0)
        return client.post('/profile/avatar',
                           data={'avatar': (buf, 'a.png'), 'csrf_token': token},
                           content_type='multipart/form-data')

    def _avatar_src(self, client):
        html = client.get('/profile').data.decode()
        return re.search(r'<img src="([^"]*uploads/avatars/[^"]+)"', html).group(1)

    def test_avatar_url_changes_after_a_new_upload(self, app, authenticated_client):
        client = authenticated_client
        path = None
        try:
            resp = self._upload(client, (255, 0, 0))
            assert resp.status_code == 200
            m = re.search(r'src="[^"]*uploads/avatars/(\d+)\.webp\?v=\d+"', resp.data.decode())
            assert m, 'upload partial should return a versioned avatar URL'
            user_id = m.group(1)
            path = os.path.join(app.static_folder, 'uploads', 'avatars', f'{user_id}.webp')

            first = self._avatar_src(client)
            assert re.search(r'\?v=\d+$', first)
            # Make the second upload land at a clearly different modification time
            os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
            stale = self._avatar_src(client)
            assert stale != first

            self._upload(client, (0, 0, 255))
            second = self._avatar_src(client)
            assert second != stale
            assert second.split('?')[0] == first.split('?')[0]
        finally:
            if path and os.path.exists(path):
                os.remove(path)
