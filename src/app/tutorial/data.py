"""Tutorial track/step definitions loaded from a JSON file.

The file location comes from ``Config.TUTORIAL_DATA_PATH`` (relative to the
``src/`` directory). If the file is missing or malformed the error is logged
and the tutorial system behaves as if no tracks exist.
"""

import json
import logging
import os

from app.config import Config

logger = logging.getLogger(__name__)

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _data_path():
    return os.path.join(_SRC_DIR, Config.TUTORIAL_DATA_PATH)


def _load_tracks():
    """Read the JSON file and return the list of usable tracks (>= 1 step)."""
    try:
        with open(_data_path(), 'r', encoding='utf-8') as f:
            raw = json.load(f)
        tracks = raw['tracks']
        if not isinstance(tracks, list):
            raise ValueError('"tracks" must be a list')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.error('Could not load tutorial data from %s: %s', _data_path(), exc)
        return []
    # A track with zero steps is treated as non-existent
    return [t for t in tracks if isinstance(t, dict) and t.get('steps')]


def load_track(track_id):
    """Return the full track dict for track_id, or None if unknown."""
    for track in _load_tracks():
        if track.get('id') == track_id:
            return track
    return None


def load_all_tracks():
    """Return metadata (id, name, trigger) for every available track."""
    return [
        {'id': t.get('id'), 'name': t.get('name'), 'trigger': t.get('trigger')}
        for t in _load_tracks()
    ]


def get_step(track_id, step_index):
    """Return a single step dict, or None if the track or index is invalid."""
    track = load_track(track_id)
    if track is None:
        return None
    steps = track['steps']
    if not isinstance(step_index, int) or isinstance(step_index, bool):
        return None
    if step_index < 0 or step_index >= len(steps):
        return None
    return steps[step_index]


def get_track_length(track_id):
    """Return the number of steps in a track (0 if the track is unknown)."""
    track = load_track(track_id)
    return len(track['steps']) if track else 0
