# 🌲 Decision Tree — OreX

A **Decision Tree** showing the branching logic and outcomes
for key decision points in the OreX system.

---

## Decision Tree — Trade Execution (Buy)

```mermaid
flowchart TD
    Q1{Is the user authenticated?}
    Q1 -->|No| A1[Redirect to Login Page]
    Q1 -->|Yes| Q2{Is quantity a positive integer?}
    Q2 -->|No| A2[Display validation error]
    Q2 -->|Yes| Q3{Does user have sufficient balance?}
    Q3 -->|No| A3[Display insufficient funds error]
    Q3 -->|Yes| Q4{Has user confirmed the trade?}
    Q4 -->|No| A4[Display confirmation page]
    Q4 -->|Yes| Q5{Database write successful?}
    Q5 -->|No| A5[Rollback transaction and display error]
    Q5 -->|Yes| A6[Deduct balance, update holdings, record transaction, redirect to portfolio]
```

---

## Decision Tree — Trade Execution (Sell)

```mermaid
flowchart TD
    Q1{Is the user authenticated?}
    Q1 -->|No| A1[Redirect to Login Page]
    Q1 -->|Yes| Q2{Is quantity a positive integer?}
    Q2 -->|No| A2[Display validation error]
    Q2 -->|Yes| Q3{Does user hold enough of this ore?}
    Q3 -->|No| A3[Display insufficient holdings error]
    Q3 -->|Yes| Q4{Has user confirmed the trade?}
    Q4 -->|No| A4[Display confirmation page]
    Q4 -->|Yes| Q5{Database write successful?}
    Q5 -->|No| A5[Rollback transaction and display error]
    Q5 -->|Yes| A6[Credit balance, reduce holdings, record transaction, redirect to portfolio]
```

---

## Decision Tree — User Login

```mermaid
flowchart TD
    Q1{Is the user already authenticated?}
    Q1 -->|Yes| A1[Redirect to Dashboard]
    Q1 -->|No| Q2{Is the IP rate-limited?}
    Q2 -->|Yes| A2[Display rate limit error]
    Q2 -->|No| Q3{Are username and password provided?}
    Q3 -->|No| A3[Display missing fields error]
    Q3 -->|Yes| Q4{Do credentials match a user record?}
    Q4 -->|No| A4[Record failed attempt and display invalid credentials error]
    Q4 -->|Yes| A5[Create session, update last_login, redirect to Dashboard]
```

---

## Decision Tree — User Registration

```mermaid
flowchart TD
    Q1{Is username 3-20 chars, alphanumeric/underscore?}
    Q1 -->|No| A1[Display username validation error]
    Q1 -->|Yes| Q2{Is password at least 8 characters?}
    Q2 -->|No| A2[Display password too short error]
    Q2 -->|Yes| Q3{Does confirm password match?}
    Q3 -->|No| A3[Display passwords do not match error]
    Q3 -->|Yes| Q4{Is username already taken?}
    Q4 -->|Yes| A4[Display duplicate username error]
    Q4 -->|No| A5[Create account with $10,000 balance, auto-login, redirect to Dashboard]
```

---

## Decision Tree — Market Engine Tick (Per Ore)

```mermaid
flowchart TD
    Q1{Market event triggered? — 0.5% chance}
    Q1 -->|Yes| A1[Apply 3x multiplier to price change]
    Q1 -->|No| A2[Use standard price change]
    A1 --> Q2{Weighted random decision?}
    A2 --> Q2
    Q2 -->|Rise| A3[Add price change to current price]
    Q2 -->|Hold| A4[Price unchanged]
    Q2 -->|Fall| A5[Subtract price change from current price]
    A3 --> Q3{New price above ceiling?}
    A4 --> Q4[Update trend log and persist]
    A5 --> Q5{New price below floor?}
    Q3 -->|Yes| A6[Clamp to ceiling]
    Q3 -->|No| Q4
    Q5 -->|Yes| A7[Clamp to floor]
    Q5 -->|No| Q4
    A6 --> Q4
    A7 --> Q4
```

---

## ✔️ Checklist

- [x] All decisions included
- [x] All outcomes shown
- [x] Branches labelled clearly
- [x] Matches program logic
- [x] File renamed to **DecisionTree.md**
