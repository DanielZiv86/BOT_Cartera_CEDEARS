from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

COMPONENTS = {
    "momentum_6m": (True, 0.25),
    "trend_vs_ma200": (True, 0.20),
    "volatility_63d": (False, 0.20),
    "max_drawdown": (True, 0.20),
    "momentum_3m": (True, 0.15),
}
VALID_DATA_STATES = {"OBSERVED", "DERIVED", "FALLBACK", "NOT_APPLICABLE", "UNAVAILABLE"}
NEUTRAL_SCORE = 0.50
MAX_UNCERTAINTY_PENALTY = 20.0


def _percentile_score(series: pd.Series, *, higher_is_better: bool) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    ranked = numeric.rank(method="average", pct=True, ascending=True)
    if higher_is_better:
        return ranked
    valid_count = int(numeric.notna().sum())
    return 1.0 - ranked + (1.0 / valid_count if valid_count else 0.0)


def _instrument_model(row: pd.Series) -> str:
    text = " ".join(str(row.get(c, "")) for c in ("instrument_type", "security_type", "asset_type", "name")).upper()
    if "ETF" in text or "FUND" in text:
        return "ETF_V1"
    if "REIT" in text:
        return "REIT_V1"
    if "BANK" in text or "FINANC" in text:
        return "FINANCIAL_V1"
    return "OPERATING_COMPANY_V1"


def build_screening_scores(universe: pd.DataFrame, features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Produce one auditable screening decision for every canonical CEDEAR."""
    if universe.empty:
        raise ValueError("canonical universe is empty")
    if "cedear_ticker" not in universe.columns:
        raise ValueError("canonical universe missing columns: cedear_ticker")

    canonical = universe.copy()
    canonical["cedear_ticker"] = canonical["cedear_ticker"].astype(str).str.strip().str.upper()
    if canonical["cedear_ticker"].eq("").any():
        raise ValueError("canonical universe contains empty ticker")
    if canonical["cedear_ticker"].duplicated().any():
        dup = sorted(canonical.loc[canonical["cedear_ticker"].duplicated(False), "cedear_ticker"].unique())
        raise ValueError("canonical universe contains duplicate tickers: " + ", ".join(dup))

    if features is None or features.empty or "cedear_ticker" not in features.columns:
        raise ValueError("market features layer is empty or invalid")
    feature_frame = features.copy()
    feature_frame["cedear_ticker"] = feature_frame["cedear_ticker"].astype(str).str.strip().str.upper()
    feature_frame = feature_frame.drop_duplicates("cedear_ticker", keep="last")
    keep = ["cedear_ticker", "as_of_date", "feature_status", "last_price", "ma200", *[c for c in COMPONENTS if c not in {"trend_vs_ma200"}]]
    keep = [c for c in dict.fromkeys(keep) if c in feature_frame.columns]
    # Canonical is intentionally the left side so mandate/deployment metadata
    # (e.g. byma_tradable, legacy_cedear_ticker) survives into ranking.
    result = canonical.merge(feature_frame[keep], on="cedear_ticker", how="left", validate="one_to_one")

    for col in ("last_price", "ma200", "momentum_6m", "volatility_63d", "max_drawdown", "momentum_3m"):
        if col not in result:
            result[col] = np.nan
        result[col] = pd.to_numeric(result[col], errors="coerce")
    result["trend_vs_ma200"] = np.where(
        (result["last_price"] > 0) & (result["ma200"] > 0),
        result["last_price"] / result["ma200"] - 1.0,
        np.nan,
    )

    weighted = pd.Series(0.0, index=result.index)
    observed_weight = pd.Series(0.0, index=result.index)
    missing_components: list[list[str]] = [[] for _ in range(len(result))]
    for component, (higher_is_better, weight) in COMPONENTS.items():
        raw = result[component]
        score = _percentile_score(raw, higher_is_better=higher_is_better)
        available = raw.notna() & np.isfinite(raw)
        result[f"state_{component}"] = np.where(available, "OBSERVED" if component != "trend_vs_ma200" else "DERIVED", "UNAVAILABLE")
        result[f"score_{component}"] = score.where(available, NEUTRAL_SCORE)
        weighted += result[f"score_{component}"] * weight
        observed_weight += available.astype(float) * weight
        for i in result.index[~available]:
            missing_components[i].append(component)

    result["screening_input_count"] = sum(result[f"state_{c}"].ne("UNAVAILABLE").astype(int) for c in COMPONENTS)
    result["data_quality_score"] = (observed_weight * 100.0).round(2)
    result["raw_screening_score"] = (weighted * 100.0).round(4)
    result["uncertainty_penalty"] = ((1.0 - observed_weight) * MAX_UNCERTAINTY_PENALTY).round(4)
    result["screening_score"] = (result["raw_screening_score"] - result["uncertainty_penalty"]).clip(0, 100).round(4)
    result["missing_components"] = [",".join(v) for v in missing_components]
    result["scoring_model_id"] = result.apply(_instrument_model, axis=1)
    result["screening_status"] = "SCORE_READY"
    result["screening_decision"] = np.select(
        [result["screening_score"] >= 65, result["screening_score"] >= 45],
        ["PASS", "WATCH"], default="FAIL"
    )
    result["lineage_status"] = "CANONICAL_UNIVERSE+MARKET_FEATURES"

    result = result.sort_values("cedear_ticker").reset_index(drop=True)
    total = len(result)
    metrics: dict[str, Any] = {
        "engine": "RESEARCH_UNIVERSAL_SCREENING",
        "engine_version": "1.0.1",
        "ticker_count": int(total),
        "score_ready_count": int(result["screening_score"].notna().sum()),
        "blocked_by_data_count": 0,
        "score_ready_pct": round(result["screening_score"].notna().mean() * 100.0, 2),
        "components": list(COMPONENTS),
        "component_weights": {k: v[1] for k, v in COMPONENTS.items()},
        "missing_data_policy": "NEUTRAL_CONTRIBUTION_PLUS_EXPLICIT_UNCERTAINTY_PENALTY",
        "mean_data_quality_score": round(float(result["data_quality_score"].mean()), 2),
        "zero_observation_tickers": int((result["screening_input_count"] == 0).sum()),
        "pass_screening": bool(total and result["screening_score"].notna().all()),
    }
    return result, metrics
