"""Shared handling of the optional inline recovery key on the register and
set-new-password forms.

The server generates the key when it renders the page and carries it in a
signed, time-limited token (hidden form field). Nothing about the key is stored
until the account is created or the reset commits, and only its hash is stored.
A token is bound to a purpose ('register' or 'reset') and, for reset, to the
pending user id, so it cannot be replayed on the other page or for another user.

The plain key is never logged and never put in the session.
"""

from flask import current_app, make_response, render_template
from itsdangerous import BadData, URLSafeTimedSerializer

from app.totp import generate_recovery_key

TOKEN_SALT = 'orex-recovery-key-token-v1'
REGISTER_TOKEN_MAX_AGE = 30 * 60  # 30 minutes
# Reset tokens never outlive the 5 minute reset session (recovery.PENDING_RESET_TTL).
RESET_TOKEN_MAX_AGE = 5 * 60

EXPIRED_NOTICE = 'Your recovery key expired, so a new one was generated; please save it.'
CONFIRM_ERROR = 'Please confirm that you have saved your recovery key.'


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=TOKEN_SALT)


def issue_token(key, purpose, user_id=None):
    """Sign ``key`` for ``purpose`` (and ``user_id`` for the reset page)."""
    return _serializer().dumps({'p': purpose, 'k': key, 'u': user_id})


def read_token(token, purpose, user_id=None, max_age=REGISTER_TOKEN_MAX_AGE):
    """Return the key from a valid token, or None if missing/tampered/expired/wrong."""
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=max_age)
    except BadData:
        return None
    if (
        not isinstance(data, dict)
        or data.get('p') != purpose
        or data.get('u') != user_id
        or not isinstance(data.get('k'), str)
    ):
        return None
    return data['k']


class RecoveryOption:
    """Outcome of reading the recovery-key part of a submitted form.

    ``key`` is the plain key to hash and store, or None when no key is wanted
    or the submission must be rejected. ``error`` (if set) means reject the
    submit. ``context`` holds the template variables for (re-)rendering the
    form with the same key and a fresh token.
    """

    def __init__(self, key, error, context):
        self.key = key
        self.error = error
        self.context = context


def _context(key, purpose, user_id, wanted, notice=None, error=None):
    return {
        'recovery_key': key,
        'recovery_token': issue_token(key, purpose, user_id),
        'recovery_wanted': wanted,
        'recovery_notice': notice,
        'recovery_error': error,
    }


def fresh_option(purpose, user_id=None, default_wanted=False):
    """Context for a GET: a new key, checkbox ticked or not by default."""
    return RecoveryOption(None, None, _context(
        generate_recovery_key(), purpose, user_id, default_wanted))


def read_option(form, purpose, user_id=None, max_age=REGISTER_TOKEN_MAX_AGE):
    """Evaluate a POSTed form's recovery-key fields."""
    wanted = bool(form.get('generate_recovery_key'))
    key = read_token(form.get('recovery_token'), purpose, user_id, max_age)

    if not wanted:
        # Ignore any token; keep the same key on the page in case of a re-render.
        return RecoveryOption(None, None, _context(
            key or generate_recovery_key(), purpose, user_id, False))

    if key is None:
        # Missing, tampered, expired or wrong-purpose token: reject, show a new key.
        return RecoveryOption(None, EXPIRED_NOTICE, _context(
            generate_recovery_key(), purpose, user_id, True, notice=EXPIRED_NOTICE))

    if not form.get('recovery_saved'):
        return RecoveryOption(None, CONFIRM_ERROR, _context(
            key, purpose, user_id, True, error=CONFIRM_ERROR))

    return RecoveryOption(key, None, _context(key, purpose, user_id, True))


def render_no_store(template, **context):
    """Render a page that contains a recovery key; never cache it."""
    response = make_response(render_template(template, **context))
    response.headers['Cache-Control'] = 'no-store'
    return response
