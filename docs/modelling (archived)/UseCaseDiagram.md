# 🎭 Use Case Diagram — OreX

A **Use Case Diagram** showing the actors, use cases, and interactions
within the OreX system.

---

## Use Case Diagram

```mermaid
flowchart LR
    VISITOR(["Visitor"])

    subgraph SYS1[" OreX "]
        direction TB
        UC1["UC1: Register"]
        UC2["UC2: Log In"]
        UC14["UC14: About"]
        UC15["UC15: Help"]
    end

    VISITOR --- UC1
    VISITOR --- UC2
    VISITOR --- UC14
    VISITOR --- UC15
```

```mermaid
flowchart LR
    PLAYER(["Player"])

    subgraph SYS2[" OreX "]
        direction TB
        UC3["UC3: Log Out"]
        UC4["UC4: Market"]
        UC5["UC5: Ore Detail"]
        UC6["UC6: Buy"]
        UC7["UC7: Sell"]
        UC8["UC8: Portfolio"]
        UC9["UC9: Dashboard"]
        UC10["UC10: Leaderboard"]
        UC11["UC11: History"]
        UC12["UC12: Password"]
        UC13["UC13: Reset"]
        UC18["UC18: Sort Market Ores"]
        UC19["UC19: Change Theme"]
    end

    PLAYER --- UC3
    PLAYER --- UC4
    PLAYER --- UC5
    PLAYER --- UC6
    PLAYER --- UC7
    PLAYER --- UC8
    PLAYER --- UC9
    PLAYER --- UC10
    PLAYER --- UC11
    PLAYER --- UC12
    PLAYER --- UC13
    PLAYER --- UC18
    PLAYER --- UC19
```

```mermaid
flowchart LR
    BOT(["Bot Trader"])
    ENGINE(["Market Engine"])

    subgraph SYS3[" OreX "]
        direction TB
        UC16["UC16: Bot Trades"]
        UC17["UC17: Update Prices"]
    end

    BOT --- UC16
    ENGINE --- UC17
    ENGINE --- UC16
```

---

## Use Case Descriptions

| ID | Use Case | Description |
|----|----------|-------------|
| UC1 | Register | Create a new account with username and password |
| UC2 | Log In | Authenticate with credentials to access the system |
| UC3 | Log Out | End the current session |
| UC4 | Market | Browse all ores and their current prices |
| UC5 | Ore Detail | View a single ore's price chart and statistics |
| UC6 | Buy | Purchase a quantity of ore at market price |
| UC7 | Sell | Sell a held quantity of ore at market price |
| UC8 | Portfolio | View all holdings with profit/loss |
| UC9 | Dashboard | View at-a-glance summary of portfolio and market |
| UC10 | Leaderboard | View ranked list of all players by total value |
| UC11 | History | View paginated transaction history |
| UC12 | Password | Change account password |
| UC13 | Reset | Reset account to starting state |
| UC14 | About | View how OreX works |
| UC15 | Help | View FAQ and usage guidance |
| UC16 | Bot Trades | Execute automated buy/sell decisions each tick |
| UC17 | Update Prices | Recalculate ore prices using the 8-step algorithm |
| UC18 | Sort Market Ores | Use the sort control on the market page to reorder ore cards by trend (Rising/Falling), reset to Default server order, or drag-and-drop to create a Custom arrangement. Includes selecting sort mode from dropdown, drag-and-drop reorder, persistence via localStorage, and re-application after HTMX refresh |
| UC19 | Change Theme | Select a colour theme (Light/Dark/System) from the settings page Appearance section. Includes immediate application via CSS custom properties, persistence via localStorage, FOUC prevention on page load, and live OS preference tracking in System mode |

---

## Actors

| Actor | Description |
|-------|-------------|
| Visitor | An unauthenticated user who can register, log in, and view public pages |
| Player | An authenticated human user who can trade, view portfolio, and manage their account |
| Bot Trader | An automated AI account that executes trades each market tick |
| Market Engine | The background process that updates ore prices every 20 seconds |

---

## ✔️ Checklist

- [x] System boundary correct
- [x] All actors included
- [x] All use cases included
- [x] Associations correct
- [x] File renamed to **UseCaseDiagram.md**
