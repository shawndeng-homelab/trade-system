"""Evaluate cached PMCC data and export a portable research report."""

import argparse
from datetime import UTC
from datetime import datetime
from pathlib import Path

from backtest_charts import BacktestReport
from options_strategies.evaluation import evaluate_pmcc
from options_strategies.pmcc import PmccConfig
from options_strategies.shared import load_pmcc_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = PmccConfig(symbol=args.symbol, capital=args.capital, start_date=args.start_date, end_date=args.end_date)
    options, stock = load_pmcc_data(config.symbol, config.start_date, config.end_date, config.expiration_type)
    evaluation = evaluate_pmcc(options, stock, config)
    output = args.output or Path(".tmp/evaluations") / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    evaluation.save(output)
    report = BacktestReport.from_evaluation(evaluation)
    report.save_html(str(output / "report.html"))
    report.export_trades(output / "trades.csv")
    print(
        evaluation.summaries[["scenario", "strategy", "gross_pnl", "commission", "slippage", "net_pnl"]].to_string(
            index=False
        )
    )
    print(f"Report: {(output / 'report.html').resolve()}")
    print("Fixed-fill research only; open positions are not valued. See report assumptions.")


if __name__ == "__main__":
    main()
