# 🔄 System Flow Diagram — OreX

A **System Flow Diagram** showing the sequence of processing steps and decisions
for the core user trading workflow in OreX.

---

## System Flow — Trading Workflow

```mermaid
flowchart TD
    START([Start]) --> LANDING[Display Landing Page]
    LANDING --> AUTH_CHECK{User Authenticated?}
    AUTH_CHECK -->|Yes| DASHBOARD[Display Dashboard]
    AUTH_CHECK -->|No| LOGIN_CHOICE{Login or Register?}

    LOGIN_CHOICE -->|Register| REG_FORM[Display Registration Form]
    REG_FORM --> REG_VALIDATE{Valid Input?}
    REG_VALIDATE -->|No| REG_ERROR[Display Validation Errors]
    REG_ERROR --> REG_FORM
    REG_VALIDATE -->|Yes| USERNAME_CHECK{Username Available?}
    USERNAME_CHECK -->|No| DUP_ERROR[Display Duplicate Error]
    DUP_ERROR --> REG_FORM
    USERNAME_CHECK -->|Yes| CREATE_USER[Create User Account with $10,000]
    CREATE_USER --> AUTO_LOGIN[Auto-Login User]
    AUTO_LOGIN --> DASHBOARD

    LOGIN_CHOICE -->|Login| LOGIN_FORM[Display Login Form]
    LOGIN_FORM --> RATE_CHECK{Rate Limited?}
    RATE_CHECK -->|Yes| RATE_ERROR[Display Rate Limit Error]
    RATE_ERROR --> LOGIN_FORM
    RATE_CHECK -->|No| CRED_CHECK{Credentials Valid?}
    CRED_CHECK -->|No| LOGIN_ERROR[Display Invalid Credentials Error]
    LOGIN_ERROR --> LOGIN_FORM
    CRED_CHECK -->|Yes| SESSION[Create Session]
    SESSION --> DASHBOARD

    DASHBOARD --> MARKET[Browse Market Overview]
    MARKET --> SELECT_ORE[Select Ore]
    SELECT_ORE --> ORE_DETAIL[View Ore Detail Page]

    ORE_DETAIL --> TRADE_CHOICE{Buy or Sell?}
    TRADE_CHOICE -->|Buy| ENTER_BUY_QTY[Enter Buy Quantity]
    ENTER_BUY_QTY --> QTY_VALID_BUY{Quantity Valid?}
    QTY_VALID_BUY -->|No| QTY_ERROR_BUY[Display Validation Error]
    QTY_ERROR_BUY --> ORE_DETAIL
    QTY_VALID_BUY -->|Yes| BALANCE_CHECK{Sufficient Balance?}
    BALANCE_CHECK -->|No| FUNDS_ERROR[Display Insufficient Funds Error]
    FUNDS_ERROR --> ORE_DETAIL
    BALANCE_CHECK -->|Yes| BUY_CONFIRM[Display Buy Confirmation]
    BUY_CONFIRM --> CONFIRM_BUY{User Confirms?}
    CONFIRM_BUY -->|No| ORE_DETAIL
    CONFIRM_BUY -->|Yes| EXEC_BUY[Execute Buy: Deduct Balance, Update Holdings, Record Transaction]
    EXEC_BUY --> RECORD_INFLUENCE_BUY[Record Trade for Market Influence]
    RECORD_INFLUENCE_BUY --> PORTFOLIO[Display Portfolio]

    TRADE_CHOICE -->|Sell| ENTER_SELL_QTY[Enter Sell Quantity]
    ENTER_SELL_QTY --> QTY_VALID_SELL{Quantity Valid?}
    QTY_VALID_SELL -->|No| QTY_ERROR_SELL[Display Validation Error]
    QTY_ERROR_SELL --> ORE_DETAIL
    QTY_VALID_SELL -->|Yes| HOLDING_CHECK{Sufficient Holdings?}
    HOLDING_CHECK -->|No| HOLD_ERROR[Display Insufficient Holdings Error]
    HOLD_ERROR --> ORE_DETAIL
    HOLDING_CHECK -->|Yes| SELL_CONFIRM[Display Sell Confirmation]
    SELL_CONFIRM --> CONFIRM_SELL{User Confirms?}
    CONFIRM_SELL -->|No| ORE_DETAIL
    CONFIRM_SELL -->|Yes| EXEC_SELL[Execute Sell: Credit Balance, Reduce Holdings, Record Transaction]
    EXEC_SELL --> RECORD_INFLUENCE_SELL[Record Trade for Market Influence]
    RECORD_INFLUENCE_SELL --> PORTFOLIO

    PORTFOLIO --> END([End])
```

---

## System Flow — Market Engine Tick

```mermaid
flowchart TD
    TICK_START([Tick Starts — Every 20 Seconds]) --> FETCH_ORES[Fetch All Ores from Database]
    FETCH_ORES --> BOT_TRADES[Execute Bot Trades for All Ores]
    BOT_TRADES --> LOOP_START[For Each Ore]

    LOOP_START --> CALC_CHANGE[Calculate % Price Change]
    CALC_CHANGE --> TREND[Apply Trend Effect to Probabilities]
    TREND --> GRAVITY[Apply Gravity Effect]
    GRAVITY --> EVENT_ROLL{Market Event? — 0.5% chance}
    EVENT_ROLL -->|Yes| MULTIPLY[Apply 3x Multiplier]
    EVENT_ROLL -->|No| SKIP_EVENT[No Multiplier]
    MULTIPLY --> INFLUENCE[Apply Player + Bot Influence]
    SKIP_EVENT --> INFLUENCE
    INFLUENCE --> VOLATILITY[Apply Volatility Scaling]
    VOLATILITY --> DECISION[Weighted Random Decision: Rise/Hold/Fall]
    DECISION --> APPLY[Apply Price Change]
    APPLY --> CLAMP[Clamp to Floor/Ceiling]
    CLAMP --> UPDATE_TREND[Update Trend Log]
    UPDATE_TREND --> PERSIST[Write New Price + History to Database]
    PERSIST --> MORE_ORES{More Ores?}
    MORE_ORES -->|Yes| LOOP_START
    MORE_ORES -->|No| COMMIT[Commit All Changes]
    COMMIT --> TICK_END([Tick Complete — Wait 20 Seconds])
```

---

## ✔️ Checklist

- [x] All major steps included
- [x] All decisions shown
- [x] Alternate paths included
- [x] Matches program behaviour
- [x] File renamed to **SystemFlow.md**
