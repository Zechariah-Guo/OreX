"""Property-based tests for the Tutorial System data layer.

Covers the tutorial data loader and the tutorial_progress model functions.
Model tests run against an in-memory SQLite DB built from the canonical
src/schema.sql, with ``get_db`` patched to return that connection.
"""

import json
import os
import sqlite3
import sys
from unittest.mock import patch

# Add src/ to the Python path so that `from app.tutorial import ...` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.tutorial import data as tutorial_data
from app.tutorial import models as tm

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'schema.sql'
)

STATUSES = ['not_started', 'in_progress', 'completed', 'dismissed']
TRACK_IDS = ['beginner', 'advanced']
POSITIONS = ['top', 'bottom', 'left', 'right', 'center']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(user_ids=()):
    """Create an in-memory DB from schema.sql with the given user IDs inserted."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    with open(SCHEMA_PATH, 'r') as f:
        conn.executescript(f.read())
    for uid in user_ids:
        conn.execute(
            'INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)',
            (uid, f'user{uid}', 'hash'),
        )
    conn.commit()
    return conn


def _count(conn, user_id, track_id):
    return conn.execute(
        'SELECT COUNT(*) FROM tutorial_progress WHERE user_id = ? AND track_id = ?',
        (user_id, track_id),
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

text_field = st.text(min_size=1, max_size=60)

step_strategy = st.fixed_dictionaries({
    'selector': text_field,
    'route': st.sampled_from(['/dashboard', '/market', '/portfolio', '/leaderboard']),
    'title': text_field,
    'description': text_field,
    'position': st.sampled_from(POSITIONS),
    'action': st.one_of(st.none(), text_field),
})


@st.composite
def track_strategy(draw):
    steps = draw(st.lists(step_strategy, min_size=1, max_size=10))
    for i, step in enumerate(steps):
        step['index'] = i
    return {
        'id': draw(st.sampled_from(TRACK_IDS)),
        'name': draw(text_field),
        'trigger': draw(st.sampled_from(['first_login', 'first_advanced_activation'])),
        'steps': steps,
    }


# ---------------------------------------------------------------------------
# Data loader (task 2.1) - example-based sanity checks on the real JSON file
# ---------------------------------------------------------------------------

def test_loader_reads_both_tracks():
    ids = [t['id'] for t in tutorial_data.load_all_tracks()]
    assert ids == ['beginner', 'advanced']
    assert tutorial_data.load_track('nope') is None
    n = tutorial_data.get_track_length('beginner')
    assert n > 0
    assert tutorial_data.get_step('beginner', 0)['index'] == 0
    assert tutorial_data.get_step('beginner', n) is None
    assert tutorial_data.get_step('beginner', -1) is None
    assert tutorial_data.get_track_length('nope') == 0


def test_loader_steps_have_required_fields():
    for meta in tutorial_data.load_all_tracks():
        track = tutorial_data.load_track(meta['id'])
        for i, step in enumerate(track['steps']):
            assert step['index'] == i
            assert step['position'] in POSITIONS
            for key in ('selector', 'route', 'title', 'description', 'action'):
                assert key in step


# ---------------------------------------------------------------------------
# Property 1: Tutorial Data Serialization Round-Trip
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 1: serializing a track to JSON and back preserves it
# Validates: Requirements 1.1, 1.2
@settings(max_examples=100)
@given(track=track_strategy())
def test_property_1_serialization_round_trip(track):
    assert json.loads(json.dumps(track)) == track
    assert json.loads(json.dumps({'tracks': [track]}))['tracks'][0] == track


# ---------------------------------------------------------------------------
# Property 2: Auto-Trigger Correctness
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 2: auto-trigger iff no record or status not_started
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
@settings(max_examples=100)
@given(status=st.sampled_from([None] + STATUSES), track_id=st.sampled_from(TRACK_IDS))
def test_property_2_auto_trigger(status, track_id):
    conn = _make_db([1])
    with patch.object(tm, 'get_db', return_value=conn):
        if status is not None:
            tm.create_or_update_tutorial_state(1, track_id, status, 0)
        expected = status is None or status == 'not_started'
        assert tm.should_auto_trigger(1, track_id) is expected
    conn.close()


# ---------------------------------------------------------------------------
# Property 7: Tutorial State Persistence Round-Trip
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 7: written state reads back identically
# Validates: Requirements 5.2, 6.1, 6.2
@settings(max_examples=100)
@given(
    user_id=st.integers(1, 1000),
    track_id=st.sampled_from(TRACK_IDS),
    status=st.sampled_from(STATUSES),
    step_index=st.integers(0, 20),
)
def test_property_7_state_round_trip(user_id, track_id, status, step_index):
    conn = _make_db([user_id])
    with patch.object(tm, 'get_db', return_value=conn):
        tm.create_or_update_tutorial_state(user_id, track_id, status, step_index)
        state = tm.get_tutorial_state(user_id, track_id)
        assert state['track_id'] == track_id
        assert state['status'] == status
        assert state['current_step_index'] == step_index
        assert [s['track_id'] for s in tm.get_all_tutorial_states(user_id)] == [track_id]
    conn.close()


# ---------------------------------------------------------------------------
# Property 12: UNIQUE Constraint on User-Track Pair
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 12: duplicate (user_id, track_id) insert raises IntegrityError
# Validates: Requirements 11.2
@settings(max_examples=100)
@given(user_id=st.integers(1, 100), track_id=st.sampled_from(TRACK_IDS))
def test_property_12_unique_user_track(user_id, track_id):
    conn = _make_db([user_id])
    insert = 'INSERT INTO tutorial_progress (user_id, track_id) VALUES (?, ?)'
    conn.execute(insert, (user_id, track_id))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, (user_id, track_id))
    assert _count(conn, user_id, track_id) == 1
    conn.close()


# ---------------------------------------------------------------------------
# Property 14: Tutorial State Upsert Behavior
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 14: upsert creates when absent, updates (no duplicate) when present
# Validates: Requirements 11.5
@settings(max_examples=100)
@given(
    user_id=st.integers(1, 100),
    track_id=st.sampled_from(TRACK_IDS),
    record_exists=st.booleans(),
    status=st.sampled_from(STATUSES),
    step_index=st.integers(0, 20),
)
def test_property_14_upsert(user_id, track_id, record_exists, status, step_index):
    conn = _make_db([user_id])
    with patch.object(tm, 'get_db', return_value=conn):
        first_id = None
        if record_exists:
            first_id = tm.create_or_update_tutorial_state(user_id, track_id, 'in_progress', 3)
            assert _count(conn, user_id, track_id) == 1
        else:
            assert _count(conn, user_id, track_id) == 0

        row_id = tm.create_or_update_tutorial_state(user_id, track_id, status, step_index)

        assert _count(conn, user_id, track_id) == 1
        if record_exists:
            assert row_id == first_id
        state = tm.get_tutorial_state(user_id, track_id)
        assert state['status'] == status
        assert state['current_step_index'] == step_index
    conn.close()


# ---------------------------------------------------------------------------
# Property 10: Replay Resets Tutorial State to Beginning
# ---------------------------------------------------------------------------

# Feature: tutorial-system, Property 10: replay sets in_progress / step 0; complete & dismiss reset step to 0
# Validates: Requirements 7.3, 11.6
@settings(max_examples=100)
@given(
    track_id=st.sampled_from(TRACK_IDS),
    status=st.sampled_from(['completed', 'dismissed']),
    step_index=st.integers(0, 20),
)
def test_property_10_replay_resets_state(track_id, status, step_index):
    conn = _make_db([1])
    with patch.object(tm, 'get_db', return_value=conn):
        tm.create_or_update_tutorial_state(1, track_id, status, step_index)
        assert tm.replay_tutorial(1, track_id) is True
        state = tm.get_tutorial_state(1, track_id)
        assert state['status'] == 'in_progress'
        assert state['current_step_index'] == 0

        # Reaching completed/dismissed also resets the step index
        tm.advance_step(1, track_id, step_index)
        finish = tm.complete_tutorial if status == 'completed' else tm.dismiss_tutorial
        assert finish(1, track_id) is True
        state = tm.get_tutorial_state(1, track_id)
        assert state['status'] == status
        assert state['current_step_index'] == 0
    conn.close()


# ---------------------------------------------------------------------------
# Remaining model functions (no dedicated property): example-based checks
# ---------------------------------------------------------------------------

def test_missing_record_behaviour():
    conn = _make_db([1])
    with patch.object(tm, 'get_db', return_value=conn):
        assert tm.get_tutorial_state(1, 'beginner') is None
        assert tm.get_all_tutorial_states(1) == []
        assert tm.advance_step(1, 'beginner', 2) is False
        assert tm.complete_tutorial(1, 'beginner') is False
        assert tm.delete_tutorial_progress(1) == 0
    conn.close()


def test_advance_and_delete():
    conn = _make_db([1, 2])
    with patch.object(tm, 'get_db', return_value=conn):
        tm.create_or_update_tutorial_state(1, 'beginner', 'in_progress', 0)
        tm.create_or_update_tutorial_state(1, 'advanced', 'in_progress', 0)
        tm.create_or_update_tutorial_state(2, 'beginner', 'in_progress', 0)
        assert tm.advance_step(1, 'beginner', 4) is True
        assert tm.get_tutorial_state(1, 'beginner')['current_step_index'] == 4
        assert tm.delete_tutorial_progress(1) == 2
        assert tm.get_all_tutorial_states(1) == []
        assert len(tm.get_all_tutorial_states(2)) == 1
    conn.close()
