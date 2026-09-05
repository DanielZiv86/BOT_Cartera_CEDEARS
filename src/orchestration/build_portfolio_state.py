from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.portfolio.state import (
    load_classification_registry,
    load_portfolio_state,
    positions_frame,
    validate_portfolio_state,
)
from src.risk.portfolio_fit import calculate_portfolio_fit
from src.risk.portfolio_risk import calculate_portfolio_risk
from src.risk.risk_engine import build_return_matrix


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical Portfolio State and portfolio analytics")
    parser.add_argument("--portfolio-state", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--correlations", required=True)
    parser.add_argument("--classification", default="config/portfolio_classification.yml")
    parser.add_argument("--output-dir", default="data/canonical/portfolio")
    args = parser.parse_args()

    payload = load_portfolio_state(args.portfolio_state)
    validation = validate_portfolio_state(payload)
    positions = positions_frame(payload)
    sector_map, factor_map, classification_meta = load_classification_registry(args.classification)

    history = pd.read_parquet(args.history)
    correlation_long = pd.read_parquet(args.correlations)
    return_matrix = build_return_matrix(history)

    portfolio_summary, risk_contrib, sector_exposure, factor_exposure = calculate_portfolio_risk(
        return_matrix=return_matrix,
        positions=positions[["cedear_ticker", "weight"]],
        sector_map=sector_map,
        factor_map=factor_map,
        cash_weight=float(payload["cash_weight"]),
    )

    all_candidates = sorted(set(correlation_long["ticker_a"]).union(correlation_long["ticker_b"]))
    portfolio_fit, portfolio_fit_metrics = calculate_portfolio_fit(
        correlation_matrix_long=correlation_long,
        positions=positions[["cedear_ticker", "weight"]],
        candidates=all_candidates,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    positions.to_json(output_dir / "portfolio_positions.json", orient="records", indent=2, force_ascii=False)
    positions.to_parquet(output_dir / "portfolio_positions.parquet", index=False)
    risk_contrib.to_json(output_dir / "portfolio_risk_contribution.json", orient="records", indent=2, force_ascii=False)
    risk_contrib.to_parquet(output_dir / "portfolio_risk_contribution.parquet", index=False)
    sector_exposure.to_json(output_dir / "portfolio_sector_exposure.json", orient="records", indent=2, force_ascii=False)
    factor_exposure.to_json(output_dir / "portfolio_factor_exposure.json", orient="records", indent=2, force_ascii=False)
    portfolio_fit.to_json(output_dir / "portfolio_fit_quantitative.json", orient="records", indent=2, force_ascii=False)
    portfolio_fit.to_parquet(output_dir / "portfolio_fit_quantitative.parquet", index=False)

    manifest = {
        "engine_version": "1.0",
        "portfolio_state_validation": validation,
        "portfolio_risk": portfolio_summary,
        "portfolio_fit": portfolio_fit_metrics,
        "classification": classification_meta,
        "outputs": [
            "portfolio_positions.json",
            "portfolio_risk_contribution.json",
            "portfolio_sector_exposure.json",
            "portfolio_factor_exposure.json",
            "portfolio_fit_quantitative.json",
        ],
    }
    (output_dir / "portfolio_state_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
