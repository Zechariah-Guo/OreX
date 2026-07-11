# 🧩 Class Diagram — OreX

A **Class Diagram** showing the object-oriented structure of the OreX system:
classes, attributes, methods, and relationships.

---

## Class Diagram

```mermaid
classDiagram
    class User {
        - id: int
        - username: str
        - balance: float
        + get_id(): str
        + is_authenticated(): bool
        + is_active(): bool
    }

    class Config {
        - SECRET_KEY: str
        - DATABASE_PATH: str
        - DEFAULT_BALANCE: int
        - TICK_INTERVAL: int
        - RATE_LIMIT_WINDOW: int
        - RATE_LIMIT_MAX: int
    }

    class Database {
        + get_db(): Connection
        + close_db(e): None
        + init_db(app): None
    }

    class Models {
        + create_user(username, password): int
        + get_user_by_id(user_id): User
        + get_user_by_username(username): Row
        + update_balance(user_id, new_balance): None
        + update_last_login(user_id): None
        + verify_password(stored_hash, password): bool
        + get_all_ores(): list
        + get_ore_by_id(ore_id): Row
        + get_holdings_by_user(user_id): list
        + get_holding(user_id, ore_id): Row
        + create_holding(user_id, ore_id, quantity, price): None
        + update_holding(holding_id, new_quantity, new_avg_price): None
        + delete_holding(holding_id): None
        + create_transaction(user_id, ore_id, type, quantity, price, total): None
        + get_transactions_by_user(user_id, limit): list
        + get_transactions_paginated(user_id, page, per_page, show_archived): tuple
        + get_recent_transactions(user_id, limit): list
        + get_price_history(ore_id, limit, hours): list
        + get_portfolio_value(user_id): float
        + get_portfolio_cost(user_id): float
        + get_top_movers(limit): list
        + get_leaderboard(): list
        + update_password(user_id, new_password): None
        + reset_account(user_id): None
        + delete_account(user_id): None
    }

    class MarketEngine {
        - _engine_thread: Thread
        + start_engine(app): None
        - tick_loop(): None
    }

    class Algorithm {
        + process_tick(db): None
        - _apply_trend_effect(probs, trend_log): list
        - _apply_gravity_effect(probs, current_price, base_price): list
        - _apply_player_influence(probs, ore_id): list
        - _apply_bot_influence_from_trades(probs, net_buy_units): list
        - _apply_disruption(probs, volatility): list
        - _weighted_random(probs): str
        - _normalise_probs(probs): list
    }

    class Bots {
        - NUM_BOTS: int
        - BOT_NAMES: list
        + ensure_bots_exist(db, default_balance): None
        + get_bot_user_ids(db): list
        + execute_bot_trades(db, ores): dict
        - _get_bot_decision(current_price, base_price): str
        - _bot_buy(db, bot_id, ore_id, quantity, price): None
        - _bot_sell(db, bot_id, ore_id, quantity, price): int
    }

    class Events {
        - EVENT_CHANCE: float
        - EVENT_MULTIPLIER: float
        + roll_event(): bool
        + apply_event_multiplier(price_change): float
    }

    class Influence {
        - _lock: Lock
        - _trades: list
        + record_player_trade(ore_id, quantity, trade_type): None
        + consume_player_trades(ore_id): list
    }

    class Validation {
        + validate_username(username): tuple
        + validate_password(password): tuple
        + validate_quantity(quantity_str): tuple
    }

    class Formatting {
        + format_currency(value): str
        + format_percentage(value): str
        + register_filters(app): None
    }

    %% Relationships
    MarketEngine --> Algorithm : invokes process_tick
    Algorithm --> Bots : executes bot trades
    Algorithm --> Events : rolls for events
    Algorithm --> Influence : consumes player trades
    Models --> Database : uses get_db
    User --> Models : loaded by get_user_by_id
    Bots --> Models : reads/writes holdings and transactions
    Validation --> Models : validates before create_user
```

---

## ✔️ Checklist

- [x] All classes included
- [x] Attributes + types shown
- [x] Methods listed
- [x] Relationships correct
- [x] Diagram renders on GitHub
- [x] File renamed to **ClassDiagram.md**
