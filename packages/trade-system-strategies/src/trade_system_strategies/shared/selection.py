"""Option-leg selection helpers shared across strategies.

Pure functions over chain data (strike/delta/price). Both PMCC and backspread use
these to translate a chain slice into concrete :class:`~trade_system_strategies.shared.legs.LegSpec`
instances. Engine-free so they are unit-testable and reusable in research notebooks.

The full short-option selector :func:`select_short_option` ports thetagang's
``OptionChainScanner.find_eligible_contracts`` (trading_operations.py:125) — strike,
DTE, delta, price, and open-interest filters plus the delta-then-DTE sort — operating
on :class:`OptionCandidate` rows instead of live IBKR tickers.
"""

from dataclasses import dataclass
from decimal import Decimal

from trade_system_strategies.shared.greeks import select_by_delta
from trade_system_strategies.shared.legs import LegSpec


def long_leg_by_delta(
    instrument_id: str,
    candidates: list[tuple[Decimal, Decimal]],
    target_delta: Decimal,
    quantity: Decimal,
    tolerance: Decimal | None = None,
) -> LegSpec | None:
    """Build a BUY leg on the candidate closest to ``target_delta``."""
    pick = select_by_delta(candidates, target_delta, tolerance)
    if pick is None:
        return None
    return LegSpec(instrument_id=instrument_id, side="BUY", quantity=quantity)


def short_leg_by_delta(
    instrument_id: str,
    candidates: list[tuple[Decimal, Decimal]],
    target_delta: Decimal,
    quantity: Decimal,
    tolerance: Decimal | None = None,
) -> LegSpec | None:
    """Build a SELL leg on the candidate closest to ``target_delta``."""
    pick = select_by_delta(candidates, target_delta, tolerance)
    if pick is None:
        return None
    return LegSpec(instrument_id=instrument_id, side="SELL", quantity=quantity)


@dataclass(frozen=True)
class OptionCandidate:
    """A single option contract reduced to the fields the selector needs.

    Attributes:
        instrument_id: The option instrument id (e.g. ``"SPY  20240119C420.ARCA"``).
        right: ``"C"`` for calls, ``"P"`` for puts.
        strike: Strike price.
        dte: Days to expiry.
        delta: Model delta (negative for puts); compared by absolute value.
        mid: Mid price (premium).
        open_interest: Open interest for the right (call OI for calls, put OI for puts).

    """

    instrument_id: str
    right: str
    strike: Decimal
    dte: int
    delta: Decimal
    mid: Decimal
    open_interest: int


@dataclass(frozen=True)
class SelectionConfig:
    """Filters and targets driving :func:`select_short_option`.

    Mirrors the thresholds thetagang resolves per symbol/right (config.py:561-806):
    target DTE / max DTE, target delta, minimum open interest, and the strike / price
    gates.

    Attributes:
        right: ``"C"`` or ``"P"``.
        target_dte: Minimum DTE; expirations below this are excluded.
        target_delta: Maximum ``abs(delta)``; higher-delta contracts are excluded.
        max_dte: Optional DTE cap; expirations above this are excluded.
        minimum_open_interest: Minimum open interest (0 disables the filter).
        minimum_price: Minimum mid price (premium) to accept.
        strike_limit: Optional hard strike bound (ceiling for puts, floor for calls).
            When ``None``, puts allow up to ``spot * 1.05`` and calls down to
            ``spot * 0.95`` — the thetagang default 5% OTM/ITM band.
        spot: Underlying price, used for the default strike band and the put
            cost-doesn't-exceed-market check.
        exclude_min_dte: Exclude expirations with DTE below this (forward-only rolls).
        max_expirations: Cap the number of expirations scanned (the nearest N).

    """

    right: str
    target_dte: int
    target_delta: Decimal
    max_dte: int | None = None
    minimum_open_interest: int = 0
    minimum_price: Decimal = Decimal("0")
    strike_limit: Decimal | None = None
    spot: Decimal | None = None
    exclude_min_dte: int = 0
    max_expirations: int | None = None
    delta_mode: str = "below"
    delta_tolerance: Decimal | None = None


def _strike_is_valid(candidate: OptionCandidate, config: SelectionConfig) -> bool:
    """Apply the thetagang strike band (valid_strike, trading_operations.py:165)."""
    right = config.right.upper()
    if right == "P":
        if config.strike_limit is not None:
            return candidate.strike <= config.strike_limit
        if config.spot is not None:
            return candidate.strike <= config.spot * Decimal("1.05")
        return True
    if right == "C":
        if config.strike_limit is not None:
            return candidate.strike >= config.strike_limit
        if config.spot is not None:
            return candidate.strike >= config.spot * Decimal("0.95")
        return True
    return False


