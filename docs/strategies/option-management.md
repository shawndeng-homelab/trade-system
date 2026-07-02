# Option management: selection & roll/close

The `trade-system-strategies` package separates a theta-gang strategy into three
concerns: **which contract to sell** (selection), **what to do with an open short**
(roll/close), and **how to submit and reconcile legs** (the `LegGroup` state machine).
The first two are pure, engine-free functions in `shared.selection` and
`shared.management`, ported from [thetagang](https://github.com/brndnmtthws/thetagang)'s
live IBKR bot. This document explains how they decide.

Both modules are deliberately decoupled from NautilusTrader and from `ib_async`:
thetagang's originals are `async` only because they fetch a live ticker to test
in-the-money. Here ITM, deltas, prices, and open interest are **inputs**, so every
decision is deterministic, unit-testable, and reusable identically in a backtest and
in a Jupyter notebook.

---

## 1. Selection — `shared.selection.select_short_option`

`select_short_option(candidates, config)` picks the single best short option to write
or roll to, from a chain reduced to `OptionCandidate` rows
`(instrument_id, right, strike, dte, delta, mid, open_interest)`. It ports thetagang's
`OptionChainScanner.find_eligible_contracts` (`trading_operations.py:125`).

### The filter pipeline

Each candidate passes through four gates in order; any failure drops it:

| Gate | Rule | Source |
|------|------|--------|
| **Strike band** | Put: `strike ≤ strike_limit` (or `spot × 1.05` if no limit). Call: `strike ≥ strike_limit` (or `spot × 0.95`). | `valid_strike` |
| **DTE window** | `target_dte ≤ dte ≤ max_dte`, and `dte ≥ exclude_min_dte` (forward-only rolls). | `option_dte` filter |
| **Premium** | `mid > minimum_price`; for puts also `strike ≤ mid + spot` (cost mustn't exceed market). | `price_is_valid` |
| **Delta** | `abs(delta) ≤ target_delta`. | `delta_is_valid` |

After the gates, survivors are filtered by **open interest** (`open_interest ≥ minimum_open_interest`, disabled when 0).

### The sort — "shortest-dated, highest-acceptable-delta"

Survivors are sorted in two stable passes:

1. **Inner sort** by `abs(delta)`: **descending for puts** (deepest acceptable put
   first), **ascending for calls** (cheapest acceptable call first).
2. **Outer stable sort** by `dte` ascending.

Because the outer sort is stable, within each DTE the delta ordering is preserved, so
the **first** element is the *nearest expiry* with the *highest acceptable delta* (puts)
or *lowest acceptable delta* (calls). This matches thetagang's preference: sell the
shortest-dated option that still meets the delta target — fastest theta decay.

### The fallback path

If **no** candidate passes the delta gate but `minimum_price > 0` and `fallback=True`,
the delta-rejected candidates are retried, sorted by `abs(delta)` **ascending** (least
aggressive of the over-delta group). thetagang does this only when a minimum credit is
required — it would rather sell a slightly-too-delta option for adequate premium than
sell nothing. With `minimum_price == 0` there is no fallback: return `None`.

### `SelectionConfig` at a glance

```python
SelectionConfig(
    right="P",                 # "C" or "P"
    target_dte=7,              # min DTE
    target_delta=Decimal("0.30"),  # max abs(delta)
    max_dte=30,                # optional DTE cap
    minimum_open_interest=100, # 0 disables
    minimum_price=Decimal("0.05"),
    strike_limit=Decimal("395"),  # optional hard bound
    spot=Decimal("400"),          # for default band + put cost check
    exclude_min_dte=0,            # forward-only roll floor
    max_expirations=3,            # scan nearest N expiries
)
```

---

## 2. Roll / close — `shared.management`

Once a short is open, two questions recur each cycle: **roll it** (close + open a
farther-dated replacement) or **close it** (take profit and exit). `should_roll` and
`should_close` answer these from a `PositionSnapshot` and a `RollWhenConfig`.

### `PositionSnapshot`

A short option reduced to what the rules need: `symbol, right, strike, spot, dte, pnl,
itm, has_excess`. `pnl` is the fraction of max profit captured (0.0–1.0+). `itm` is
optional — when `None` it is derived: **call ITM iff `strike ≤ spot`**, **put ITM iff
`strike ≥ spot`**.

### The roll decision tree

`should_roll(position, config)` applies this order (put and call symmetric; the
per-leg config `RollWhenLegConfig` differs by default — calls `itm=True`, puts
`itm=False`, because the wheel *lets ITM puts assign* to acquire stock but *rolls ITM
covered calls*):

| # | Condition | Result |
|---|-----------|--------|
| 1 | `always_when_itm` and ITM | **roll** (force, overrides everything including `max_dte`) |
| 2 | `itm == False` and ITM | **do not roll** (let it assign / hold) |
| 3 | `has_excess` and leg `has_excess == False` | **do not roll** (symbol is overweight) |
| 4 | `max_dte` set and `dte > max_dte` | **do not roll** (too far from expiry) |
| 5 | `dte ≤ roll_dte` and `pnl ≥ min_pnl` | **roll** (DTE trigger — near expiry, profitable enough) |
| 6 | `pnl ≥ roll_pnl` | **roll** (profit trigger — captured enough premium regardless of DTE) |

Rules 5 and 6 are the two independent roll triggers: roll either because expiry is
close *and* you've banked `min_pnl`, or because you've hit the profit target early
(`roll_pnl`, e.g. 50%) and want to lock it in.

### The close decision

`should_close(position, config)` is simpler: when `close_at_pnl` is truthy (default
`1.0` = 100%) and `pnl > close_at_pnl`, close for profit. Equality is *not* enough —
close requires strictly exceeding the threshold. A falsy `close_at_pnl` (e.g. `0`)
disables closing entirely.

### Roll strike floor / ceiling

When rolling, the *new* leg's strike must respect the existing position so the roll
doesn't lose money or move the wrong way. Two helpers compute the bound:

- **`next_roll_strike_for_call`** — a **floor**: the new covered-call strike cannot fall
  below the stock cost basis, and under `maintain_high_water_mark` cannot fall below the
  prior short strike (roll calls *up*, never down).
- **`next_roll_strike_for_put`** — a **ceiling**: when the short put is ITM, the new
  strike is capped at the prior strike (don't roll further ITM); an explicit
  `strike_limit` also caps it.

These bounds feed back into `SelectionConfig.strike_limit` for the replacement leg's
`select_short_option` call — closing the loop between the two modules.

### `RollWhenConfig` at a glance

```python
RollWhenConfig(
    dte=7,                      # DTE trigger
    pnl=Decimal("0.5"),         # profit trigger (50%)
    min_pnl=Decimal("0.0"),     # min profit for the DTE trigger
    close_at_pnl=Decimal("1.0"),# close at 100%
    close_if_unable_to_roll=False,
    max_dte=None,               # never roll past this DTE
    calls=RollWhenLegConfig(itm=True),   # roll ITM calls
    puts=RollWhenLegConfig(itm=False),   # let ITM puts assign
)
```

---

## How they fit together

A wheel cycle wires both modules:

1. **Enter**: `select_short_option(chain, SelectionConfig(...))` → chosen contract →
   submit a SELL leg → `LegGroup.apply_fill` on `on_order_filled`.
2. **Manage** (each bar): build a `PositionSnapshot` from the open short, then:
   - `should_close(...)` → close for profit, or
   - `should_roll(...)` → compute the strike bound via `next_roll_strike_for_*`, feed
     it as `strike_limit` into a new `SelectionConfig`, `select_short_option` the
     replacement, and submit the close+open legs.

Both decisions are pure: the same `PositionSnapshot` + `RollWhenConfig` in a notebook
yields the same roll/close verdict as in the backtest. That is the point of porting
thetagang's logic out of its `async`/IBKR-coupled engine — the *policy* is now
inspectable and reproducible, while the *execution* (order submission, fill
reconciliation) stays in the NautilusTrader strategy layer.

---

## Porting notes

- **Defaults mirror thetagang**: calls roll when ITM (`itm=True`), puts do not
  (`itm=False`); `close_at_pnl` defaults to 100%; the strike band defaults to ±5%.
- **Not modelled here**: the `credit_only` roll constraint and the BAG-combo order
  construction (live-only in thetagang) — `credit_only` is a property on
  `RollWhenLegConfig` for the order layer to read; the roll *order* is built by the
  NautilusTrader strategy using `LegGroup`.
- **American exercise**: thetagang prices greeks European-style; this port inherits
  that approximation for the ITM test. Deep-ITM LEAPS early-exercise risk is not
  captured.
