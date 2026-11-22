"""PWA check for OreX: service worker + offline fallback in a real browser.

Starts the app against a THROWAWAY database (helpers from screenshot.py), loads
the landing page, waits for the service worker to activate, goes offline and
asserts the branded offline page appears, then goes back online and asserts a
normal page loads. Also asserts the only cache entries are the offline page and
its logo. Not collected by pytest.

DEV ONLY. Needs the dev dependency group (Playwright). It uses the Chrome or
Edge that is already installed (no browser download); Playwright's WebKit is
tried only if neither is found, and may not support service workers.
Run (repo root):
    .venv\\Scripts\\python.exe scripts\\dev\\pwa_check.py
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import screenshot as shot  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit('Playwright is not installed. Run: uv sync')


def launch(p):
    for channel in ('chrome', 'msedge'):
        try:
            return p.chromium.launch(channel=channel), channel
        except Exception:
            continue
    return p.webkit.launch(), 'webkit'


def main():
    tmp_dir = tempfile.mkdtemp(prefix='orex_pwa_')
    server, base = shot.start_app(shot.prepare_database(tmp_dir, False), live_market=False)
    failures = []

    def check(ok, label):
        print(('PASS  ' if ok else 'FAIL  ') + label)
        if not ok:
            failures.append(label)

    try:
        with sync_playwright() as p:
            browser, name = launch(p)
            print('browser:', name)
            context = browser.new_context()
            page = context.new_page()
            page.goto(base + '/')
            ready = page.evaluate(
                "navigator.serviceWorker ? navigator.serviceWorker.ready.then(r => !!r.active) : false")
            check(ready is True, 'service worker activated')

            # Wait until the worker controls the page (clients.claim)
            page.wait_for_function('!!navigator.serviceWorker.controller', timeout=10000)
            cached = page.evaluate(
                "caches.keys().then(ks => Promise.all(ks.map(k => caches.open(k)"
                ".then(c => c.keys().then(rs => rs.map(r => new URL(r.url).pathname))))))")
            flat = sorted(u for group in cached for u in group)
            check(flat == ['/static/images/logo.webp', '/static/offline.html'],
                  f'cache holds only the offline page and logo: {flat}')

            context.set_offline(True)
            page.goto(base + '/about')
            check('Waiting for connection' in page.inner_text('body'), 'offline navigation shows the offline page')
            check(page.is_visible('#retry'), 'Retry button visible')

            context.set_offline(False)
            page.goto(base + '/about')
            check('Waiting for connection' not in page.inner_text('body'), 'back online loads the real page')
            browser.close()
    finally:
        server.shutdown()

    if failures:
        sys.exit(f'{len(failures)} check(s) failed')
    print('All PWA checks passed')


if __name__ == '__main__':
    main()
