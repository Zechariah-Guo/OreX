"""Safari-engine check for OreX: Playwright WebKit + iPhone/iPad presets.

Starts the app against a THROWAWAY database (same helpers as screenshot.py),
registers a Standard and an Advanced user per device, visits the main pages,
saves full-page screenshots and runs automated checks (horizontal overflow,
fixed bars, console/network errors, tap-target and input font sizes, CSS
feature support and a few best-effort interactions). Prints a pass/fail table
and exits non-zero if any check fails.

DEV ONLY. Needs the dev dependency group and the browser download:
    uv sync
    .venv\\Scripts\\python.exe -m playwright install webkit
Run (repo root):
    .venv\\Scripts\\python.exe scripts\\dev\\safari_check.py
    .venv\\Scripts\\python.exe scripts\\dev\\safari_check.py --device "iPhone 13" --compare
Screenshots go to screenshots/safari/<device>/<mode>/<page>.png (git-ignored).
--compare also shoots every page in Chrome/Edge (Playwright's Chromium if it is
installed, otherwise the Chrome/Edge that screenshot.py finds) into
screenshots/safari-chrome/ and prints a pixel-difference percentage (needs Pillow).

LIMITS. Playwright's WebKit on Windows is a WebKit port, NOT Apple's Safari or
iOS. It cannot show: env(safe-area-inset-*) (always 0, so the iPhone bottom-bar
padding is unverified), the dynamic address bar (dvh/svh/vh behaviour while
scrolling), rubber-band overscroll, real touch momentum and scroll anchoring,
iOS input zoom on focus (the 16px font-size check only stands in for it), iOS
font rendering, or the long-press/context-menu behaviour of real iOS. Touch
interactions here are synthetic. All of that "needs a real iPhone".
"""

import argparse
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import screenshot as shot  # noqa: E402  (reuses the throwaway-DB / server / user helpers)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit('Playwright is not installed. Run: uv sync   then: .venv\\Scripts\\python.exe -m playwright install webkit')

ROOT = shot.ROOT
DEVICES = ['iPhone SE', 'iPhone SE (3rd gen)', 'iPhone 13', 'iPad Mini', 'custom-360x800']
# (slug, path, who): who is 'anon', 'any' (logged in) or 'advanced'
PAGES = [
    ('landing', '/', 'anon'), ('login', '/login', 'anon'),
    ('dashboard', '/dashboard', 'any'), ('market', '/market', 'any'), ('ore-detail', '/market/1', 'any'),
    ('portfolio-longs', '/portfolio', 'any'), ('portfolio-shorts', '/portfolio?tab=shorts', 'advanced'),
    ('finances', '/finances', 'advanced'), ('history', '/history', 'any'), ('leaderboard', '/leaderboard', 'any'),
    ('inbox', '/inbox', 'any'), ('profile', '/profile', 'any'), ('settings', '/settings', 'any'), ('help', '/help', 'any'),
]
COLUMNS = ['overflow', 'bars', 'console', 'requests', 'taps', 'fonts', 'dot', 'interact']

SUPPORT = {
    'color-mix()': "CSS.supports('color', 'color-mix(in srgb, red, blue)')",
    ':has()': "CSS.supports('selector(:has(*))')",
    'overflow-x: clip': "CSS.supports('overflow-x', 'clip')",
    '100dvh': "CSS.supports('height', '100dvh')",
    '100svh': "CSS.supports('height', '100svh')",
    'display: contents': "CSS.supports('display', 'contents')",
    'touch-action: pan-y': "CSS.supports('touch-action', 'pan-y')",
    'env(safe-area-inset-bottom)': "CSS.supports('padding-bottom', 'env(safe-area-inset-bottom)')",
    'position: sticky': "CSS.supports('position', 'sticky')",
    'aspect-ratio': "CSS.supports('aspect-ratio', '1 / 1')",
    'backdrop-filter': "CSS.supports('backdrop-filter', 'blur(4px)')",
    '-webkit-backdrop-filter': "CSS.supports('-webkit-backdrop-filter', 'blur(4px)')",
}

