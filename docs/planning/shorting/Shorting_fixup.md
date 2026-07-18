# Shorting System Fixup

## Root Cause

The spec (requirements.md, design.md) incorrectly defined `Total_Locked_Collateral` as:

```
Total_Locked_Collateral = Short_Value × Collateral_Multiplier
```

But the original plan (`docs/planning/OreX Shorting Plans.md`) defines it as:

```
Total_Locked_Collateral = Short_Value + (Short_Value × Collateral_Multiplier)
                        = Short_Value × (1 + Collateral_Multiplier)
```

The missing `Short_Value` component represents the **synthetic short sale proceeds** — the "borrowed" shares sold at market price. Without it, the close formula `Locked - Buyback` can never produce a meaningful profit when prices drop.

Additionally, the spec introduced **surplus release** (Requirement 3.4) which is NOT in the original plan. The plan only describes one-directional margin calls (pulling FROM FreeCash when price rises). It never releases collateral back when price drops — the vault only grows.

---

## Where the spec went wrong

| Location | What it says | What it should say |
|---|---|---|
| **requirements.md Req 2.3** | `Total_Locked_Collateral = (Shares × Price) × Multiplier` | `Total_Locked_Collateral = (Shares × Price) × (1 + Multiplier)` |
| **requirements.md Req 2.5** | "deduct Total_Locked_Collateral from FreeCash" | "deduct Player_Margin (= Short_Value × Multiplier) from FreeCash" — vault is LARGER than what player pays |
| **requirements.md Req 3.4** | "release surplus from Locked_Collateral back to FreeCash" | **DELETE THIS** — no surplus release, collateral only grows |
| **design.md Collateral formula** | `Total_Locked_Collateral = (shares × price) × Collateral_Multiplier` | `Total_Locked_Collateral = (shares × price) × (1 + Collateral_Multiplier)` |
| **design.md Property 4** | "Conservation of money: FreeCash + Locked stays constant through rebalancing" | Only applies to deficit direction (margin calls). No surplus release. |

---

## Step-by-step comparison: Opening a short

**Example:** Player has $200,000. Shorts 1000 shares of Coal at $100/share. Multiplier = 0.5. No crowding.

### Current (broken) code

File: `src/app/market/shorting.py` line 75

```python
def _calculate_total_locked_collateral(shares, price, collateral_multiplier):
    position_size = shares * price
    return round(position_size * collateral_multiplier, 2)
```

Result: `1000 × $100 × 0.5 = $50,000` locked. Player pays $50,000.

File: `src/app/routes/trade.py` ~line 475

```python
new_balance = user.balance - locked_collateral  # deducts $50,000
```

DB record: `locked_collateral = $50,000`

### Desired code

```python
def _calculate_total_locked_collateral(shares, price, collateral_multiplier):
    """Vault = Short_Value + Margin = Short_Value × (1 + Multiplier)"""
    short_value = shares * price
    return round(short_value * (1 + collateral_multiplier), 2)

def _calculate_player_margin(shares, price, collateral_multiplier):
    """What the player actually pays from FreeCash = Short_Value × Multiplier"""
    short_value = shares * price
    return round(short_value * collateral_multiplier, 2)
```

Result: Vault = `1000 × $100 × 1.5 = $150,000`. Player pays only margin = `1000 × $100 × 0.5 = $50,000`.

Trade route change:
```python
player_margin = _calculate_player_margin(quantity, current_price, collateral_multiplier)
locked_collateral = _calculate_total_locked_collateral(quantity, current_price, collateral_multiplier)

# Player only pays the margin from FreeCash
new_balance = user.balance - player_margin

# But the vault stores the full amount (proceeds + margin)
db.execute("""INSERT INTO short_positions (..., locked_collateral) VALUES (..., ?)""",
           (..., locked_collateral))
```

---

## Step-by-step comparison: Per-tick margin rebalancing (price RISES)

**Example:** Price rises from $100 to $150. Shares = 1000. Multiplier = 0.5.

### Current (broken) code

File: `src/app/market/shorting.py` `_rebalance_margin`

```python
# Recalculates required as: new_short_value × multiplier
required_collateral = _calculate_total_locked_collateral(shares, current_price, multiplier)
# = 1000 × 150 × 0.5 = $75,000

# Deficit = required - locked = $75,000 - $50,000 = $25,000
# Pulls $25,000 from FreeCash into Locked
```

### Desired code

```python
# Recalculates required as: new_short_value × (1 + multiplier)
required_collateral = _calculate_total_locked_collateral(shares, current_price, multiplier)
# = 1000 × 150 × 1.5 = $225,000

# Deficit = required - locked = $225,000 - $150,000 = $75,000
# Pulls $75,000 from FreeCash into Locked
```

This is larger, which makes sense — as price rises, the vault needs more to cover the increased buyback cost.

---

## Step-by-step comparison: Per-tick margin rebalancing (price DROPS)

