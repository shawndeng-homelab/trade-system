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

### Status

| Component                        | Status                         |
|----------------------------------|--------------------------------|
| `ibkr.fee.IBKRFeeModel`          | ✅ implemented                  |
| `ibkr.catalog_loader`            | ✅ implemented                  |
| `binance.fee.BinanceFeeModel`    | 🚧 scaffold (`NotImplementedError`) |
| `binance.funding` / `ibkr.financing` / `core.financing` | 🚧 scaffold |

The examples below cover the implemented IBKR pieces.


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

## Usage

### 1. Download IBKR data into the fixed catalog

Requires a running TWS / IB Gateway (see above) and `NAUTILUS_PATH` set.

```python
import asyncio
import datetime as dt

from trade_system_venues.ibkr import catalog_loader as cl


async def main() -> None:
    catalog = cl.default_catalog()  # -> $NAUTILUS_PATH/catalog
    client = await cl.make_client(host="127.0.0.1", port=7497, client_id=5)

    # Stocks / ETFs: instruments + bars
    await cl.download_stock_bars(
        client,
        catalog,
        instrument_ids=["AAPL.NASDAQ", "SPY.ARCA"],
        bar_specifications=["1-DAY-LAST", "1-HOUR-LAST"],
        start=dt.datetime(2024, 1, 1),
        end=dt.datetime(2024, 6, 30),
    )

    # Options: download a chain's instrument definitions
    await cl.download_option_chain(
        client,
        catalog,
        underlying="SPY",
        primary_exchange="ARCA",
        min_expiry_days=7,
        max_expiry_days=30,
    )


asyncio.run(main())
```

### 2. Backtest with `IBKRFeeModel` (low-level API)

Attach the fee model directly to the venue on a `BacktestEngine`:

```python
from trade_system_venues.ibkr.fee import IBKRFeeModel
from trade_system_venues.ibkr.fee import IBKRFeeModelConfig

engine.add_venue(
    venue=Venue("NASDAQ"),
    oms_type=OmsType.NETTING,
    account_type=AccountType.MARGIN,
    starting_balances=[Money(1_000_000, USD)],
    base_currency=USD,
    fee_model=IBKRFeeModel(IBKRFeeModelConfig(pricing="tiered")),
)
```

### 3. Backtest with `IBKRFeeModel` (high-level API)

Reference the model by path so `BacktestNode` / `FeeModelFactory` build it from config:

```python
from nautilus_trader.backtest.config import BacktestVenueConfig
from nautilus_trader.config import ImportableFeeModelConfig

venue = BacktestVenueConfig(
    name="NASDAQ",
    oms_type="NETTING",
    account_type="MARGIN",
    base_currency="USD",
    starting_balances=["1_000_000 USD"],
    fee_model=ImportableFeeModelConfig(
        fee_model_path="trade_system_venues.ibkr.fee:IBKRFeeModel",
        config_path="trade_system_venues.ibkr.fee:IBKRFeeModelConfig",
        config={"pricing": "fixed"},  # or "tiered"; optional asset_class override
    ),
)
```

Then point `BacktestDataConfig(catalog_path=..., ...)` at the same catalog you downloaded
into, and the fee model prices every fill.


