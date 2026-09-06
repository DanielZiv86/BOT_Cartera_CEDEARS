from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

SCREENING_COMPONENTS = (
    "momentum_6m",
    "trend_vs_ma200",
    "volatility_63d",
)


def _percentile_score(series: pd.Series, *, higher_is_better: bool) -> pd.Series:
    """Cross-sectional percentile score in [0, 1], preserving missing values."""
    numeric = pd.to_numeric(series, errors="coerce")
    ranked = numeric.rank(method="average", pct=True, ascending=higher_is_better)
    if higher_is_better:
        return ranked
    return 1.0 - ranked + (1.0 / numeric.notna().sum() if numeric.notna().sum() else 0.0)


def build_screening_scores(
    universe: pd.DataFrame,
    features: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the minimal MVP screening score for every canonical CEDEAR.

    The engine does not invent or impute missing inputs. A ticker is scoreable only
    when the three existing market-feature inputs are available:
    6m momentum, price vs MA200 trend, and 63d annualized volatility.

    Components receive equal weight. This deliberately avoids introducing an
    unvalidated weighting model during the MVP phase.
    """
    if universe.empty:
        raise ValueError("canonical universe is empty")
    if features.empty:
        raise ValueError("market features are empty")

    universe_required = {"cedear_ticker"}
    feature_required = {
        "cedear_ticker",
        "last_price",
        "ma200",
        "momentum_6m",
        "volatility_63d",
    }
    missing_universe = sorted(universe_required - set(universe.columns))
    missing_features = sorted(feature_required - set(features.columns))
    if missing_universe:
        raise ValueError("canonical universe missing columns: " + ", ".join(missing_universe))
    if missing_features:
        raise ValueError("market features missing columns: " + ", ".join(missing_features))

    canonical = universe[["cedear_ticker"]].copy()
    canonical["cedear_ticker"] = canonical["cedear_ticker"].astype(str).str.upper()
    if canonical["cedear_ticker"].duplicated().any():
        duplicates = sorted(canonical.loc[canonical["cedear_ticker"].duplicated(), "cedear_ticker"].unique())
        raise ValueError("canonical universe contains duplicate tickers: " + ", ".join(duplicates))

    feature_cols = [
        "cedear_ticker",
        "as_of_date",
        "feature_status",
        "last_price",
        "ma200",
        "momentum_6m",
        "volatility_63d",
    ]
    available_cols = [col for col in feature_cols if col in features.columns]
    feature_frame = features[available_cols].copy()
    feature_frame["cedear_ticker"] = feature_frame["cedear_ticker"].astype(str).str.upper()
    feature_frame = feature_frame.drop_duplicates(subset=["cedear_ticker"], keep="last")

    result = canonical.merge(feature_frame, on="cedear_ticker", how="left", validate="one_to_one")

    last_price = pd.to_numeric(result["last_price"], errors="coerce")
    ma200 = pd.to_numeric(result["ma200"], errors="coerce")
    result["trend_vs_ma200"] = np.where(
        (last_price > 0) & (ma200 > 0),
        last_price / ma200 - 1.0,
        np.nan,
    )

    result["score_momentum_6m"] = _percentile_score(result["momentum_6m"], higher_is_better=True)
    result["score_trend_vs_ma200"] = _percentile_score(result["trend_vs_ma200"], higher_is_better=True)
    result["score_volatility_63d"] = _percentile_score(result["volatility_63d"], higher_is_better=False)

    score_cols = [
        "score_momentum_6m",
        "score_trend_vs_ma200",
        "score_volatility_63d",
    ]
    result["screening_input_count"] = result[score_cols].notna().sum(axis=1)
    scoreable = result["screening_input_count"] == len(score_cols)
    result["screening_score"] = np.nan
    result.loc[scoreable, "screening_score"] = result.loc[scoreable, score_cols].mean(axis=1) * 100.0
    result["screening_status"] = np.where(scoreable, "SCORE_READY", "BLOCKED_BY_DATA")

    result = result.sort_values("cedear_ticker").reset_index(drop=True)
    total = int(len(result))
    ready = int(scoreable.sum())
    blocked = total - ready
    metrics: dict[str, Any] = {
        "engine": "RESEARCH_MVP_SCREENING",
        "engine_version": "1.0",
        "ticker_count": total,
        "score_ready_count": ready,
        "blocked_by_data_count": blocked,
        "score_ready_pct": round(ready / total * 100.0, 2) if total else 0.0,
        "components": list(SCREENING_COMPONENTS),
        "component_weighting": "EQUAL_WEIGHT",
        "missing_data_policy": "NO_IMPUTATION_BLOCK_TICKER",
        "pass_screening": blocked == 0,
    }
    return result, metrics
