from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION_FACTOR = 252
CORRELATION_WINDOW = 252
ROLLING_WINDOWS = (63, 126, 252)
VAR_CONFIDENCE = 0.95


def _finite(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    value = float(value)
    return value if np.isfinite(value) else None


def _price_series(group: pd.DataFrame) -> pd.Series:
    close = pd.to_numeric(group["close"], errors="coerce")
    if "adjusted_close" in group.columns:
        adj = pd.to_numeric(group["adjusted_close"], errors="coerce")
        price = adj.where(adj > 0, close)
    else:
        price = close
    return price.where(price > 0)


def _historical_var_cvar(returns: pd.Series, confidence: float = VAR_CONFIDENCE) -> tuple[float | None, float | None]:
    clean = returns.dropna().astype(float)
    if len(clean) < 60:
        return None, None
    q = float(clean.quantile(1.0 - confidence))
    tail = clean[clean <= q]
    if tail.empty:
        return abs(q), None
    return abs(q), abs(float(tail.mean()))


def _downside_volatility(returns: pd.Series, window: int = CORRELATION_WINDOW) -> float | None:
    clean = returns.dropna().tail(window)
    negative = clean[clean < 0]
    if len(negative) < 20:
        return None
    return _finite(negative.std(ddof=1) * np.sqrt(ANNUALIZATION_FACTOR))


def build_return_matrix(history: pd.DataFrame) -> pd.DataFrame:
    required = {"cedear_ticker", "date", "close"}
    missing = sorted(required - set(history.columns))
    if missing:
        raise ValueError("underlying_history missing columns: " + ", ".join(missing))

    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"])
    price_frames = []
    for ticker, group in frame.groupby("cedear_ticker", sort=True):
        group = group.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        prices = _price_series(group)
        tmp = pd.DataFrame({"date": group["date"], ticker: prices}).dropna()
        price_frames.append(tmp.set_index("date"))
    if not price_frames:
        raise ValueError("no valid price history")
    prices = pd.concat(price_frames, axis=1).sort_index()
    return prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)


def calculate_risk_and_correlations(
    history: pd.DataFrame,
    benchmark_ticker: str = "SPY",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    returns = build_return_matrix(history)
    if benchmark_ticker not in returns.columns:
        raise ValueError(f"benchmark {benchmark_ticker} not found in underlying history")

    latest_window = returns.tail(CORRELATION_WINDOW)
    corr_matrix = latest_window.corr(min_periods=60)
    corr_long = (
        corr_matrix.stack(future_stack=True)
        .rename("correlation")
        .reset_index()
        .rename(columns={"level_0": "ticker_a", "level_1": "ticker_b"})
    )

    benchmark = returns[benchmark_ticker]
    rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []

    for ticker in returns.columns:
        r = returns[ticker]
        aligned = pd.concat([r, benchmark], axis=1, keys=["asset", "benchmark"]).dropna().tail(CORRELATION_WINDOW)

        beta = None
        corr_252 = None
        if len(aligned) >= 60:
            benchmark_var = aligned["benchmark"].var(ddof=1)
            if benchmark_var and benchmark_var > 0:
                beta = _finite(aligned["asset"].cov(aligned["benchmark"]) / benchmark_var)
            corr_252 = _finite(aligned["asset"].corr(aligned["benchmark"]))

        var95, cvar95 = _historical_var_cvar(r.tail(CORRELATION_WINDOW))
        downside_vol = _downside_volatility(r)

        latest_date = r.dropna().index.max()
        row = {
            "cedear_ticker": ticker,
            "benchmark_ticker": benchmark_ticker,
            "as_of_date": latest_date.date().isoformat() if pd.notna(latest_date) else None,
            "beta_252d_vs_spy": beta,
            "correlation_252d_vs_spy": corr_252,
            "downside_volatility_252d": downside_vol,
            "historical_var_95_1d": var95,
            "historical_cvar_95_1d": cvar95,
            "observations_252d": int(len(aligned)),
        }

        for window in ROLLING_WINDOWS:
            pair = pd.concat([r, benchmark], axis=1, keys=["asset", "benchmark"]).dropna().tail(window)
            corr = _finite(pair["asset"].corr(pair["benchmark"])) if len(pair) >= max(20, window // 3) else None
            row[f"rolling_corr_{window}d_vs_spy"] = corr
            rolling_rows.append({
                "cedear_ticker": ticker,
                "benchmark_ticker": benchmark_ticker,
                "window_trading_days": window,
                "as_of_date": latest_date.date().isoformat() if pd.notna(latest_date) else None,
                "rolling_correlation": corr,
                "observation_count": int(len(pair)),
            })

        required_values = [
            row["beta_252d_vs_spy"], row["correlation_252d_vs_spy"], row["downside_volatility_252d"],
            row["historical_var_95_1d"], row["historical_cvar_95_1d"],
            *(row[f"rolling_corr_{w}d_vs_spy"] for w in ROLLING_WINDOWS),
        ]
        row["risk_status"] = "RISK_METRICS_READY" if all(v is not None for v in required_values) else "RISK_METRICS_PARTIAL"
        rows.append(row)

    risk_df = pd.DataFrame(rows).sort_values("cedear_ticker").reset_index(drop=True)
    rolling_df = pd.DataFrame(rolling_rows).sort_values(["cedear_ticker", "window_trading_days"]).reset_index(drop=True)
    ready = int((risk_df["risk_status"] == "RISK_METRICS_READY").sum())

    metrics = {
        "engine_version": "1.0",
        "ticker_count": int(len(risk_df)),
        "risk_metrics_ready_count": ready,
        "risk_metrics_partial_count": int(len(risk_df) - ready),
        "risk_metrics_ready_pct": round(ready / len(risk_df) * 100, 2) if len(risk_df) else 0.0,
        "benchmark_ticker": benchmark_ticker,
        "correlation_window_trading_days": CORRELATION_WINDOW,
        "rolling_windows_trading_days": list(ROLLING_WINDOWS),
        "var_method": "HISTORICAL",
        "var_confidence": VAR_CONFIDENCE,
        "var_horizon": "1D",
        "annualization_factor": ANNUALIZATION_FACTOR,
        "correlation_matrix_pairs": int(len(corr_long)),
        "pass_cross_sectional_risk": ready == len(risk_df),
    }
    return risk_df, corr_long, rolling_df, metrics
