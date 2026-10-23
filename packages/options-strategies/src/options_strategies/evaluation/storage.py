"""Versioned JSON and Parquet persistence, without executable pickle payloads."""

import json
import math
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from options_strategies.evaluation.core import EvaluationResult


def _json_value(value):
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _save_raw(result, path, prefix):
    trades = getattr(result, "trade_log", None)
    (trades if trades is not None else pd.DataFrame()).to_parquet(path / f"{prefix}_trades.parquet")
    equity = getattr(result, "equity_curve", None)
    (equity if equity is not None else pd.Series(dtype=float)).rename("equity").to_frame().to_parquet(
        path / f"{prefix}_equity.parquet"
    )
    legs = {}
    for i, (label, leg) in enumerate((getattr(result, "leg_results", None) or {}).items()):
        legs[label] = _save_raw(leg, path, f"{prefix}_{i}")
    return {"prefix": prefix, "summary": _json_value(getattr(result, "summary", {})), "legs": legs}


def _load_raw(path, node):
    prefix = node["prefix"]
    if not prefix.startswith("raw") or any(c not in "raw_0123456789" for c in prefix):
        raise ValueError("Invalid raw result prefix")
    return SimpleNamespace(
        trade_log=pd.read_parquet(path / f"{prefix}_trades.parquet"),
        equity_curve=pd.read_parquet(path / f"{prefix}_equity.parquet")["equity"],
        summary=node["summary"],
        leg_results={label: _load_raw(path, leg) for label, leg in node["legs"].items()},
    )


def save_evaluation(evaluation: EvaluationResult, path: str | Path) -> str:
    """Write a new evaluation directory atomically; never overwrite an existing run."""
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(f"Evaluation directory already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".evaluation-", dir=path.parent) as temp:
        output = Path(temp) / "run"
        output.mkdir()
        for name in ("trades", "ledger", "curves", "summaries", "segments"):
            getattr(evaluation, name).to_parquet(output / f"{name}.parquet", index=False)
        evaluation.stock_prices.rename("close").to_frame().to_parquet(output / "stock_prices.parquet")
        manifest = {
            "schema_version": 1,
            "metadata": evaluation.metadata,
            "raw": _save_raw(evaluation.raw_result, output, "raw"),
        }
        (output / "manifest.json").write_text(
            json.dumps(_json_value(manifest), indent=2, allow_nan=False), encoding="utf-8"
        )
        output.rename(path)
    return str(path)


def load_evaluation(path: str | Path) -> EvaluationResult:
    """Read a supported version of a portable evaluation."""
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported evaluation schema version")
    return EvaluationResult(
        raw_result=_load_raw(path, manifest["raw"]),
        **{
            name: pd.read_parquet(path / f"{name}.parquet")
            for name in ("trades", "ledger", "curves", "summaries", "segments")
        },
        stock_prices=pd.read_parquet(path / "stock_prices.parquet")["close"],
        metadata=manifest["metadata"],
    )
