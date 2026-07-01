# trade-system-venues

Venue-specific fee and financing models for [NautilusTrader](https://nautilustrader.io),
covering commissions and periodic funding/financing costs that the core platform does
not settle out of the box.

## Scope

| Venue   | Fee model                                             | Periodic cost                                   |
|---------|-------------------------------------------------------|-------------------------------------------------|
| Binance | maker/taker tiered %, BNB discount, spot/USDⓈ/COIN-M  | funding rate settlement (8h)                    |
| IBKR    | per-share/contract + min/cap, tiered **and** fixed    | margin interest + short-borrow fees (daily)     |

Fee models subclass `nautilus_trader.backtest.models.FeeModel` and plug into
`BacktestEngine.add_venue(fee_model=...)`. Periodic costs are settled by a shared
`FinancingSettlementActor` that tracks cashflows in an independent ledger (it does not
mutate account balances).

## Layout

- `core/` — venue-agnostic abstractions (`FinancingSettlementActor`, schedule helpers).
- `binance/` — Binance fee model, funding settlement, funding-data plumbing.
- `ibkr/` — IBKR fee model (per asset class), margin-interest / borrow-fee financing.
