"""Screenshot OreX pages in a real (headless) browser.

Starts the actual app against a THROWAWAY database (your dev database is never
touched), registers a fresh user in the browser, then visits each page and saves
a PNG. Also reports console errors and failed requests per page, which makes it
handy for UI work: change CSS/templates, re-run, look at the images.

Needs Google Chrome or Microsoft Edge installed (auto-detected; override with
--browser or the CHROME_PATH environment variable). No extra Python packages.
The page loads htmx/Alpine from CDNs, so you need an internet connection.

Usage (run from the repo root):
    python scripts/screenshot.py /dashboard /market
    python scripts/screenshot.py /market/1 --theme both --viewport desktop --viewport mobile
    python scripts/screenshot.py /finances --advanced --balance 250000
    python scripts/screenshot.py /profile --selector ".profile__showcase"
    python scripts/screenshot.py /settings --full-page --dev-data
    python scripts/screenshot.py /login /register --no-login
    python scripts/screenshot.py /dashboard --with-tutorial --wait 2500
    python scripts/screenshot.py /market --click "#some-button" --wait-for ".result"
    python scripts/screenshot.py /help --click "[data-tutorial-replay=beginner]" --settle 4000

Files are written to ./screenshots/ (git-ignored) as <page>_<viewport>_<theme>.png.

Notes:
  * By default the user's tutorials are pre-marked completed so the tutorial
    overlay does not cover every shot. Use --with-tutorial to see it.
  * The market engine is off by default (prices stay at their seed values).
    Use --live-market to let prices tick.
  * --dev-data starts from a COPY of src/data/orex.db so pages show realistic
    ores/prices. The original file is only read, never written.
"""

import argparse
import base64
import json
import logging
import os
import random
import re
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

VIEWPORT_PRESETS = {
    'desktop': (1280, 720),
    'laptop': (1440, 900),
    'tablet': (820, 1180),
    'mobile': (390, 844),
    'small-mobile': (360, 844),
    'short-mobile': (375, 667),
    'tablet-portrait': (768, 844),
}
PASSWORD = 'Password123!'
MAX_FULL_PAGE_HEIGHT = 16000  # browsers fail to capture taller images


# ----------------------------------------------------------------------------
# Minimal WebSocket client (RFC 6455), just enough for Chrome's DevTools port.
# Written against the stdlib so the tool needs no extra dependencies.
# ----------------------------------------------------------------------------