JS_OVERFLOW = "({sw: document.documentElement.scrollWidth, iw: window.innerWidth})"
JS_BARS = """(() => {
  const links = document.querySelector('.main-nav--auth .nav__links');
  if (!links) return {missing: true};
  const r = links.getBoundingClientRect(), cs = getComputedStyle(links);
  const top = getComputedStyle(links, '::after');
  const brand = document.querySelector('.main-nav--auth .nav__brand').getBoundingClientRect();
  return {bottom: r.bottom, ih: window.innerHeight, pos: cs.position, topPos: top.position, topTop: top.top,
          topH: top.height, brandTop: brand.top, scrollY: window.scrollY};
})()"""
JS_TABS = """(() => [...document.querySelectorAll('.nav__tab-link, #nav-avatar-btn')].map(e => {
  const r = e.getBoundingClientRect();
  return {n: e.getAttribute('aria-label') || e.id, w: Math.round(r.width), h: Math.round(r.height)};
}).filter(o => o.w > 0))()"""
JS_MENU = """(() => [...document.querySelectorAll('.nav__dropdown-icon, .nav__dropdown-item')].map(e => {
  const r = e.getBoundingClientRect();
  return {n: (e.getAttribute('aria-label') || e.textContent).trim().slice(0, 20), w: Math.round(r.width), h: Math.round(r.height)};
}).filter(o => o.w > 0))()"""
JS_FONTS = """(() => [...document.querySelectorAll('input, select, textarea')].filter(e => {
  const t = (e.type || '').toLowerCase(), r = e.getBoundingClientRect(), cs = getComputedStyle(e);
  return !['hidden','checkbox','radio','submit','button','image','file','range','color'].includes(t)
    && r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
}).map(e => ({n: e.tagName.toLowerCase() + (e.name ? '[' + e.name + ']' : ''), fs: parseFloat(getComputedStyle(e).fontSize)}))
  .filter(o => o.fs < 16))()"""
JS_DOT = """(() => {
  const a = document.querySelector('.nav__dropdown-icon--unread');
  if (!a) return null;
  const svg = a.querySelector('svg').getBoundingClientRect(), ar = a.getBoundingClientRect();
  const cs = getComputedStyle(a, '::after'), w = parseFloat(cs.width) || 8;
  const left = cs.left !== 'auto' ? ar.left + parseFloat(cs.left) : ar.right - parseFloat(cs.right) - w;
  const top = ar.top + parseFloat(cs.top);
  return {dx: Math.round(left + w / 2 - svg.right), dy: Math.round(top + w / 2 - svg.top)};
})()"""
JS_LONG_PRESS = """(() => {
  const el = document.querySelector('.inbox__row-link');
  if (!el) return 'no inbox row';
  // WebKit has no Touch() constructor: fake the touch events with plain Events carrying the touch lists
  const r = el.getBoundingClientRect();
  const t = {identifier: 1, target: el, clientX: r.left + 20, clientY: r.top + r.height / 2};
  const fire = (type, touches) => { const e = new Event(type, {bubbles: true, cancelable: true});
    Object.defineProperties(e, {touches: {value: touches}, targetTouches: {value: touches}, changedTouches: {value: [t]}});
    el.dispatchEvent(e); };
  window.__lpEnd = () => fire('touchend', []);
  fire('touchstart', [t]);
  return 'ok';
})()"""
JS_LONG_PRESS_END = "window.__lpEnd()"


class Row:
    """Results for one page: column -> (ok, detail)."""

    def __init__(self, label, shots):
        self.label, self.shots, self.results = label, shots, {}

    def add(self, column, ok, detail=''):
        old = self.results.get(column)
        if old and not old[0]:  # keep the first failure's detail
            return
        self.results[column] = (ok, detail)

    @property
    def failures(self):
        return [(c, d) for c, (ok, d) in self.results.items() if not ok]


def context_options(pw, device, viewport_override=None):
    if device == 'custom-360x800':
        opts = dict(pw.devices['iPhone 13'])
        opts.update(viewport={'width': 360, 'height': 800}, screen={'width': 360, 'height': 800})
    else:
        opts = dict(pw.devices[device])
    opts.pop('default_browser_type', None)
    return opts


def slug(text):
    return shot.slugify(text.lower())