**Example:** Price drops from $100 to $50. Shares = 1000. Multiplier = 0.5.

### Current (broken) code

```python
required_collateral = 1000 × 50 × 0.5 = $25,000
# Surplus = locked ($50,000) - required ($25,000) = $25,000
# Releases $25,000 back to FreeCash ← THIS IS THE BUG
```

### Desired code

```python
# NO SURPLUS RELEASE. Locked stays at $150,000.
# The "required" is lower but we don't release the difference.
# The vault only grows, never shrinks.
# When price drops, the player profits at close time, not during the tick.

# Simply: skip the elif branch entirely
if required_collateral > locked_collateral:
    # Pull deficit from FreeCash (margin call)
    ...
# else: do nothing — vault stays frozen
```

---

## Step-by-step comparison: Closing (price DROPPED — profitable)

**Example:** Opened at $100, price now $50. Shares = 1000. Vault = $150,000 (unchanged — no surplus release).

### Current (broken) code

```python
short_value = shares * current_price  # 1000 × 50 = $50,000
pnl = locked_collateral - short_value  # $25,000 - $50,000 = -$25,000 (LOSS!)
# Because surplus release already shrunk locked to $25,000
```

### Desired code

```python
short_value = shares * current_price  # 1000 × 50 = $50,000
pnl = locked_collateral - short_value  # $150,000 - $50,000 = $100,000 returned to FreeCash

# Player originally paid $50,000 margin. Gets back $100,000.
# Net profit = $100,000 - $50,000 = $50,000 ✓
```

---

## Step-by-step comparison: Closing (price ROSE — unprofitable)

**Example:** Opened at $100, price now $150. Shares = 1000. Vault grew via margin calls.

After margin call: vault = $225,000 (deficit of $75,000 was pulled from FreeCash).

### Current code (same logic, just different numbers)

```python
short_value = 1000 × 150 = $150,000
pnl = locked ($225,000) - short_value ($150,000) = $75,000 returned
```

But player lost $75,000 via margin calls already. So:
- Margin paid at open: $50,000
- Margin call: $75,000
- Total spent: $125,000
- Returned at close: $75,000
- Net loss: $125,000 - $75,000 = $50,000

### Desired code (same — this part is correct)

Identical math. The loss comes from margin calls draining FreeCash during the life of the position.

---

## Step-by-step comparison: Forced liquidation (FreeCash hits $0)

**Scenario:** Price keeps rising, margin calls drain FreeCash to $0.

### Current and Desired (same logic)

When FreeCash = $0 and another margin call is needed:
1. Transfer all remaining FreeCash to vault
2. Close the position: return `vault - buyback` to FreeCash

At this point vault ≈ buyback cost (since we just topped up), so return ≈ $0. Player lost their entire margin + all margin calls.

This is correct in both implementations. The "fuse burned out."

---

## Summary of code changes needed

### 1. `_calculate_total_locked_collateral` — change formula
- From: `short_value × multiplier`
- To: `short_value × (1 + multiplier)`

### 2. Add `_calculate_player_margin` function
- Formula: `short_value × multiplier` (what the player pays from FreeCash)

### 3. `short_open` route — deduct margin, not full vault
- Player pays: `_calculate_player_margin(...)` from FreeCash
- DB stores: `_calculate_total_locked_collateral(...)` as locked_collateral

### 4. `_rebalance_margin` — remove surplus release
- Delete the `elif required_collateral < locked_collateral` branch entirely
- Vault only grows, never shrinks

### 5. `short_preview` route — update UI to show both margin cost and vault size
- "You pay" = margin
- "Vault (total locked)" = full collateral
- Insufficient funds check: against margin, not vault

### 6. `short_confirm.html` — show margin deducted, not vault
- "Balance after" = balance - margin

### 7. Update preview and confirmation text
- Make clear the player only pays the margin portion
- The vault size is informational (shows protection level)

### 8. Flash message at close — already fixed to show true net P/L

---

## What to NOT change (keep as-is)

- Fee calculation (based on Short_Value, not vault)
- SL/TP trigger logic
- Forced liquidation logic (margin call → FreeCash = 0 → liquidate)
- The `_close_position` formula: `balance += locked - short_value` (this is correct once vault is properly sized)
- Bot shorting logic (will use the corrected functions)
- Net worth formula: `FreeCash + Longs + (Locked - Short_Value)` (correct — just Locked is now bigger)

---

## Verification after fix

With the fix, using our original example:
- Player: $200,000. Short 1000 shares at $100. Multiplier 0.5.
- Margin (player pays): $50,000. Vault: $150,000.
- FreeCash after open: $150,000.
- Price drops to $50: NO surplus release. Vault stays $150,000.
- Close: vault ($150,000) - buyback ($50,000) = $100,000 returned.
- FreeCash: $150,000 + $100,000 = $250,000.
- Net: started $200,000, ended $250,000. **Profit = $50,000** ✓
