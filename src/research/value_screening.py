from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DEFAULT_COMPONENTS = {
    "consensus_upside_to_base": (True, 0.30),
    "fundamental_pe_normalized": (False, 0.20),
    "fundamental_eps_growth_3y": (True, 0.20),
    "fundamental_roe": (True, 0.10),
    "fundamental_debt_to_equity": (False, 0.10),
    "analyst_count": (True, 0.10),
}
NEUTRAL_SCORE = 0.50
DEFAULT_MAX_UNCERTAINTY_PENALTY = 20.0

VALUATION_COLUMNS = [
    "cedear_ticker",
    "valuation_engine_type",
    "valuation_status",
    "current_price",
    "base_target_price",
    "analyst_count",
    "fundamental_pe_normalized",
    "fundamental_eps_growth_3y",
    "fundamental_roe",
    "fundamental_debt_to_equity",
]


def _percentile_score(series: pd.Series, *, higher_is_better: bool) -> pd.Series:
    """Same percentile-rank + fair-tiebreak design already used by the technical
    screening engine (src/research/screening.py). Duplicated intentionally,
    rather than imported, so this shadow-only module never has to touch the
    production screening module.
    """
    numeric = pd.to_numeric(series, errors="coerce")
    ranked = numeric.rank(method="average", pct=True, ascending=True)
    if higher_is_better:
        return ranked
    valid_count = int(numeric.notna().sum())
    return 1.0 - ranked + (1.0 / valid_count if valid_count else 0.0)


def _components_from_policy(policy: dict[str, Any] | None) -> dict[str, tuple[bool, float]]:
    raw = (policy or {}).get("components")
    if not raw:
        return dict(DEFAULT_COMPONENTS)
    out: dict[str, tuple[bool, float]] = {}
    for name, cfg in raw.items():
        out[name] = (bool(cfg.get("higher_is_better", True)), float(cfg.get("weight", 0.0)))
    return out


def build_value_scores(universe: pd.DataFrame, valuation: pd.DataFrame, policy: dict[str, Any] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Score every canonical ticker on fundamentals from the broad-universe
    valuation scenario (src/orchestration/build_valuation_scenarios.py run
    against the full eligible universe, not just a pre-selected Top-N).

    Mirrors src/research/screening.py's contract: every canonical ticker gets
    a score (never dropped), missing fundamental inputs get a neutral
    contribution plus an explicit uncertainty penalty, and non-equity
    instruments (ETFs, trackers) are scored as structurally not applicable so
    they never compete against equities on value.
    """
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

    if valuation is None or valuation.empty or "cedear_ticker" not in valuation.columns:
        raise ValueError("broad-universe valuation scenario layer is empty or invalid")
    val_frame = valuation.copy()
    val_frame["cedear_ticker"] = val_frame["cedear_ticker"].astype(str).str.strip().str.upper()
    val_frame = val_frame.drop_duplicates("cedear_ticker", keep="last")
    keep = [c for c in dict.fromkeys(VALUATION_COLUMNS) if c in val_frame.columns]
    result = canonical.merge(val_frame[keep], on="cedear_ticker", how="left", validate="one_to_one")

    for col in ("current_price", "base_target_price", "analyst_count", "fundamental_pe_normalized", "fundamental_eps_growth_3y", "fundamental_roe", "fundamental_debt_to_equity"):
        if col not in result:
            result[col] = np.nan
        result[col] = pd.to_numeric(result[col], errors="coerce")

    result["instrument_class"] = result.get("valuation_engine_type", pd.Series(index=result.index, dtype=object)).astype(str).str.upper().replace({"NAN": "UNKNOWN"})
    equity_mask = result["instrument_class"].eq("EQUITY")

    result["consensus_upside_to_base"] = np.where(
        (result["current_price"] > 0) & (result["base_target_price"] > 0),
        result["base_target_price"] / result["current_price"] - 1.0,
        np.nan,
    )

    components = _components_from_policy(policy)
    max_uncertainty_penalty = float((policy or {}).get("max_uncertainty_penalty", DEFAULT_MAX_UNCERTAINTY_PENALTY))

    weighted = pd.Series(0.0, index=result.index)
    observed_weight = pd.Series(0.0, index=result.index)
    missing_components: list[list[str]] = [[] for _ in range(len(result))]
    for component, (higher_is_better, weight) in components.items():
        raw = result[component] if component in result else pd.Series(np.nan, index=result.index)
        score = _percentile_score(raw, higher_is_better=higher_is_better)
        available = raw.notna() & np.isfinite(raw) & equity_mask
        result[f"state_value_{component}"] = np.where(available, "OBSERVED", "UNAVAILABLE")
        result[f"score_value_{component}"] = score.where(available, NEUTRAL_SCORE)
        weighted += result[f"score_value_{component}"] * weight
        observed_weight += available.astype(float) * weight
        for i in result.index[~available]:
            missing_components[i].append(component)

    result["value_screening_applicable"] = equity_mask
    result["value_input_count"] = sum(result[f"state_value_{c}"].eq("OBSERVED").astype(int) for c in components)
    result["value_data_quality_score"] = (observed_weight * 100.0).round(2)
    result["raw_value_score"] = (weighted * 100.0).round(4)
    result["value_uncertainty_penalty"] = ((1.0 - observed_weight) * max_uncertainty_penalty).round(4)
    result["value_score"] = (result["raw_value_score"] - result["value_uncertainty_penalty"]).clip(0, 100).round(4)
    result["missing_value_components"] = [",".join(v) for v in missing_components]
    # Same design as screening.py: SCORE_READY means "a score was produced",
    # not "all inputs were observed" — data-quality gating happens downstream.
    result["value_screening_status"] = "SCORE_READY"
    result["value_lineage_status"] = "CANONICAL_UNIVERSE+BROAD_VALUATION_SCENARIOS"

    result = result.sort_values("cedear_ticker").reset_index(drop=True)
    total = len(result)
    equity_total = int(equity_mask.sum())
    metrics: dict[str, Any] = {
        "engine": "RESEARCH_VALUE_SCREENING_SHADOW",
        "engine_version": "1.0.0-shadow",
        "methodology_version": str((policy or {}).get("methodology_version") or "VALUE-SCREEN-1.0-SHADOW"),
        "ticker_count": int(total),
        "equity_ticker_count": equity_total,
        "non_equity_ticker_count": int(total - equity_total),
        "score_ready_count": int(result["value_score"].notna().sum()),
        "components": list(components),
        "component_weights": {k: v[1] for k, v in components.items()},
        "missing_data_policy": "NEUTRAL_CONTRIBUTION_PLUS_EXPLICIT_UNCERTAINTY_PENALTY",
        "mean_equity_value_data_quality_score": round(float(result.loc[equity_mask, "value_data_quality_score"].mean()), 2) if equity_total else None,
        "zero_observation_equity_tickers": int(((result["value_input_count"] == 0) & equity_mask).sum()),
    }
    return result, metrics