def seed_user(db_path, username, advanced):
    ns = argparse.Namespace(advanced=advanced, balance=None, cosmetic=None, with_tutorial=False)
    shot.apply_user_state(db_path, username, ns)
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        uid = con.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()[0]
        for i in range(3):  # unread notifications so the inbox rows and the nav dot exist
            con.execute("INSERT INTO notifications (user_id, category, message, action_url, target_url, is_read, created_at) "
                        "VALUES (?, 'trade', ?, '/inbox', '/history', 0, datetime('now', 'localtime'))",
                        (uid, f'Safari check notification {i + 1}'))
        con.commit()
    finally:
        con.close()


def register(page, base, username):
    page.goto(base + '/register')
    page.evaluate(
        "([u, p]) => { const f = document.querySelector('form.auth-form'); const e = f.elements;"
        " e['username'].value = u; e['password'].value = p; e['confirm_password'].value = p; f.submit(); }",
        [username, shot.PASSWORD])
    page.wait_for_url(lambda url: '/register' not in url, timeout=20000)


def tap(page, selector):
    loc = page.locator(selector).first
    loc.tap(timeout=4000)


def run_interactions(page, row, slug_, width, logged_in):
    """Best-effort interaction checks; any failure is recorded, never raised."""
    def attempt(name, fn):
        try:
            msg = fn()
            row.add('interact', msg is None, f'{name}: {msg}' if msg else '')
            if msg:
                print(f'    interaction FAILED [{row.label}] {name}: {msg}')
        except Exception as exc:  # noqa: BLE001 - best effort
            row.add('interact', False, f'{name}: {type(exc).__name__}: {str(exc).splitlines()[0]}')
            print(f'    interaction ERROR [{row.label}] {name}: {str(exc).splitlines()[0]}')

    if logged_in and slug_ == 'dashboard':
        def avatar():
            tap(page, '#nav-avatar-btn')
            page.wait_for_timeout(500)
            if page.get_attribute('#nav-avatar-btn', 'aria-expanded') != 'true':
                return 'aria-expanded is not "true" after tapping the avatar'
            small = [o for o in page.evaluate(JS_MENU) if min(o['w'], o['h']) < 44]
            row.add('taps', not small, 'menu: ' + ', '.join(f"{o['n']} {o['w']}x{o['h']}" for o in small))
            dot = page.evaluate(JS_DOT)
            if dot:
                off = abs(dot['dx']) > 10 or abs(dot['dy']) > 10
                row.add('dot', not off, f"unread dot centre is {dot['dx']}px right / {dot['dy']}px down of the icon's top-right corner")
        attempt('avatar menu', avatar)
    if logged_in and slug_ == 'market' and width < 641:
        def scroll_bars():
            # mobile WebKit has no mouse wheel; scrollBy fires the same scroll events
            page.evaluate('window.scrollBy(0, 700)')
            page.wait_for_timeout(700)
            hidden = page.evaluate("document.documentElement.classList.contains('nav-hidden')")
            page.evaluate('window.scrollBy(0, -300)')
            page.wait_for_timeout(700)
            back = not page.evaluate("document.documentElement.classList.contains('nav-hidden')")
            if not hidden:
                return 'bars did not hide after scrolling down'
            if not back:
                return 'bars did not return after scrolling up'
        attempt('market scroll hides/shows bars', scroll_bars)
    if logged_in and slug_ == 'inbox':
        def long_press():
            res = page.evaluate(JS_LONG_PRESS)
            if res != 'ok':
                return f'could not start synthetic touch ({res})'
            page.wait_for_timeout(700)
            mode = page.get_attribute('#inbox', 'data-mode')
            page.evaluate(JS_LONG_PRESS_END)
            if mode != 'select':
                return f'data-mode is "{mode}" after a 700 ms synthetic long-press (select mode did not start)'
        attempt('inbox long-press -> select mode', long_press)
    if logged_in and slug_ == 'profile' and width < 880:
        def carousel():
            before = page.inner_text('[data-ach-title]')
            tap(page, '[data-ach-next]')
            page.wait_for_timeout(500)
            after = page.inner_text('[data-ach-title]')
            if before == after:
                return f'title stayed "{before}" after tapping next'
        attempt('profile carousel next arrow', carousel)


