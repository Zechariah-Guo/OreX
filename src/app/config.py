import os
from datetime import timedelta


DEFAULT_SECRET_KEY = 'orex-local-dev-secret-change-in-production'


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', DEFAULT_SECRET_KEY)
    DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'orex.db')
    DEFAULT_BALANCE = 10000
    TICK_INTERVAL = 20          # seconds
    MAX_BUY_QUANTITY = 500      # hard cap on total units held of a single ore in simple mode (no Advanced Mode)
    RATE_LIMIT_WINDOW = 900     # 15 minutes in seconds
    RATE_LIMIT_MAX = 5          # attempts per window
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_HTTPONLY = True
    # SESSION_COOKIE_SECURE is resolved in create_app(): the SESSION_COOKIE_SECURE env var
    # wins, otherwise True in production (not debug, not testing) and False elsewhere.
    SESSION_COOKIE_SECURE = False

    # "Stay signed in" cookie (Flask-Login). REMEMBER_COOKIE_SECURE follows
    # SESSION_COOKIE_SECURE and is resolved in create_app().
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = False

    # Advanced Mode
    ADVANCED_MODE_THRESHOLD = 100_000    # Net worth eligibility threshold
    ADVANCED_MODE_COST = 50_000          # Purchase cost
    ADVANCED_TOGGLE_COOLDOWN = 300       # 5 minutes in seconds
    RS_LOOKBACK_WINDOW = 50              # Price ticks for resistance/support

    # Shorting System Configuration
    SHORT_BASE_REQUIREMENT = 0.50        # Base collateral multiplier (50%)
    SHORT_MAX_PENALTY = 2.0              # Maximum crowding penalty
    SHORT_STEEPNESS = 3                  # Cubic exponent for penalty curve
    SHORT_BASE_HOURLY_RATE = 0.005       # 0.5% base fee per hour
    SHORT_MAX_HOURLY_FEE = 0.10          # Coefficient scaling hourly fee by ore's fixed volatility²
    SHORT_MAX_QUANTITY = 10000           # Max shares per short order
    SHORT_MIN_QUANTITY = 1               # Min shares per short order

    # Bot Shorting Configuration
    BOT_SHORT_TREND_THRESHOLD = 4        # 4/5 trend entries must be "fall"
    BOT_SHORT_SUSTAIN_TICKS = 30         # Must sustain 30 ticks of fees
    BOT_SHORT_CAPITAL_CAP = 0.30         # 30% of bot balance max in shorts
    BOT_SHORT_SL_PERCENT = 0.05          # 5% above entry for mandatory SL

    # Advancements System
    ADVANCEMENT_MILLIONAIRE_THRESHOLD = 1_000_000        # Net worth for Millionaire achievement
    ADVANCEMENT_MULTIMILLIONAIRE_THRESHOLD = 10_000_000  # Net worth for Multimillionaire achievement
    ADVANCEMENT_WHAT_A_DEAL_TRADES = 100                 # Trade count for Day Trader achievement
    ADVANCEMENT_SUIT_UP_MINUTES = 20                     # Play time minutes for Budding Enthusiast
    ADVANCEMENT_DEDICATED_STREAK = 3                     # Login streak days for Dedicated achievement
    ADVANCEMENT_POST_MORTEM_THRESHOLD = 10_000           # Net worth below which Tragedy triggers
    PLAYTIME_HEARTBEAT_INTERVAL = 60                     # Seconds between play time heartbeats
    PLAYTIME_MAX_INCREMENT = 5                           # Max minutes to add per heartbeat

    # Profile / Avatar
    STORAGE_BACKEND = os.environ.get('STORAGE_BACKEND', 'local')  # 'local' or 'oci'
    MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
    AVATAR_OUTPUT_SIZE = 300           # pixels (square)
    AVATAR_FORMAT = 'WEBP'             # output format

    # Oracle Object Storage (production only)
    OCI_NAMESPACE = os.environ.get('OCI_NAMESPACE', '')
    OCI_BUCKET = os.environ.get('OCI_BUCKET', 'orex-avatars')
    OCI_CONFIG_PATH = os.environ.get('OCI_CONFIG_PATH', '~/.oci/config')

    # Web Push (opt-in). All three must be set or push is switched off.
    # Generate a pair with scripts/admin/generate_vapid_keys.py.
    # VAPID_PUBLIC_KEY: base64url uncompressed P-256 point (sent to browsers).
    # VAPID_PRIVATE_KEY: base64url raw 32-byte private value (server only, never logged).
    # VAPID_SUBJECT: contact URL, 'mailto:you@example.com' or 'https://...'.
    VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '').strip()
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '').strip()
    VAPID_SUBJECT = os.environ.get('VAPID_SUBJECT', '').strip()
    PUSH_PRESENCE_SECONDS = 60           # a visible poll this recent means the player is present
    PUSH_PRESENCE_WRITE_INTERVAL = 15    # refresh the stored presence time at most this often
    PUSH_MAX_AGE_SECONDS = 300           # only notifications this fresh are pushed
    PUSH_TEST_COOLDOWN = 30              # seconds between test pushes per user

    # Dev /testing page: always on in debug mode; outside debug only when the env
    # var OREX_ENABLE_TESTING_PAGE=1 is set (read in create_app). Local Docker only.
    ENABLE_TESTING_PAGE = False

    # Daily Bonus
    BONUS_AMOUNTS = {1: 1000, 2: 10000, 3: 50000}

    # Tutorial System
    TUTORIAL_HIGHLIGHT_PADDING = 8       # pixels around target element
    TUTORIAL_TRANSITION_DURATION = 400   # ms for highlight animation
    TUTORIAL_BACKDROP_OPACITY = 0.5      # backdrop darkness (0.4-0.6)
    TUTORIAL_RESUME_TOAST_MS = 10000     # how long the "resume tutorial?" toast stays before auto-hiding
    TUTORIAL_DATA_PATH = 'static/data/tutorials.json'
