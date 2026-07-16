# 🔁 Data Flow Diagram (Level 1) — OreX

A **Level 1 DFD** expanding the Context Diagram by breaking the OreX system
into multiple processes, data stores, external entities, and labelled data flows.

---

## Level 1 DFD

### 1.0 Authentication

```mermaid
flowchart LR
    VISITOR([Visitor])
    PLAYER([Player])
    P1((1.0 Auth))
    D1[(D1 Users)]

    VISITOR -->|Registration Details| P1
    VISITOR -->|Login Credentials| P1
    P1 -->|Auth Response| VISITOR
    P1 -->|Auth Response| PLAYER
    P1 -->|New User Record| D1
    D1 -->|User Credentials| P1
```

### 2.0 Market Display

```mermaid
flowchart LR
    PLAYER([Player])
    P2((2.0 Market Display))
    D2[(D2 Ores)]
    D5[(D5 Price History)]

    PLAYER -->|Page Request| P2
    P2 -->|Ore Prices and Charts| PLAYER
    D2 -->|Ore Data| P2
    D5 -->|Historical Prices| P2
```

### 3.0 Trade Execution

```mermaid
flowchart LR
    PLAYER([Player])
    P3((3.0 Trade))
    D1[(D1 Users)]
    D2[(D2 Ores)]
    D3[(D3 Holdings)]
    D4[(D4 Transactions)]

    PLAYER -->|Trade Order| P3
    P3 -->|Trade Confirmation| PLAYER
    D1 -->|User Balance| P3
    D2 -->|Current Price| P3
    D3 -->|Existing Holdings| P3
    P3 -->|Updated Balance| D1
    P3 -->|Updated Holdings| D3
    P3 -->|Transaction Record| D4
```

### 4.0 Portfolio Management

```mermaid
flowchart LR
    PLAYER([Player])
    P4((4.0 Portfolio))
    D2[(D2 Ores)]
    D3[(D3 Holdings)]

    PLAYER -->|Portfolio Request| P4
    P4 -->|Holdings and P/L| PLAYER
    D3 -->|User Holdings| P4
    D2 -->|Current Prices| P4
```

### 5.0 Price Calculation

```mermaid
flowchart LR
    ENGINE([Market Engine])
    P5((5.0 Price Calc))
    D2[(D2 Ores)]
    D5[(D5 Price History)]

    ENGINE -->|Tick Trigger| P5
    D2 -->|Ore Configuration| P5
    P5 -->|Updated Prices| D2
    P5 -->|Price Record| D5
```

### 6.0 Bot Trading

```mermaid
flowchart LR
    BOT([Bot Trader])
    ENGINE([Market Engine])
    P6((6.0 Bot Trading))
    D1[(D1 Users)]
    D2[(D2 Ores)]
    D3[(D3 Holdings)]
    D4[(D4 Transactions)]

    ENGINE -->|Tick Trigger| P6
    BOT -->|Trade Decisions| P6
    D2 -->|Current Prices| P6
    D1 -->|Bot Balances| P6
    D3 -->|Bot Holdings| P6
    P6 -->|Updated Balance| D1
    P6 -->|Updated Holdings| D3
    P6 -->|Transaction Record| D4
```

### 7.0 Leaderboard

```mermaid
flowchart LR
    PLAYER([Player])
    P7((7.0 Leaderboard))
    D1[(D1 Users)]
    D2[(D2 Ores)]
    D3[(D3 Holdings)]

    PLAYER -->|Leaderboard Request| P7
    P7 -->|Rankings| PLAYER
    D1 -->|All Balances| P7
    D3 -->|All Holdings| P7
    D2 -->|Current Prices| P7
```

### 8.0 Account Management

```mermaid
flowchart LR
    PLAYER([Player])
    P8((8.0 Account Mgmt))
    D1[(D1 Users)]
    D3[(D3 Holdings)]
    D4[(D4 Transactions)]

    PLAYER -->|Settings Changes| P8
    P8 -->|Confirmation| PLAYER
    D1 -->|User Data| P8
    P8 -->|Updated Password| D1
    P8 -->|Clear Holdings| D3
    P8 -->|Archive Transactions| D4
```

### Cross-Process Influence Flows

```mermaid
flowchart LR
    P3((3.0 Trade))
    P5((5.0 Price Calc))
    P6((6.0 Bot Trading))

    P3 -->|Player Trade Influence| P5
    P6 -->|Net Bot Influence| P5
```

---

## Processes

| Process | Description |
|---------|-------------|
| 1.0 Authentication | Handles user registration, login, logout, rate limiting, and session management |
| 2.0 Market Display | Retrieves ore data and price history for market overview and ore detail pages |
| 3.0 Trade Execution | Validates and executes buy/sell orders atomically; records influence for next tick |
| 4.0 Portfolio Management | Calculates and displays user holdings with profit/loss metrics |
| 5.0 Price Calculation | Applies the 8-step algorithm to update ore prices each tick |
| 6.0 Bot Trading | Executes automated bot trades with balance checks and transaction recording |
| 7.0 Leaderboard | Calculates total value (cash + holdings) for all users and ranks them |
| 8.0 Account Management | Handles password changes and account resets |

## Data Stores

| Store | Description |
|-------|-------------|
| D1 Users | User accounts (human and bot) with credentials and balances |
| D2 Ores | Ore definitions with current prices, configuration, and trend logs |
| D3 Holdings | Per-user ore holdings with quantities and average purchase prices |
| D4 Transactions | Complete trade history for all users |
| D5 Price History | Timestamped price records for each ore (used for charting) |

---

## ✔️ Checklist

- [x] All processes numbered (1.0, 2.0, 3.0…)
- [x] All data stores included and labelled
- [x] All external entities match the Context Diagram
- [x] All arrows labelled with meaningful data flows
- [x] Diagram matches the System Flow Diagram
- [x] Diagram renders correctly on GitHub
- [x] File renamed to **DFDLevel1.md**
