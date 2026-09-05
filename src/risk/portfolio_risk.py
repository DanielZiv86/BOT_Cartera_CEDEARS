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
    cash_weight: float = 0.0,
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

    risky_weight_input = float(pos["weight"].sum())
    total_weight_input = risky_weight_input + float(cash_weight)
    if not np.isfinite(total_weight_input) or abs(total_weight_input - 1.0) > 0.01:
        raise ValueError(f"portfolio weights must sum to ~1.0 including cash; got {total_weight_input:.8f}")

    tickers = [t for t in pos["cedear_ticker"] if t in return_matrix.columns]
    if len(tickers) != len(pos):
        missing_tickers = sorted(set(pos["cedear_ticker"]) - set(tickers))
        return (
            {
                "portfolio_risk_status": "BLOCKED_BY_PORTFOLIO_DATA",
                "reason": "PORTFOLIO_TICKERS_MISSING_FROM_RETURN_MATRIX",
                "missing_tickers": missing_tickers,
            },
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        )

    window = return_matrix[tickers].dropna(how="all").tail(252)
    cov = window.cov(min_periods=60) * ANNUALIZATION_FACTOR
    covariance_matrix = cov.reindex(index=tickers, columns=tickers)
    if covariance_matrix.isna().any().any():
        return (
            {"portfolio_risk_status": "BLOCKED_BY_RISK_DATA", "reason": "INCOMPLETE_COVARIANCE_MATRIX"},
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        )

    actual_weights = pos.set_index("cedear_ticker")["weight"].reindex(tickers).astype(float)
    risky_sleeve_weights = actual_weights / actual_weights.sum()

    sigma = covariance_matrix.to_numpy(dtype=float)
    w_total = actual_weights.to_numpy(dtype=float)
    w_sleeve = risky_sleeve_weights.to_numpy(dtype=float)

    portfolio_var = float(w_total.T @ sigma @ w_total)
    risky_sleeve_var = float(w_sleeve.T @ sigma @ w_sleeve)
    portfolio_vol = float(np.sqrt(max(portfolio_var, 0.0)))
    risky_sleeve_vol = float(np.sqrt(max(risky_sleeve_var, 0.0)))

    marginal = sigma @ w_total
    component_variance = w_total * marginal
    if portfolio_var > 0:
        risk_contribution_pct = component_variance / portfolio_var
    else:
        risk_contribution_pct = np.zeros_like(component_variance)

    contribution_df = pd.DataFrame({
        "cedear_ticker": tickers,
        "portfolio_weight": w_total,
        "risky_sleeve_weight": w_sleeve,
        "marginal_variance_contribution": marginal,
        "component_variance_contribution": component_variance,
        "risk_contribution_pct": risk_contribution_pct,
    }).sort_values("risk_contribution_pct", ascending=False).reset_index(drop=True)

    sector_exposure = pd.DataFrame()
    if sector_map is not None and {"cedear_ticker", "sector"}.issubset(sector_map.columns):
        sector_exposure = pos.merge(sector_map[["cedear_ticker", "sector"]], on="cedear_ticker", how="left")
        sector_exposure["sector"] = sector_exposure["sector"].fillna("UNKNOWN")
        sector_exposure = sector_exposure.groupby("sector", as_index=False)["weight"].sum().sort_values("weight", ascending=False)
        if cash_weight > 0:
            sector_exposure = pd.concat([
                sector_exposure,
                pd.DataFrame([{"sector": "Cash", "weight": float(cash_weight)}]),
            ], ignore_index=True).sort_values("weight", ascending=False).reset_index(drop=True)

    factor_exposure = pd.DataFrame()
    if factor_map is not None and {"cedear_ticker", "factor"}.issubset(factor_map.columns):
        factor_exposure = pos.merge(factor_map[["cedear_ticker", "factor"]], on="cedear_ticker", how="left")
        factor_exposure["factor"] = factor_exposure["factor"].fillna("UNKNOWN")
        factor_exposure = factor_exposure.groupby("factor", as_index=False)["weight"].sum().sort_values("weight", ascending=False)
        if cash_weight > 0:
            factor_exposure = pd.concat([
                factor_exposure,
                pd.DataFrame([{"factor": "Cash", "weight": float(cash_weight)}]),
            ], ignore_index=True).sort_values("weight", ascending=False).reset_index(drop=True)

    summary = {
        "portfolio_risk_status": "PORTFOLIO_RISK_READY",
        "portfolio_volatility_annualized": portfolio_vol,
        "risky_sleeve_volatility_annualized": risky_sleeve_vol,
        "position_count": int(len(pos)),
        "risky_weight_input": risky_weight_input,
        "cash_weight_input": float(cash_weight),
        "total_weight_input": total_weight_input,
        "cash_return_assumption_for_volatility": 0.0,
        "sector_concentration_status": "READY" if not sector_exposure.empty else "BLOCKED_BY_CLASSIFICATION_DATA",
        "factor_concentration_status": "READY" if not factor_exposure.empty else "BLOCKED_BY_CLASSIFICATION_DATA",
    }
    return summary, contribution_df, sector_exposure, factor_exposure