def _dte_is_valid(candidate: OptionCandidate, config: SelectionConfig) -> bool:
    """Apply the DTE window: ``target_dte <= dte`` and ``dte <= max_dte``."""
    if candidate.dte < config.target_dte or candidate.dte < config.exclude_min_dte:
        return False
    return config.max_dte is None or candidate.dte <= config.max_dte


def _delta_is_valid(candidate: OptionCandidate, config: SelectionConfig) -> bool:
    """Validate delta per ``config.delta_mode``.

    ``"below"`` (default): ``abs(delta) <= target_delta`` — used for short options.
    ``"near"``: ``abs(abs(delta) - target_delta) <= delta_tolerance`` — used for long
    legs (e.g. LEAPS) where delta should be close to a target, not below it.
    """
    if config.delta_mode == "near":
        if config.delta_tolerance is None:
            return True
        return abs(abs(candidate.delta) - config.target_delta) <= config.delta_tolerance
    # Default "below" mode: abs(delta) <= target_delta.
    return abs(candidate.delta) <= config.target_delta


def _price_is_valid(candidate: OptionCandidate, config: SelectionConfig) -> bool:
    """Apply the minimum-premium and put cost-doesn't-exceed-market checks (:175:262)."""
    if candidate.mid <= config.minimum_price:
        return False
    # A short put's strike should not exceed premium + spot (cost > market).
    return not (
        config.right.upper() == "P" and config.spot is not None and candidate.strike > candidate.mid + config.spot
    )


def _open_interest_is_valid(candidate: OptionCandidate, config: SelectionConfig) -> bool:
    """Apply the open-interest floor (open_interest_is_valid, :175:246)."""
    if config.minimum_open_interest <= 0:
        return True
    return candidate.open_interest >= config.minimum_open_interest


def _sort_candidates(
    candidates: list[OptionCandidate],
    delta_desc: bool,
    config: SelectionConfig | None = None,
) -> list[OptionCandidate]:
    """Sort candidates according to ``config.delta_mode``.

    ``"below"`` (default): sort by ``abs(delta)`` (desc for puts, asc for calls) then
    stable by DTE ascending — yielding the shortest-dated contract with the highest
    acceptable delta for puts, or the lowest delta for calls.

    ``"near"``: sort by ``abs(abs(delta) - target_delta)`` ascending (closest to target
    first) then by DTE ascending — yielding the shortest-dated contract whose delta is
    closest to the target.
    """
    if config is not None and config.delta_mode == "near":
        target = config.target_delta
        return sorted(
            sorted(candidates, key=lambda c: abs(abs(c.delta) - target)),
            key=lambda c: c.dte,
        )
    return sorted(
        sorted(candidates, key=lambda c: abs(c.delta), reverse=delta_desc),
        key=lambda c: c.dte,
    )


def select_short_option(
    candidates: list[OptionCandidate],
    config: SelectionConfig,
    fallback: bool = True,
) -> OptionCandidate | None:
    """Select the best short option contract from a chain.

    Ports thetagang ``find_eligible_contracts`` (trading_operations.py:125). Filters by
    strike band, DTE window, premium, and (when ``minimum_open_interest > 0``) open
    interest; among delta-valid survivors sorts by ``abs(delta)`` (descending for puts)
    then by DTE ascending, and returns the first. If no delta-valid contract survives
    and ``fallback`` is true with a non-zero ``minimum_price``, retries the delta-rejects
    sorted by delta ascending (the thetagang fallback at :175:334).

    Args:
        candidates: Chain candidates as :class:`OptionCandidate` rows.
        config: Filters and targets (see :class:`SelectionConfig`).
        fallback: Whether to fall back to delta-rejected contracts when none are
            delta-valid (thetagang only does this when ``minimum_price != 0``).

    Returns:
        The chosen candidate, or ``None`` if none pass the filters.

    """
    right = config.right.upper()
    delta_desc = right == "P"  # puts: highest delta first; calls: lowest delta first.

    passed: list[OptionCandidate] = []
    delta_rejects: list[OptionCandidate] = []
    for c in candidates:
        if not (_strike_is_valid(c, config) and _dte_is_valid(c, config) and _price_is_valid(c, config)):
            continue
        if _delta_is_valid(c, config):
            passed.append(c)
        else:
            delta_rejects.append(c)

    if config.minimum_open_interest > 0:
        passed = [c for c in passed if _open_interest_is_valid(c, config)]

    if passed:
        ordered = _sort_candidates(passed, delta_desc, config)
    elif fallback and config.minimum_price > 0 and delta_rejects:
        if config.minimum_open_interest > 0:
            delta_rejects = [c for c in delta_rejects if _open_interest_is_valid(c, config)]
        ordered = _sort_candidates(delta_rejects, not delta_desc, config)
    else:
        return None

    if config.max_expirations is not None and len(ordered) > config.max_expirations:
        ordered = ordered[: config.max_expirations]
    return ordered[0] if ordered else None