def check_page(page, row, path, slug_, logged_in, width, diag):
    ov = page.evaluate(JS_OVERFLOW)
    row.add('overflow', ov['sw'] <= ov['iw'], f"scrollWidth {ov['sw']} > innerWidth {ov['iw']}")
    if logged_in and width < 641:
        b = page.evaluate(JS_BARS)
        bad = []
        if b.get('missing'):
            bad.append('bottom bar element missing')
        else:
            if abs(b['bottom'] - b['ih']) > 1:
                bad.append(f"bottom bar ends at {b['bottom']} not {b['ih']}")
            if b['pos'] != 'fixed' or b['topPos'] != 'fixed' or b['topTop'] not in ('0px', '0'):
                bad.append(f"positions bottom={b['pos']} top={b['topPos']}/{b['topTop']}")
        row.add('bars', not bad, '; '.join(bad))
        small = [o for o in page.evaluate(JS_TABS) if min(o['w'], o['h']) < 44]
        row.add('taps', not small, 'bar/avatar: ' + ', '.join(f"{o['n']} {o['w']}x{o['h']}" for o in small))
    fonts = page.evaluate(JS_FONTS)
    row.add('fonts', not fonts, ', '.join(f"{o['n']} {o['fs']}px" for o in fonts))
    if slug_ == 'market' and logged_in:
        h = page.evaluate("(() => { const e = document.querySelector('.ore-card__handle'); if (!e) return null;"
                          " const r = e.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height), d: getComputedStyle(e).display}; })()")
        row.add('taps', bool(h) and h['w'] >= 44 and h['h'] >= 44 or bool(h) and h['d'] == 'none',
                f'market drag handle {h}' if h else 'market drag handle missing')
    if slug_ == 'profile' and width < 880:
        vis = page.evaluate("(() => { const e = document.querySelector('.ach-carousel'); return !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0; })()")
        row.add('interact', vis, 'achievements carousel is not visible below 880px')
    row.add('console', not diag['console'], ' | '.join(diag['console'][:3]))
    row.add('requests', not diag['requests'], ' | '.join(diag['requests'][:3]))
    run_interactions(page, row, slug_, width, logged_in)


def pixel_diff(a_path, b_path):
    from PIL import Image, ImageChops
    a, b = Image.open(a_path).convert('RGB'), Image.open(b_path).convert('RGB')
    if a.width != b.width:
        b = b.resize((a.width, round(b.height * a.width / b.width)))
    h = min(a.height, b.height)
    diff = ImageChops.difference(a.crop((0, 0, a.width, h)), b.crop((0, 0, a.width, h))).convert('L')
    changed = diff.point(lambda v: 255 if v > 24 else 0).histogram()[255]
    pct = 100.0 * changed / (a.width * h)
    return pct, (a.height, b.height)


def run_device(pw, browser, engine, device, base, db_path, args, rows, support, out_root):
    """One device: logged-out pages, then Standard and Advanced users."""
    opts = context_options(pw, device)
    width = opts['viewport']['width']
    for mode in ('anon', 'standard', 'advanced'):
        context = browser.new_context(**opts)
        page = context.new_page()
        diag = {'console': [], 'requests': []}
        page.on('console', lambda m: diag['console'].append(m.text[:160]) if m.type == 'error' else None)
        page.on('pageerror', lambda e: diag['console'].append(f'pageerror: {str(e)[:160]}'))
        page.on('requestfailed', lambda r: diag['requests'].append(f'{r.failure} {r.url[:80]}')
                if not any(w in (r.failure or '').lower() for w in ('abort', 'cancel')) else None)
        page.on('response', lambda r: diag['requests'].append(f'{r.status} {r.url[:80]}') if r.status >= 400 else None)
        try:
            logged_in = mode != 'anon'
            if logged_in:
                username = f'sf{random.randint(10000, 99999)}'
                register(page, base, username)
                page.goto('about:blank')
                seed_user(db_path, username, mode == 'advanced')
            for slug_, path, who in PAGES:
                if (who == 'anon') == logged_in or (who == 'advanced' and mode != 'advanced'):
                    continue
                diag['console'].clear(), diag['requests'].clear()
                out = os.path.join(out_root, slug(device), mode, f'{slug_}.png')
                os.makedirs(os.path.dirname(out), exist_ok=True)
                row = Row(f'{device} / {mode} / {slug_}', out)
                try:
                    page.goto(base + path, wait_until='load', timeout=30000)
                    page.wait_for_timeout(800)
                    if engine == 'webkit':
                        if not support:
                            support.update(page.evaluate('(c) => Object.fromEntries(Object.entries(c).map(([k, v]) => [k, !!eval(v)]))', SUPPORT))
                            support['__device'] = device
                        check_page(page, row, path, slug_, logged_in, width, diag)
                    page.screenshot(path=out, full_page=True)
                except Exception as exc:  # noqa: BLE001
                    row.add('console', False, f'{type(exc).__name__}: {str(exc).splitlines()[0]}')
                    print(f'  ERROR {row.label}: {str(exc).splitlines()[0]}')
                rows.append(row)
        finally:
            context.close()


