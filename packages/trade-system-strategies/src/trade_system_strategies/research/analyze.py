"""Exploratory analysis helpers for Jupyter research.

Engine-free conveniences that turn catalog data into Polars DataFrames for inspection
and plotting. Mirrors the selection logic used in backtests so a notebook validates the
exact legs a strategy would trade.
"""



from decimal import Decimal

import polars as pl

from trade_system_strategies.shared.greeks import select_by_delta


def chain_to_dataframe(strikes: list, deltas: list) -> pl.DataFrame:
    """Build a Polars DataFrame of ``(strike, delta, abs_delta)`` from chain data."""
    return pl.DataFrame({"strike": strikes, "delta": deltas}).with_columns(
        pl.col("delta").abs().alias("abs_delta"),
    )


def nearest_delta_row(frame: pl.DataFrame, target_delta: float) -> pl.DataFrame | None:
    """Return the single chain row whose ``abs_delta`` is closest to ``target_delta``."""
    if frame.is_empty():
        return None
    return frame.sort((pl.col("abs_delta") - target_delta).abs()).head(1)


def select_leg_summary(
    candidates: list[tuple[float, float]],
    targets: list[float],
) -> pl.DataFrame:
    """For each target delta, report the closest candidate strike/delta.

    Args:
        candidates: ``(strike, delta)`` pairs from a chain.
        targets: Absolute delta targets to evaluate (e.g. ``[0.8, 0.3]``).

    Returns:
        A Polars DataFrame with one row per target.

    """
    rows = []
    for target in targets:
        pick = select_by_delta(
            [(Decimal(str(s)), Decimal(str(d))) for s, d in candidates],
            Decimal(str(target)),
        )
        if pick is None:
            rows.append({"target_delta": target, "strike": None, "delta": None})
        else:
            rows.append({"target_delta": target, "strike": float(pick[0]), "delta": float(pick[1])})
    return pl.DataFrame(rows)
