"""Property-based tests for the pure logic in src/static/js/tutorial.js.

The functions under test (card positioning, highlight geometry, button state,
route comparison, step counter text) are exported by tutorial.js for Node. A
single long-lived Node process (tests/tutorial_logic_runner.js) evaluates them,
so these tests exercise the real browser code. The module is skipped when
Node.js is not installed.
"""

import atexit
import json
import os
import shutil
import subprocess

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

NODE = shutil.which('node')
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tutorial_logic_runner.js')

pytestmark = pytest.mark.skipif(NODE is None, reason='Node.js is required for the tutorial.js logic tests')

POSITIONS = ['top', 'bottom', 'left', 'right', 'center']
EPS = 1e-6

_runner = None


def _stop_runner():
    if _runner is not None and _runner.poll() is None:
        _runner.kill()


def call_js(fn, *args):
    """Call an exported tutorial.js helper and return its JSON-decoded result."""
    global _runner
    if _runner is None or _runner.poll() is not None:
        _runner = subprocess.Popen(
            [NODE, RUNNER],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', bufsize=1,
        )
        atexit.register(_stop_runner)
    _runner.stdin.write(json.dumps({'fn': fn, 'args': list(args)}) + '\n')
    _runner.stdin.flush()
    line = _runner.stdout.readline()
    if not line:
        raise RuntimeError('Node runner exited unexpectedly')
    reply = json.loads(line)
    assert 'error' not in reply, reply['error']
    return reply['result']


def finite(lo, hi):
    return st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Property 4: Step Card Positioning Within Viewport
# ---------------------------------------------------------------------------

@st.composite
def card_placement(draw):
    viewport = {'width': draw(finite(300, 3000)), 'height': draw(finite(300, 3000))}
    card = {
        'width': draw(finite(100, min(420, viewport['width']))),
        'height': draw(finite(80, min(400, viewport['height']))),
    }
    highlight = {
        'top': draw(finite(-500, 3500)), 'left': draw(finite(-500, 3500)),
        'width': draw(finite(0, 3000)), 'height': draw(finite(0, 3000)),
    }
    position = draw(st.sampled_from(POSITIONS + ['unknown']))
    return position, highlight, card, viewport


# Feature: tutorial-system, Property 4: the step card is always placed fully inside the viewport
# Validates: Requirements 4.2
@settings(max_examples=200, deadline=None)
@given(case=card_placement())
def test_property_4_card_stays_in_viewport(case):
    position, highlight, card, viewport = case
    result = call_js('computeCardPosition', position, highlight, card, viewport)
    assert result['left'] >= -EPS
    assert result['top'] >= -EPS
    assert result['left'] + card['width'] <= viewport['width'] + EPS
    assert result['top'] + card['height'] <= viewport['height'] + EPS
    assert result['side'] in POSITIONS


def test_card_prefers_requested_side_and_flips_when_cramped():
    viewport = {'width': 1000, 'height': 800}
    card = {'width': 300, 'height': 150}
    roomy = {'top': 300, 'left': 400, 'width': 200, 'height': 80}
    below = call_js('computeCardPosition', 'bottom', roomy, card, viewport)
    assert below['side'] == 'bottom' and below['top'] >= roomy['top'] + roomy['height']
    above = call_js('computeCardPosition', 'top', roomy, card, viewport)
    assert above['side'] == 'top' and above['top'] + card['height'] <= roomy['top']

    # Target near the bottom edge: "bottom" does not fit, so the card flips above it
    low = {'top': 700, 'left': 100, 'width': 200, 'height': 80}
    flipped = call_js('computeCardPosition', 'bottom', low, card, viewport)
    assert flipped['side'] == 'top'

    # Centre placement ignores the target and centres in the viewport
    centred = call_js('computeCardPosition', 'center', low, card, viewport)
    assert centred['left'] == pytest.approx((1000 - 300) / 2)
    assert centred['top'] == pytest.approx((800 - 150) / 2)


# ---------------------------------------------------------------------------
# Property 5: Navigation Button State Matches Step Position
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 5: Back disabled iff first step; forward says Finish iff last step
# Validates: Requirements 4.4, 4.6
@settings(max_examples=100, deadline=None)
@given(length=st.integers(1, 50), data=st.data())
def test_property_5_nav_button_state(length, data):
    index = data.draw(st.integers(0, length - 1))
    state = call_js('navState', index, length)
    assert state['backDisabled'] is (index == 0)
    assert state['isLast'] is (index == length - 1)
    assert state['forwardLabel'] == ('Finish' if index == length - 1 else 'Next')


# ---------------------------------------------------------------------------
# Property 6: Cross-Page Navigation Triggers on Route Mismatch
# ---------------------------------------------------------------------------

ROUTES = ['/', '/dashboard', '/market', '/market/1', '/portfolio', '/leaderboard', '/finances']
URL_NOISE = ['', '/', '?x=1', '#section', '/?q=2#z']


# Feature: tutorial-system, Property 6: moving between consecutive steps navigates iff their routes differ
# Validates: Requirements 5.1, 5.5
@settings(max_examples=100, deadline=None)
@given(routes=st.lists(st.sampled_from(ROUTES), min_size=2, max_size=10))
def test_property_6_navigation_on_route_mismatch(routes):
    for current, target in zip(routes, routes[1:]):
        expected = current != target
        assert call_js('needsPageNavigation', current, target) is expected    # going forward
        assert call_js('needsPageNavigation', target, current) is expected    # going back


# Feature: tutorial-system, Property 6 (supporting): trailing slash, query string and hash never count as a different page
# Validates: Requirements 5.1
@settings(max_examples=100, deadline=None)
@given(route=st.sampled_from(ROUTES), noise=st.sampled_from(URL_NOISE))
def test_property_6_url_noise_is_not_a_route_change(route, noise):
    assert call_js('needsPageNavigation', route + noise, route) is False


# ---------------------------------------------------------------------------
# Property 11: Highlight Box Dimensions from Target Rect Plus Padding
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 11: highlight = (top-P, left-P, width+2P, height+2P)
# Validates: Requirements 9.6
@settings(max_examples=100, deadline=None)
@given(
    rect=st.fixed_dictionaries({
        'top': finite(-1000, 3000), 'left': finite(-1000, 3000),
        'width': finite(0, 3000), 'height': finite(0, 3000),
    }),
    padding=finite(0, 50),
)
def test_property_11_highlight_dimensions(rect, padding):
    box = call_js('computeHighlight', rect, padding)
    assert box['top'] == rect['top'] - padding
    assert box['left'] == rect['left'] - padding
    assert box['width'] == rect['width'] + 2 * padding
    assert box['height'] == rect['height'] + 2 * padding


# ---------------------------------------------------------------------------
# Property 3 (part): the progress indicator text
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 3: the progress indicator reads "Step {I+1} of {N}"
# Validates: Requirements 4.1
@settings(max_examples=100, deadline=None)
@given(total=st.integers(1, 50), data=st.data())
def test_property_3_step_counter_text(total, data):
    index = data.draw(st.integers(0, total - 1))
    assert call_js('stepCounterText', index, total) == f'Step {index + 1} of {total}'
