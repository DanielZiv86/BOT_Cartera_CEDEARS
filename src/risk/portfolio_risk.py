from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION_FACTOR = 252


def calculate_portfolio_risk(
    return_matrix: pd.DataFrame,
    positions: pd.DataFrame,
    sector_map: pd.DataFrame | None = None,
    factor_map: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    required = {"cedear_ticker", "weight"}
    missing = sorted(required - set(positions.columns))
    if missing:
        raise ValueError("positions missing columns: " + ", ".join(missing))

    pos = positions.copy()
    pos["weight"] = pd.to_numeric(pos["weight"], errors="coerce")
    pos = pos.dropna(subset=["cedear_ticker", "weight"])
    pos = pos[pos["weight"] > 0].copy()
    if pos.empty:
        return (
            {"portfolio_risk_status": "BLOCKED_BY_PORTFOLIO_DATA", "reason": "NO_POSITIVE_WEIGHTS"},
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        )

    total_weight = float(pos["weight"].sum())
    if total_weight <= 0:
        raise ValueError("portfolio weights sum to zero")
    pos["normalized_weight"] = pos["weight"] / total_weight

    tickers = [t for t in pos["cedear_ticker"] if t in return_matrix.columns]
    if not tickers:
        return (
            {"portfolio_risk_status": "BLOCKED_BY_PORTFOLIO_DATA", "reason": "NO_PORTFOLIO_TICKERS_IN_RETURN_MATRIX"},
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        )

    pos = pos[pos["cedear_ticker"].isin(tickers)].copy()
    pos["normalized_weight"] = pos["weight"] / pos["weight"].sum()
    window = return_matrix[tickers].dropna(how="all").tail(252)
    cov = window.cov(min_periods=60) * ANNUALIZATION_FACTOR
    weights = pos.set_index("cedear_ticker")["normalized_weight"].reindex(tickers).fillna(0.0)

    covariance_matrix = cov.reindex(index=tickers, columns=tickers).fillna(0.0)
    w = weights.to_numpy(dtype=float)
    sigma = covariance_matrix.to_numpy(dtype=float)
    portfolio_var = float(w.T @ sigma @ w)
    portfolio_vol = float(np.sqrt(max(portfolio_var, 0.0)))

    marginal = sigma @ w
    component = w * marginal
    if portfolio_vol > 0:
        contribution = component / portfolio_vol
        contribution_pct = contribution / contribution.sum() if contribution.sum() != 0 else np.zeros_like(contribution)
    else:
        contribution = np.zeros_like(component)
        contribution_pct = np.zeros_like(component)

    contribution_df = pd.DataFrame({
        "cedear_ticker": tickers,
        "weight": w,
        "marginal_variance_contribution": marginal,
        "component_volatility_contribution": contribution,
        "risk_contribution_pct": contribution_pct,
    }).sort_values("risk_contribution_pct", ascending=False).reset_index(drop=True)

    sector_exposure = pd.DataFrame()
    if sector_map is not None and {"cedear_ticker", "sector"}.issubset(sector_map.columns):
        sector_exposure = pos.merge(sector_map[["cedear_ticker", "sector"]], on="cedear_ticker", how="left")
        sector_exposure["sector"] = sector_exposure["sector"].fillna("UNKNOWN")
        sector_exposure = sector_exposure.groupby("sector", as_index=False)["normalized_weight"].sum().rename(columns={"normalized_weight": "weight"}).sort_values("weight", ascending=False)

    factor_exposure = pd.DataFrame()
    if factor_map is not None and {"cedear_ticker", "factor"}.issubset(factor_map.columns):
        factor_exposure = pos.merge(factor_map[["cedear_ticker", "factor"]], on="cedear_ticker", how="left")
        factor_exposure["factor"] = factor_exposure["factor"].fillna("UNKNOWN")
        factor_exposure = factor_exposure.groupby("factor", as_index=False)["normalized_weight"].sum().rename(columns={"normalized_weight": "weight"}).sort_values("weight", ascending=False)

    summary = {
        "portfolio_risk_status": "PORTFOLIO_RISK_READY",
        "portfolio_volatility_annualized": portfolio_vol,
        "position_count": int(len(pos)),
        "weights_normalized": True,
        "weight_sum_input": total_weight,
        "sector_concentration_status": "READY" if not sector_exposure.empty else "BLOCKED_BY_CLASSIFICATION_DATA",
        "factor_concentration_status": "READY" if not factor_exposure.empty else "BLOCKED_BY_CLASSIFICATION_DATA",
    }
    return summary, contribution_df, sector_exposure, factor_exposure
