"""Number and currency formatting filters for Jinja2 templates."""

from datetime import datetime


def format_currency(value):
    """Format a number as currency (e.g. $1,234.56)."""
    if value is None:
        return '$0.00'
    return f"${value:,.2f}"


def format_percentage(value):
    """Format a number as a percentage with sign (e.g. +12.34% or -5.67%)."""
    if value is None:
        return '0.00%'
    sign = '+' if value >= 0 else ''
    return f"{sign}{value:.2f}%"


def timeago(value):
    """Convert a datetime string to a relative time description (e.g. '2 hours ago').

    Accepts ISO-format datetime strings like '2024-01-15T10:30:00' or
    '2024-01-15 10:30:00'. Returns the original value if parsing fails.
    """
    if value is None:
        return ''
    try:
        # Handle both 'T' separator and space separator
        dt_str = str(value).replace('T', ' ')
        dt = datetime.strptime(dt_str[:19], '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return str(value)

    now = datetime.now()
    diff = now - dt

    seconds = int(diff.total_seconds())
    if seconds < 0:
        return 'just now'
    elif seconds < 60:
        return 'just now'
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} min ago" if minutes == 1 else f"{minutes} mins ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour ago" if hours == 1 else f"{hours} hours ago"
    elif seconds < 604800:
        days = seconds // 86400
        return f"{days} day ago" if days == 1 else f"{days} days ago"
    else:
        # Fall back to short date format for older notifications
        return dt.strftime('%d %b %Y')


def register_filters(app):
    """Register custom Jinja2 template filters."""
    app.jinja_env.filters['currency'] = format_currency
    app.jinja_env.filters['percentage'] = format_percentage
    app.jinja_env.filters['timeago'] = timeago
