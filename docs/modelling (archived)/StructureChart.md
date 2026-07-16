# 🧱 Structure Chart — OreX

A **Structure Chart** showing the modular decomposition of the OreX application —
the hierarchy of modules, functions, and subroutines that match the actual code.

---

## Structure Chart

### Top-Level Modules

```mermaid
flowchart TD
    MAIN["run.py"]
    MAIN --> FACTORY["create_app()"]

    FACTORY --> CONFIG["config.py"]
    FACTORY --> DB["database.py"]
    FACTORY --> MODELS["models.py"]
    FACTORY --> ROUTES["routes/"]
    FACTORY --> MARKET["market/"]
    FACTORY --> UTILS["utils/"]
```

### database.py

```mermaid
flowchart TD
    DB["database.py"]
    DB --> DB1["init_db()"]
    DB --> DB2["get_db()"]
    DB --> DB3["close_db()"]
```

### models.py — User Functions

```mermaid
flowchart TD
    M["models.py — Users"]
    M --> M1["create_user()"]
    M --> M2["get_user_by_id()"]
    M --> M3["get_user_by_username()"]
    M --> M4["update_balance()"]
    M --> M5["update_last_login()"]
    M --> M6["verify_password()"]
```

### models.py — Ore and Holdings Functions

```mermaid
flowchart TD
    MO["models.py — Ores"]
    MO --> MO1["get_all_ores()"]
    MO --> MO2["get_ore_by_id()"]

    MH["models.py — Holdings"]
    MH --> MH1["get_holdings_by_user()"]
    MH --> MH2["get_holding()"]
    MH --> MH3["create_holding()"]
    MH --> MH4["update_holding()"]
    MH --> MH5["delete_holding()"]
```

### models.py — Transaction, Dashboard, and Account Functions

```mermaid
flowchart TD
    MT["models.py — Transactions"]
    MT --> MT1["create_transaction()"]
    MT --> MT2["get_transactions_by_user()"]
    MT --> MT3["get_transactions_paginated()"]
    MT --> MT4["get_recent_transactions()"]

    MD["models.py — Dashboard"]
    MD --> MD1["get_portfolio_value()"]
    MD --> MD2["get_portfolio_cost()"]
    MD --> MD3["get_top_movers()"]
    MD --> MD4["get_price_history()"]

    MA["models.py — Account"]
    MA --> MA1["get_leaderboard()"]
    MA --> MA2["update_password()"]
    MA --> MA3["reset_account()"]
    MA --> MA4["delete_account()"]
```

### routes/ — Blueprints

```mermaid
flowchart TD
    R["routes/"]
    R --> R1["auth.py"]
    R --> R2["dashboard.py"]
    R --> R3["market.py"]
    R --> R4["trade.py"]
    R --> R5["portfolio.py"]
    R --> R6["leaderboard.py"]
    R --> R7["history.py"]
    R --> R8["settings.py"]
    R --> R9["pages.py"]
```

### routes/auth.py

```mermaid
flowchart TD
    RA["auth.py"]
    RA --> RA1["register()"]
    RA --> RA2["login()"]
    RA --> RA3["logout()"]
    RA --> RA4["_is_rate_limited()"]
    RA --> RA5["_record_attempt()"]
```

### routes/trade.py and routes/market.py

```mermaid
flowchart TD
    RT["trade.py"]
    RT --> RT1["buy()"]
    RT --> RT2["sell()"]

    RM["market.py"]
    RM --> RM1["overview()"]
    RM --> RM2["ore_detail()"]
    RM --> RM3["ore_price_history()"]
```

### market/ — Engine Package

```mermaid
flowchart TD
    MK["market/"]
    MK --> E["engine.py"]
    MK --> AL["algorithm.py"]
    MK --> BO["bots.py"]
    MK --> EV["events.py"]
    MK --> IN["influence.py"]
```

### market/engine.py and market/events.py

```mermaid
flowchart TD
    E["engine.py"]
    E --> E1["start_engine()"]
    E --> E2["tick_loop()"]

    EV["events.py"]
    EV --> EV1["roll_event()"]
    EV --> EV2["apply_event_multiplier()"]
```

### market/algorithm.py

```mermaid
flowchart TD
    A["algorithm.py"]
    A --> A1["process_tick()"]
    A --> A2["_apply_trend_effect()"]
    A --> A3["_apply_gravity_effect()"]
    A --> A4["_apply_player_influence()"]
    A --> A5["_apply_bot_influence()"]
    A --> A6["_apply_disruption()"]
    A --> A7["_weighted_random()"]
    A --> A8["_normalise_probs()"]
```

### market/bots.py

```mermaid
flowchart TD
    B["bots.py"]
    B --> B1["ensure_bots_exist()"]
    B --> B2["get_bot_user_ids()"]
    B --> B3["execute_bot_trades()"]
    B --> B4["_get_bot_decision()"]
    B --> B5["_bot_buy()"]
    B --> B6["_bot_sell()"]
```

### market/influence.py and utils/

```mermaid
flowchart TD
    IN["influence.py"]
    IN --> I1["record_player_trade()"]
    IN --> I2["consume_player_trades()"]

    VA["validation.py"]
    VA --> V1["validate_username()"]
    VA --> V2["validate_password()"]
    VA --> V3["validate_quantity()"]

    FO["formatting.py"]
    FO --> F1["format_currency()"]
    FO --> F2["format_percentage()"]
    FO --> F3["register_filters()"]
```

---

## ✔️ Checklist

- [x] Main module shown at the top
- [x] All major functions included
- [x] Helper functions shown under their parent modules
- [x] Names match the actual code
- [x] Diagram renders correctly on GitHub
- [x] File renamed to **StructureChart.md**