class WebSocketClient:
    def __init__(self, url, timeout=30):
        match = re.match(r'ws://([^/:]+):(\d+)(/.*)$', url)
        if not match:
            raise ValueError(f'Unsupported WebSocket URL: {url}')
        host, port, path = match.group(1), int(match.group(2)), match.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f'GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n'
            'Upgrade: websocket\r\nConnection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'
        )
        self.sock.sendall(request.encode())
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('Browser closed the connection during handshake')
            data += chunk
        head, _, rest = data.partition(b'\r\n\r\n')
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise ConnectionError(f'WebSocket handshake failed: {head[:80]!r}')
        self._buffer = rest

    def _read_exact(self, count):
        while len(self._buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('Browser closed the connection')
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _send_frame(self, opcode, payload):
        header = bytes([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header += bytes([0x80 | length])
        elif length < 65536:
            header += bytes([0x80 | 126]) + struct.pack('>H', length)
        else:
            header += bytes([0x80 | 127]) + struct.pack('>Q', length)
        mask = os.urandom(4)  # client frames must be masked
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send_text(self, text):
        self._send_frame(0x1, text.encode('utf-8'))

    def recv_text(self):
        message = b''
        while True:
            first, second = self._read_exact(2)
            fin, opcode = first & 0x80, first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack('>H', self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack('>Q', self._read_exact(8))[0]
            payload = self._read_exact(length)  # server frames are not masked
            if opcode == 0x8:
                raise ConnectionError('Browser closed the WebSocket')
            if opcode == 0x9:
                self._send_frame(0xA, payload)  # answer ping with pong
                continue
            if opcode in (0x0, 0x1):
                message += payload
                if fin:
                    return message.decode('utf-8')

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class CDPError(RuntimeError):
    pass


class CDP:
    """Tiny Chrome DevTools Protocol client: send commands, track a few events."""

    def __init__(self, ws):
        self.ws = ws
        self._next_id = 0
        self.events = []
        self.console_errors = []
        self.failed_requests = []
        self.last_document_status = None

    def call(self, method, params=None, timeout=30):
        self._next_id += 1
        message_id = self._next_id
        self.ws.send_text(json.dumps({'id': message_id, 'method': method, 'params': params or {}}))
        deadline = time.time() + timeout
        while True:
            message = self._receive(deadline)
            if message.get('id') == message_id:
                if 'error' in message:
                    raise CDPError(f"{method}: {message['error'].get('message')}")
                return message.get('result', {})

    def _receive(self, deadline):
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError('Timed out waiting for the browser')
        self.ws.sock.settimeout(remaining)
        try:
            message = json.loads(self.ws.recv_text())
        except socket.timeout:
            raise TimeoutError('Timed out waiting for the browser')
        if 'method' in message:
            self._on_event(message['method'], message.get('params', {}))
        return message

    def _on_event(self, name, params):
        if name == 'Page.loadEventFired':
            self.events.append(name)
        elif name == 'Runtime.exceptionThrown':
            details = params.get('exceptionDetails', {})
            text = (details.get('exception') or {}).get('description') or details.get('text', 'exception')
            self._add_console_error(text.splitlines()[0])
        elif name == 'Runtime.consoleAPICalled' and params.get('type') == 'error':
            text = ' '.join(str(a.get('value', a.get('description', ''))) for a in params.get('args', []))
            self._add_console_error(text)
        elif name == 'Log.entryAdded' and params.get('entry', {}).get('level') == 'error':
            self._add_console_error(params['entry'].get('text', ''))
        elif name == 'Network.responseReceived':
            response = params.get('response', {})
            if params.get('type') == 'Document':
                self.last_document_status = response.get('status')
            if response.get('status', 0) >= 400:
                self.failed_requests.append(f"{response['status']} {response.get('url', '')}")
        elif name == 'Network.loadingFailed':
            if params.get('errorText') != 'net::ERR_ABORTED':
                self.failed_requests.append(f"{params.get('errorText')} (request {params.get('requestId')})")

    def _add_console_error(self, text):
        text = text.strip()
        if text and text not in self.console_errors:
            self.console_errors.append(text)

    def wait_event(self, name, timeout):
        deadline = time.time() + timeout
        while name not in self.events:
            self._receive(deadline)
        self.events.remove(name)

    def navigate(self, url, timeout=30):
        self.events = [e for e in self.events if e != 'Page.loadEventFired']
        result = self.call('Page.navigate', {'url': url})
        if result.get('errorText'):
            raise CDPError(f"Could not open {url}: {result['errorText']}")
        self.wait_event('Page.loadEventFired', timeout)

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
        if 'exceptionDetails' in result:
            details = result['exceptionDetails']
            text = (details.get('exception') or {}).get('description') or details.get('text')
            raise CDPError(f'JavaScript error: {text}')
        return result.get('result', {}).get('value')

    def reset_diagnostics(self):
        self.console_errors = []
        self.failed_requests = []


# ----------------------------------------------------------------------------
# Browser + app lifecycle
# ----------------------------------------------------------------------------

def find_browser(explicit=None):
    candidates = [explicit, os.environ.get('CHROME_PATH')]
    if os.name == 'nt':
        for base in filter(None, [os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)'),
                                  os.environ.get('LOCALAPPDATA')]):
            candidates.append(os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'))
            candidates.append(os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'))
    elif sys.platform == 'darwin':
        candidates += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                       '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge']
    for name in ('google-chrome', 'chromium', 'chromium-browser', 'chrome', 'msedge'):
        candidates.append(shutil.which(name))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def launch_browser(path, profile_dir, debug_port):
    return subprocess.Popen(
        [path, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
         '--disable-extensions', '--hide-scrollbars', '--mute-audio',
         f'--remote-debugging-port={debug_port}', f'--user-data-dir={profile_dir}', 'about:blank'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def stop_browser(proc):
    if proc is None or proc.poll() is not None:
        return
    if os.name == 'nt':
        # /T also kills the helper processes, which otherwise keep the profile folder locked
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


def remove_dir(path):
    for _ in range(10):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        time.sleep(0.5)


def connect_to_browser(debug_port):
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json', timeout=2) as resp:
                targets = json.load(resp)
            page = next((t for t in targets if t.get('type') == 'page'), None)
            if page:
                return WebSocketClient(page['webSocketDebuggerUrl'])
        except (OSError, ValueError, ConnectionError):
            pass
        time.sleep(0.25)
    raise RuntimeError('Could not connect to the browser (did it start?)')


def prepare_database(tmp_dir, use_dev_data):
    """Return the path of the throwaway DB. With --dev-data it starts as a copy of the dev DB."""
    from app.config import Config
    db_path = os.path.join(tmp_dir, 'orex.db')
    if use_dev_data:
        source = Config.DATABASE_PATH
        if not os.path.isfile(source):
            raise RuntimeError(f'--dev-data: {source} does not exist')
        for suffix in ('', '-wal', '-shm'):
            if os.path.isfile(source + suffix):
                shutil.copy2(source + suffix, db_path + suffix)
        try:
            con = sqlite3.connect(db_path)
            con.execute('SELECT COUNT(*) FROM ores').fetchone()
            con.close()
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(f'--dev-data: the dev database is not readable ({exc}). '
                               'Is orex.db a Git LFS pointer file?')
    return db_path


def start_app(db_path, live_market):
    """Create the Flask app on a free port, backed by db_path. Returns (server, base_url)."""
    from app.config import Config
    # create_app() initialises the database straight away, so repoint it BEFORE creating the app
    Config.DATABASE_PATH = db_path
    if not live_market:
        import app.market.engine as engine
        engine.start_engine = lambda app: None
    # Local script served over plain http: allow the dev secret and non-secure cookies
    os.environ.setdefault('OREX_ALLOW_DEFAULT_SECRET', '1')
    os.environ.setdefault('SESSION_COOKIE_SECURE', '0')
    from app import create_app
    from werkzeug.serving import make_server
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    flask_app = create_app()
    server = make_server('127.0.0.1', 0, flask_app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_port}'


# ----------------------------------------------------------------------------
# Scenario setup
# ----------------------------------------------------------------------------

def register_user(cdp, base_url, username):
    cdp.navigate(f'{base_url}/register')
    cdp.evaluate(
        "(() => { const f = document.querySelector('form.auth-form'); const e = f.elements;"
        f" e['username'].value = {json.dumps(username)};"
        f" e['password'].value = {json.dumps(PASSWORD)};"
        f" e['confirm_password'].value = {json.dumps(PASSWORD)};"
        " f.submit(); })()"
    )
    cdp.wait_event('Page.loadEventFired', 20)
    path = cdp.evaluate('location.pathname')
    if path == '/register':
        message = cdp.evaluate("(document.querySelector('.flash, .form-error, [role=alert]') || {}).textContent")
        raise RuntimeError(f'Registration failed: {(message or "unknown error").strip()}')


def tutorial_track_ids():
    try:
        with open(os.path.join(ROOT, 'src', 'static', 'data', 'tutorials.json'), encoding='utf-8') as f:
            return [t['id'] for t in json.load(f)['tracks']]
    except (OSError, ValueError, KeyError):
        return ['beginner', 'advanced']


def apply_user_state(db_path, username, args):
    """Adjust the new user directly in the throwaway DB (advanced mode, balance, themes...)."""
    con = sqlite3.connect(db_path)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        row = con.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        user_id = row[0]
        if args.advanced:
            con.execute('UPDATE users SET advanced_eligible=1, advanced_purchased=1, advanced_active=1 WHERE id=?',
                        (user_id,))
        if args.balance is not None:
            con.execute('UPDATE users SET balance=? WHERE id=?', (args.balance, user_id))
        elif args.advanced:
            con.execute('UPDATE users SET balance=MAX(balance, 150000) WHERE id=?', (user_id,))
        if args.cosmetic:
            column = 'money_theme_unlocked' if args.cosmetic == 'money' else 'gold_theme_unlocked'
            con.execute(f'UPDATE users SET {column}=1 WHERE id=?', (user_id,))
        if args.with_tutorial:
            # Registration already landed on a page that auto-started the tutorial; start from scratch
            con.execute('DELETE FROM tutorial_progress WHERE user_id=?', (user_id,))
        else:
            for track_id in tutorial_track_ids():
                con.execute(
                    "INSERT INTO tutorial_progress (user_id, track_id, status, current_step_index) "
                    "VALUES (?, ?, 'completed', 0) "
                    "ON CONFLICT(user_id, track_id) DO UPDATE SET status='completed', current_step_index=0",
                    (user_id, track_id))
        con.commit()
    finally:
        con.close()


def set_theme_script(cdp, state, theme, cosmetic):
    """Make every new document start with the chosen theme in localStorage."""
    if state.get('script_id'):
        cdp.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': state['script_id']})
    cosmetic_js = (f"localStorage.setItem('orex-cosmetic-theme', {json.dumps(cosmetic)});" if cosmetic
                   else "localStorage.removeItem('orex-cosmetic-theme');")
    source = f"try {{ localStorage.setItem('orex-theme', {json.dumps(theme)}); {cosmetic_js} }} catch (e) {{}}"
    state['script_id'] = cdp.call('Page.addScriptToEvaluateOnNewDocument', {'source': source})['identifier']


# ----------------------------------------------------------------------------
# Taking the shots
# ----------------------------------------------------------------------------

def slugify(page):
    slug = re.sub(r'[^A-Za-z0-9]+', '-', page).strip('-')
    return slug or 'home'


def parse_viewport(text):
    if text in VIEWPORT_PRESETS:
        width, height = VIEWPORT_PRESETS[text]
        return text, width, height
    match = re.fullmatch(r'(\d{2,5})x(\d{2,5})', text)
    if not match:
        raise argparse.ArgumentTypeError(
            f"bad viewport '{text}' (use WIDTHxHEIGHT or one of: {', '.join(VIEWPORT_PRESETS)})")
    return text, int(match.group(1)), int(match.group(2))


def wait_for_selector(cdp, selector, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cdp.evaluate(f'!!document.querySelector({json.dumps(selector)})'):
            return True
        time.sleep(0.2)
    return False


def capture(cdp, page, base_url, args, out_path):
    cdp.reset_diagnostics()
    cdp.last_document_status = None
    cdp.navigate(base_url + page)
    status = cdp.last_document_status
    final_path = cdp.evaluate('location.pathname + location.search')
    warnings = []
    if final_path.rstrip('/') != page.rstrip('/'):
        warnings.append(f'redirected to {final_path}')
    if status and status >= 400:
        warnings.append(f'HTTP {status}')

    if args.wait_for and not wait_for_selector(cdp, args.wait_for):
        warnings.append(f'--wait-for {args.wait_for!r} never appeared')
    time.sleep(args.wait / 1000)

    for selector in args.click or []:
        clicked = cdp.evaluate(
            f'(() => {{ const e = document.querySelector({json.dumps(selector)});'
            ' if (!e) return false; e.click(); return true; })()')
        if not clicked:
            warnings.append(f'--click {selector!r}: no such element')
        time.sleep(args.settle / 1000)
    for script in args.eval or []:
        cdp.evaluate(script)
        time.sleep(args.settle / 1000)

    params = {'format': 'png'}
    if args.selector:
        rect = cdp.evaluate(
            f'(() => {{ const e = document.querySelector({json.dumps(args.selector)}); if (!e) return null;'
            ' e.scrollIntoView({block: "center"}); const r = e.getBoundingClientRect();'
            ' return {x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height}; })()')
        if rect and rect['width'] > 0 and rect['height'] > 0:
            pad = 8
            params['clip'] = {'x': max(rect['x'] - pad, 0), 'y': max(rect['y'] - pad, 0),
                              'width': rect['width'] + 2 * pad, 'height': rect['height'] + 2 * pad, 'scale': 1}
            params['captureBeyondViewport'] = True
        else:
            warnings.append(f'--selector {args.selector!r} not found, saved the normal viewport instead')
    elif args.full_page:
        size = cdp.call('Page.getLayoutMetrics')
        content = size.get('cssContentSize') or size['contentSize']
        params['clip'] = {'x': 0, 'y': 0, 'width': content['width'],
                          'height': min(content['height'], MAX_FULL_PAGE_HEIGHT), 'scale': 1}
        params['captureBeyondViewport'] = True

    data = cdp.call('Page.captureScreenshot', params, timeout=60)['data']
    with open(out_path, 'wb') as f:
        f.write(base64.b64decode(data))
    return warnings


# Guarded: a tour can navigate on its own (e.g. after skipping steps whose
# target has no box), and polling during that page load runs before Alpine exists.
TUTORIAL_STATE = "(window.Alpine && Alpine.$data(document.querySelector('.tutorial-root')))"


def walk_tutorial(cdp, base_url, track_id, out_dir, viewport_name):
    """Walk a tutorial track, saving one screenshot per step. Returns a status string."""
    # Be on a real same-origin page before issuing XHRs (we may arrive here from about:blank)
    cdp.navigate(base_url + '/dashboard')
    tid = json.dumps(track_id)
    # Runtime.evaluate won't await a promise with returnByValue, so use a
    # synchronous XHR to learn how many steps the track has.
    length = cdp.evaluate(
        "(function () { try { var x = new XMLHttpRequest();"
        " x.open('GET', '/tutorial/track/' + " + tid + ", false); x.send();"
        " return JSON.parse(x.responseText).steps.length; } catch (e) { return 0; } })()")
    if not length:
        return {'saved': 0, 'expected': 0, 'error': f'track {track_id!r} has no steps (is it the right id?)'}

    # The track must be in progress and on its first step's page. /replay does both.
    first_route = cdp.evaluate(
        "(function () { var x = new XMLHttpRequest();"
        " x.open('POST', '/tutorial/replay', false);"
        " x.setRequestHeader('Content-Type', 'application/json');"
        " var m = document.querySelector('meta[name=\"csrf-token\"]');"
        " x.setRequestHeader('X-CSRFToken', m ? m.content : '');"
        " x.send(JSON.stringify({track_id: " + tid + "}));"
        " return JSON.parse(x.responseText).redirect; })()")
    if not first_route:
        return {'saved': 0, 'expected': length,
                'error': f'could not start track {track_id!r} (replay refused — advanced not unlocked?)'}

    # Set the hand-off flag the overlay looks for, so it opens directly at step 0
    # on the destination page (the same mechanism the Help "Replay" button uses),
    # rather than only offering the resume toast.
    cdp.evaluate(
        "sessionStorage.setItem('orex-tutorial-nav', JSON.stringify({track_id: "
        + tid + ", step_index: 0, ts: Date.now()}))")
    cdp.navigate(base_url + first_route)
    saved = 0
    for i in range(length):
        # Wait for the card to settle on this step
        ready = False
        for _ in range(40):
            ready = cdp.evaluate(
                "(function () { var d = " + TUTORIAL_STATE + ";"
                " return !!(d && d.showOverlay && d.showCard && !d.busy && d.currentStep); })()")
            if ready:
                break
            time.sleep(0.15)
        if not ready:
            return {'saved': saved, 'expected': length,
                    'error': f'step {i} never appeared (saved {saved} of {length})'}
        info = cdp.evaluate(
            "(function () { var d = " + TUTORIAL_STATE + ";"
            " return {i: d.currentIndex, title: d.currentStep.title,"
            " route: location.pathname, side: d.cardSide}; })()")
        time.sleep(0.4)  # let the highlight/card finish animating
        slug = re.sub(r'[^a-z0-9]+', '-', (info['title'] or '').lower()).strip('-')
        out_path = os.path.join(out_dir, f'{i:02d}_{slugify(info["route"])}_{slug}_{viewport_name}.png')
        data = cdp.call('Page.captureScreenshot', {'format': 'png'}, timeout=60)['data']
        with open(out_path, 'wb') as f:
            f.write(base64.b64decode(data))
        print(f'saved   {os.path.relpath(out_path, ROOT)}  ({info["title"]})')
        saved += 1
        # Advance by tapping a dim panel, exactly as a user would (Option A). The
        # last step's tap finishes the tour. Clicking the first panel is enough:
        # on a no-highlight step it covers the screen, on a normal step it is the
        # top band, and either way the handler calls next().
        cdp.evaluate(
            "(function(){var p=document.querySelector('.tutorial-panel');"
            " if(p){p.click();} else {var d=" + TUTORIAL_STATE + "; if(d){d.next();}}})()")
        time.sleep(1.8)
    return {'saved': saved, 'expected': length, 'error': None}


def parse_args():
    parser = argparse.ArgumentParser(
        description='Screenshot OreX pages in headless Chrome/Edge using a throwaway database.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Viewport presets: ' + ', '.join(f'{k}={w}x{h}' for k, (w, h) in VIEWPORT_PRESETS.items()))
    parser.add_argument('pages', nargs='*', default=['/dashboard'], help='paths to capture (default: /dashboard)')
    parser.add_argument('--out', default=os.path.join(ROOT, 'screenshots'), help='output folder (default: ./screenshots)')
    parser.add_argument('--theme', choices=['light', 'dark', 'both'], default='light')
    parser.add_argument('--viewport', action='append', type=parse_viewport, metavar='SIZE',
                        help='WIDTHxHEIGHT or a preset; repeatable (default: desktop)')
    parser.add_argument('--full-page', action='store_true', help='capture the whole scrollable page')
    parser.add_argument('--selector', metavar='CSS', help='capture only the first element matching this selector')
    parser.add_argument('--wait', type=int, default=800, metavar='MS', help='settle time after load (default 800)')
    parser.add_argument('--wait-for', metavar='CSS', help='wait until this selector exists before capturing')
    parser.add_argument('--settle', type=int, default=400, metavar='MS',
                        help='pause after each --click/--eval, e.g. for animations or a page change (default 400)')
    parser.add_argument('--click', action='append', metavar='CSS', help='click this element first; repeatable')
    parser.add_argument('--eval', action='append', metavar='JS', help='run this JavaScript first; repeatable')
    parser.add_argument('--advanced', action='store_true', help='user has Advanced Mode purchased and active')
    parser.add_argument('--balance', type=float, metavar='N', help='set the user balance')
    parser.add_argument('--cosmetic', choices=['money', 'gold'], help='unlock and apply a cosmetic theme')
    parser.add_argument('--with-tutorial', action='store_true', help='do not pre-complete the tutorials')
    parser.add_argument('--tutorial-walk', metavar='TRACK',
                        help='walk a tutorial track start-to-finish, saving one screenshot per step '
                             '(e.g. --tutorial-walk beginner). Implies the user state needed to reach it.')
    parser.add_argument('--no-login', action='store_true', help='stay logged out (for /login, /register, landing)')
    parser.add_argument('--dev-data', action='store_true', help='start from a copy of src/data/orex.db')
    parser.add_argument('--live-market', action='store_true', help='run the market engine so prices tick')
    parser.add_argument('--browser', metavar='PATH', help='path to chrome/msedge (default: auto-detect)')
    args = parser.parse_args()
    args.pages = [p if p.startswith('/') else '/' + p for p in args.pages]
    args.viewport = args.viewport or [parse_viewport('desktop')]
    return args


def main():
    args = parse_args()
    browser_path = find_browser(args.browser)
    if not browser_path:
        sys.exit('No Chrome/Edge found. Install one, or pass --browser PATH (or set CHROME_PATH).')

    os.makedirs(args.out, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix='orex_shots_')
    profile_dir = os.path.join(tmp_dir, 'browser-profile')
    server = proc = ws = None
    saved, problems, failed = [], 0, False
    try:
        db_path = prepare_database(tmp_dir, args.dev_data)
        server, base_url = start_app(db_path, args.live_market)
        debug_port = free_port()
        proc = launch_browser(browser_path, profile_dir, debug_port)
        ws = connect_to_browser(debug_port)
        cdp = CDP(ws)
        for domain in ('Page', 'Runtime', 'Network', 'Log'):
            cdp.call(f'{domain}.enable')

        if not args.no_login:
            username = f'shots{random.randint(1000, 9999)}'
            register_user(cdp, base_url, username)
            # Leave the post-registration page so none of its scripts (e.g. an
            # auto-starting tutorial) run while we change the user's state below
            cdp.navigate('about:blank')
            # The advanced track is only reachable once Advanced Mode is purchased
            if args.tutorial_walk == 'advanced':
                args.advanced = True
            apply_user_state(db_path, username, args)

        # Tutorial-walk mode: step through one track, one screenshot per step
        if args.tutorial_walk:
            theme = 'dark' if args.theme == 'dark' else 'light'
            set_theme_script(cdp, {}, theme, args.cosmetic)
            name, width, height = args.viewport[0]
            cdp.call('Emulation.setDeviceMetricsOverride', {
                'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width <= 600})
            cdp.reset_diagnostics()
            result = walk_tutorial(cdp, base_url, args.tutorial_walk, args.out, name)
            saved.extend([args.out] * result['saved'])
            if result['error']:
                print(f'FAILED  tutorial-walk {args.tutorial_walk}: {result["error"]}')
                failed = True
            for e in cdp.console_errors:
                print(f'          ! console: {e}')
                problems += 1

        # The normal multi-page loop is skipped entirely in tutorial-walk mode.
        themes = [] if args.tutorial_walk else (['light', 'dark'] if args.theme == 'both' else [args.theme])
        script_state = {}
        for theme in themes:
            set_theme_script(cdp, script_state, theme, args.cosmetic)
            for name, width, height in args.viewport:
                cdp.call('Emulation.setDeviceMetricsOverride', {
                    'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width <= 600})
                for page in args.pages:
                    out_path = os.path.join(args.out, f'{slugify(page)}_{name}_{theme}.png')
                    try:
                        warnings = capture(cdp, page, base_url, args, out_path)
                    except (CDPError, TimeoutError, RuntimeError) as exc:
                        print(f'FAILED  {page} [{name}/{theme}]: {exc}')
                        failed = True
                        continue
                    saved.append(out_path)
                    print(f'saved   {os.path.relpath(out_path, ROOT)}')
                    notes = warnings + [f'console: {e}' for e in cdp.console_errors] + \
                            [f'request: {r}' for r in cdp.failed_requests]
                    for note in notes:
                        print(f'          ! {note}')
                    problems += len(notes)
    except (RuntimeError, CDPError, TimeoutError, ConnectionError) as exc:
        print(f'ERROR: {exc}')
        failed = True
    finally:
        if ws:
            ws.close()
        stop_browser(proc)
        if server:
            server.shutdown()
        remove_dir(tmp_dir)

    print(f'\n{len(saved)} screenshot(s) in {os.path.relpath(args.out, ROOT)}'
          + (f', {problems} thing(s) worth a look (marked with !)' if problems else ''))
    # Console errors / odd statuses are reported but don't fail the run; real failures do
    sys.exit(1 if failed or not saved else 0)


if __name__ == '__main__':
    main()
