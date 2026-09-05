from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _clip_score(value: float) -> float:
    return round(float(np.clip(value, 0.0, 100.0)), 2)


def calculate_portfolio_fit(
    correlation_matrix_long: pd.DataFrame,
    positions: pd.DataFrame,
    candidates: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    required_corr = {"ticker_a", "ticker_b", "correlation"}
    required_pos = {"cedear_ticker", "weight"}
    if not required_corr.issubset(correlation_matrix_long.columns):
        raise ValueError("correlation matrix long format is incomplete")
    if not required_pos.issubset(positions.columns):
        raise ValueError("positions missing cedear_ticker/weight")

    pos = positions.copy()
    pos["weight"] = pd.to_numeric(pos["weight"], errors="coerce")
    pos = pos.dropna(subset=["cedear_ticker", "weight"])
    pos = pos[pos["weight"] > 0].copy()
    if pos.empty:
        return pd.DataFrame(), {
            "portfolio_fit_status": "BLOCKED_BY_PORTFOLIO_DATA",
            "reason": "NO_POSITIVE_POSITION_WEIGHTS",
        }
    pos["weight"] = pos["weight"] / pos["weight"].sum()
    weights = pos.set_index("cedear_ticker")["weight"].to_dict()
    holdings = set(weights)

    corr = correlation_matrix_long.copy()
    corr["correlation"] = pd.to_numeric(corr["correlation"], errors="coerce")
    universe = sorted(set(corr["ticker_a"]).union(corr["ticker_b"]))
    candidate_list = candidates or [t for t in universe if t not in holdings]

    rows = []
    for candidate in candidate_list:
        subset = corr[(corr["ticker_a"] == candidate) & (corr["ticker_b"].isin(holdings))].copy()
        if subset.empty:
            subset = corr[(corr["ticker_b"] == candidate) & (corr["ticker_a"].isin(holdings))].copy()
            subset["holding"] = subset["ticker_a"]
        else:
            subset["holding"] = subset["ticker_b"]
        subset = subset.dropna(subset=["correlation"])
        if subset.empty:
            rows.append({
                "cedear_ticker": candidate,
                "weighted_avg_corr_to_portfolio": None,
                "max_corr_to_portfolio": None,
                "diversification_score": None,
                "portfolio_fit_status": "BLOCKED_BY_CORRELATION_DATA",
            })
            continue

        subset["holding_weight"] = subset["holding"].map(weights).fillna(0.0)
        covered_weight = float(subset["holding_weight"].sum())
        if covered_weight <= 0:
            weighted_avg = None
        else:
            weighted_avg = float((subset["correlation"] * subset["holding_weight"]).sum() / covered_weight)
        max_corr = float(subset["correlation"].max())

        if weighted_avg is None:
            score = None
            status = "BLOCKED_BY_CORRELATION_DATA"
        else:
            # Weighted portfolio correlation is the primary diversification signal.
            # -0.25 or lower maps to 100; +0.75 or higher maps to 0.
            corr_component = _clip_score((0.75 - weighted_avg) / 1.00 * 100.0)
            # High single-position correlation reduces diversification quality.
            max_component = _clip_score((0.90 - max_corr) / 0.90 * 100.0)
            score = round(0.80 * corr_component + 0.20 * max_component, 2)
            status = "PORTFOLIO_FIT_QUANT_READY" if covered_weight >= 0.95 else "PORTFOLIO_FIT_QUANT_PARTIAL"

        rows.append({
            "cedear_ticker": candidate,
            "weighted_avg_corr_to_portfolio": weighted_avg,
            "max_corr_to_portfolio": max_corr,
            "portfolio_weight_covered": covered_weight,
            "diversification_score": score,
            "portfolio_fit_status": status,
            "methodology_version": "1.0",
        })

    result = pd.DataFrame(rows).sort_values("cedear_ticker").reset_index(drop=True) if rows else pd.DataFrame()
    ready = int((result["portfolio_fit_status"] == "PORTFOLIO_FIT_QUANT_READY").sum()) if not result.empty else 0
    metrics = {
        "portfolio_fit_status": "READY" if not result.empty and ready == len(result) else "PARTIAL_OR_BLOCKED",
        "candidate_count": int(len(result)),
        "ready_count": ready,
        "methodology_version": "1.0",
        "score_basis": "80% weighted-average correlation + 20% maximum holding correlation",
        "note": "Sector/factor concentration penalties are intentionally separate until canonical classifications are available.",
    }
    return result, metrics