def print_table(rows):
    w = max(len(r.label) for r in rows)
    print('\n' + 'page'.ljust(w) + '  ' + '  '.join(c[:8].ljust(8) for c in COLUMNS))
    for r in rows:
        cells = []
        for c in COLUMNS:
            res = r.results.get(c)
            cells.append(('-' if res is None else 'ok' if res[0] else 'FAIL').ljust(8))
        print(r.label.ljust(w) + '  ' + '  '.join(cells))
    print('\nFailures:')
    n = 0
    for r in rows:
        for c, d in r.failures:
            n += 1
            print(f'  [{c}] {r.label}: {d}')
            print(f'        screenshot: {os.path.relpath(r.shots, ROOT)}')
    print('  none' if not n else f'\n{n} failing check(s)')
    return n


def main():
    parser = argparse.ArgumentParser(description='Safari-engine check (Playwright WebKit, iPhone/iPad presets). Dev only; see the module docstring for limits.')
    parser.add_argument('--device', action='append', choices=DEVICES, help='limit to these devices (repeatable; default: all four)')
    parser.add_argument('--compare', action='store_true', help='also shoot pages in Chrome/Edge and print a pixel-diff %% per page')
    parser.add_argument('--out', default=os.path.join(ROOT, 'screenshots'), help='screenshot root (default: ./screenshots)')
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    devices = args.device or DEVICES

    tmp = tempfile.mkdtemp(prefix='orex_safari_')
    server = None
    rows, support, chrome_rows = [], {}, []
    try:
        db_path = shot.prepare_database(tmp, False)
        server, base = shot.start_app(db_path, False)
        with sync_playwright() as pw:
            wk = pw.webkit.launch()
            version = wk.version
            print(f'WebKit {version} (Playwright {pw.webkit.name}), app at {base}')
            for d in devices:
                print(f'== {d}')
                run_device(pw, wk, 'webkit', d, base, db_path, args, rows, support, os.path.join(args.out, 'safari'))
            wk.close()
            if args.compare:
                path = pw.chromium.executable_path
                path = path if path and os.path.isfile(path) else shot.find_browser()
                if not path:
                    print('--compare: no Chromium/Chrome/Edge found, skipping')
                else:
                    cr = pw.chromium.launch(executable_path=path)
                    for d in devices:
                        run_device(pw, cr, 'chromium', d, base, db_path, args, chrome_rows, {}, os.path.join(args.out, 'safari-chrome'))
                    cr.close()
    finally:
        if server:
            server.shutdown()
        shot.remove_dir(tmp)

    failures = print_table(rows)
    print(f'\nCSS support in WebKit {version} (on {support.pop("__device", "?")}):')
    for k, v in support.items():
        print(f'  {"yes" if v else "NO ":3}  {k}')
    if args.compare and chrome_rows:
        try:
            print('\nWebKit vs Chrome pixel difference (% of pixels differing):')
            for w_row, c_row in zip(rows, chrome_rows):
                pct, heights = pixel_diff(w_row.shots, c_row.shots)
                print(f'  {pct:5.1f}%  {w_row.label}  (heights {heights[0]} vs {heights[1]})')
        except ImportError:
            print('Pillow is not installed: images saved, diff skipped')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
