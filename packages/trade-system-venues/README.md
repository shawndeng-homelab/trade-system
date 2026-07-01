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

## Environment

| Variable       | Used by                                              | Meaning                                                                                                   |
|----------------|------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `NAUTILUS_PATH` | `ibkr.catalog_loader.default_catalog()` / `ParquetDataCatalog.from_env()` | Root of the shared data store. The catalog resolves to `$NAUTILUS_PATH/catalog`. Set it once so downloads and backtests share the same fixed location. |

Example (Windows PowerShell):

```powershell
$env:NAUTILUS_PATH = "E:\trade-data"   # catalog lives in E:\trade-data\catalog
```

Example (bash):

```bash
export NAUTILUS_PATH=/data/trade-data  # catalog lives in /data/trade-data/catalog
```

### IBKR data downloads (runtime)

`ibkr.catalog_loader` connects to Interactive Brokers to pull historical data. It needs:

- A running **TWS** or **IB Gateway** reachable at the `host`/`port` passed to
  `make_client(...)` (these are function arguments, not environment variables) —
  e.g. `7497` paper TWS, `7496` live TWS, `4001`/`4002` gateway.
- The IBKR support extra, installed automatically via the `nautilus-trader[ib]`
  dependency (bundles `nautilus-ibapi`, `protobuf`, `defusedxml`).
- Appropriate IBKR market-data permissions for the instruments requested (delayed data
  is usually sufficient for backtests; historical **options** data is often sparse).

