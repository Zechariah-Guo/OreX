from functools import wraps
from flask import abort
from flask_login import current_user


def advanced_required(f):
    """Block access unless the current user has Advanced Mode active."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        from app.advanced import is_advanced_active
        if not is_advanced_active(current_user.id):
            abort(403)
        return f(*args, **kwargs)
    return decorated
