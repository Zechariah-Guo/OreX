import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'orex-local-dev-secret-change-in-production')
    DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'orex.db')
    DEFAULT_BALANCE = 10000
    TICK_INTERVAL = 20          # seconds
    MAX_BUY_QUANTITY = 500      # hard cap on single buy order in simple mode (no Advanced Mode)
    RATE_LIMIT_WINDOW = 900     # 15 minutes in seconds
    RATE_LIMIT_MAX = 5          # attempts per window
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False   # Set True in production with HTTPS

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
    SHORT_MAX_HOURLY_FEE = 0.10          # 10% max fee per hour at peak volatility
    SHORT_MAX_QUANTITY = 10000           # Max shares per short order
    SHORT_MIN_QUANTITY = 1               # Min shares per short order

    # Bot Shorting Configuration
    BOT_SHORT_TREND_THRESHOLD = 4        # 4/5 trend entries must be "fall"
    BOT_SHORT_SUSTAIN_TICKS = 30         # Must sustain 30 ticks of fees
    BOT_SHORT_CAPITAL_CAP = 0.30         # 30% of bot balance max in shorts
    BOT_SHORT_SL_PERCENT = 0.05          # 5% above entry for mandatory SL
