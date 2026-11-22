"""Cache policy for /static files.

Templates build static URLs with url_for('static', ...). register_static_caching()
swaps that one global for a wrapper that appends ?v=<file modification time>, so
a URL changes whenever the file's content does. That makes it safe to cache
versioned URLs for a year (immutable); browsers never revalidate them.

Static URLs without ?v= (CSS url(), JS-built URLs, the service worker's precache
list) cannot change with the file, so they get a short max-age; .html files
(the offline page the service worker precaches) are always revalidated.

User avatars live under static/uploads/avatars/<user_id>.webp and are overwritten
on every upload; their mtime changes, so their versioned URL changes too.
"""

import os

from flask import current_app, request, url_for as flask_url_for
from werkzeug.security import safe_join

VERSIONED_CACHE_CONTROL = 'public, max-age=31536000, immutable'
UNVERSIONED_CACHE_CONTROL = 'public, max-age=3600'
HTML_CACHE_CONTROL = 'no-cache'


def static_file_version(filename):
    """Return the modification time (ms) of a static file as a string, or None."""
    path = safe_join(current_app.static_folder, filename)
    if path is None:
        return None
    try:
        return str(os.stat(path).st_mtime_ns // 1_000_000)
    except OSError:
        return None


def versioned_static_url(filename, **values):
    """url_for('static', ...) with a ?v=<mtime> cache-busting query string."""
    version = static_file_version(filename)
    if version:
        values['v'] = version
    return flask_url_for('static', filename=filename, **values)


def _url_for(endpoint, **values):
    """Drop-in replacement for the Jinja url_for global."""
    if endpoint == 'static' and 'v' not in values and values.get('filename'):
        version = static_file_version(values['filename'])
        if version:
            values['v'] = version
    return flask_url_for(endpoint, **values)


def register_static_caching(app):
    app.jinja_env.globals['url_for'] = _url_for

    @app.after_request
    def set_static_cache_headers(response):
        if request.endpoint != 'static' or response.status_code not in (200, 304):
            return response
        if 'v' in request.args:
            response.headers['Cache-Control'] = VERSIONED_CACHE_CONTROL
        elif (request.view_args or {}).get('filename', '').endswith('.html'):
            response.headers['Cache-Control'] = HTML_CACHE_CONTROL
        else:
            response.headers['Cache-Control'] = UNVERSIONED_CACHE_CONTROL
        return response
