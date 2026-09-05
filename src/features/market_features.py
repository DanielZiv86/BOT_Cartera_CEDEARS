from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

RETURN_WINDOWS = (1, 5, 21, 63, 126, 252)
VOL_WINDOWS = (21, 63, 252)
MA_WINDOWS = (20, 50, 200)
MOMENTUM_WINDOWS = {"3m": 63, "6m": 126, "12m": 252}
ANNUALIZATION_FACTOR = 252


def _finite_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    value = float(value)
    return value if np.isfinite(value) else None


def _period_return(series: pd.Series, periods: int) -> float | None:
    if len(series) <= periods:
        return None
    base = float(series.iloc[-(periods + 1)])
    current = float(series.iloc[-1])
    if base <= 0:
        return None
    return current / base - 1.0


def _annualized_volatility(series: pd.Series, window: int) -> float | None:
    if len(series) < window + 1:
        return None
    returns = series.pct_change().dropna().tail(window)
    if len(returns) < window:
        return None
    value = returns.std(ddof=1) * np.sqrt(ANNUALIZATION_FACTOR)
    return _finite_or_none(value)


def _max_drawdown(series: pd.Series) -> float | None:
    if series.empty:
        return None
    running_max = series.cummax()
    drawdowns = series / running_max - 1.0
    return _finite_or_none(drawdowns.min())


def _moving_average(series: pd.Series, window: int) -> float | None:
    if len(series) < window:
        return None
    return _finite_or_none(series.tail(window).mean())


def _select_price_series(frame: pd.DataFrame) -> tuple[pd.Series, str]:
    close = pd.to_numeric(frame["close"], errors="coerce")
    if "adjusted_close" in frame.columns:
        adjusted = pd.to_numeric(frame["adjusted_close"], errors="coerce")
        # Prefer adjusted prices while allowing provider gaps on individual dates.
        combined = adjusted.where(adjusted > 0, close)
        if adjusted.notna().any():
            return combined, "ADJUSTED_CLOSE_WITH_CLOSE_FALLBACK"
    return close, "CLOSE"


def calculate_market_features(history: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = {"cedear_ticker", "canonical_underlying", "date", "close"}
    missing = sorted(required - set(history.columns))
    if missing:
        raise ValueError("underlying_history missing columns: " + ", ".join(missing))
    if history.empty:
        raise ValueError("underlying_history is empty")

    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"])
    frame = frame.sort_values(["cedear_ticker", "date"])

    rows: list[dict[str, Any]] = []
    feature_columns = [
        *(f"return_{n}d" for n in RETURN_WINDOWS),
        *(f"volatility_{n}d" for n in VOL_WINDOWS),
        "max_drawdown",
        *(f"ma{n}" for n in MA_WINDOWS),
        "momentum_3m",
        "momentum_6m",
        "momentum_12m",
    ]

    for ticker, group in frame.groupby("cedear_ticker", sort=True):
        group = group.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        prices, price_basis = _select_price_series(group)
        valid = pd.DataFrame({"date": group["date"], "price": prices}).dropna()
        valid = valid[valid["price"] > 0]
        series = valid["price"].astype(float).reset_index(drop=True)

        row: dict[str, Any] = {
            "cedear_ticker": ticker,
            "canonical_underlying": group["canonical_underlying"].iloc[-1],
            "as_of_date": valid["date"].iloc[-1].date().isoformat() if not valid.empty else None,
            "observation_count": int(len(series)),
            "price_basis": price_basis,
            "last_price": _finite_or_none(series.iloc[-1]) if not series.empty else None,
        }

        for window in RETURN_WINDOWS:
            row[f"return_{window}d"] = _period_return(series, window)
        for window in VOL_WINDOWS:
            row[f"volatility_{window}d"] = _annualized_volatility(series, window)

        row["max_drawdown"] = _max_drawdown(series)
        for window in MA_WINDOWS:
            row[f"ma{window}"] = _moving_average(series, window)

        for label, window in MOMENTUM_WINDOWS.items():
            row[f"momentum_{label}"] = _period_return(series, window)

        populated = sum(row.get(col) is not None for col in feature_columns)
        row["feature_count"] = len(feature_columns)
        row["populated_feature_count"] = populated
        row["feature_coverage_pct"] = round(populated / len(feature_columns) * 100, 2)
        row["feature_status"] = "FEATURES_READY" if populated == len(feature_columns) else "FEATURES_PARTIAL"
        rows.append(row)

    features = pd.DataFrame(rows).sort_values("cedear_ticker").reset_index(drop=True)
    ready = int((features["feature_status"] == "FEATURES_READY").sum())
    partial = int((features["feature_status"] == "FEATURES_PARTIAL").sum())

    per_feature_coverage = {
        col: int(features[col].notna().sum()) for col in feature_columns
    }
    metrics = {
        "engine_version": "1.0",
        "ticker_count": int(len(features)),
        "features_ready_count": ready,
        "features_partial_count": partial,
        "features_ready_pct": round(ready / len(features) * 100, 2) if len(features) else 0.0,
        "per_feature_coverage_count": per_feature_coverage,
        "pass_market_features": ready == len(features),
        "annualization_factor": ANNUALIZATION_FACTOR,
        "return_windows_trading_days": list(RETURN_WINDOWS),
        "volatility_windows_trading_days": list(VOL_WINDOWS),
        "moving_average_windows_trading_days": list(MA_WINDOWS),
        "momentum_windows_trading_days": MOMENTUM_WINDOWS,
        "max_drawdown_scope": "FULL_AVAILABLE_HISTORY",
    }
    return features, metrics
