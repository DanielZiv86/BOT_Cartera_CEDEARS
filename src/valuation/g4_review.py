from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def apply_extreme_target_review(
    result: pd.DataFrame,
    valuation_inputs: pd.DataFrame,
    policy: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Annotate evaluated G4 rows that require human review before actionability.

    This governance layer never changes the economic G4_PASS/G4_FAIL result. It
    prevents unusually large 12m analyst targets or unusually wide target ranges
    from becoming actionable signals without an explicit review.
    """
    cfg = (policy or {}).get("target_review", {})
    base_upside_threshold = float(cfg.get("base_upside_review_threshold", 0.75))
    bull_upside_threshold = float(cfg.get("bull_upside_review_threshold", 1.25))
    dispersion_threshold = float(cfg.get("high_low_dispersion_review_threshold", 1.00))

    out = result.copy()
    vals = valuation_inputs.copy()
    if vals.empty or "cedear_ticker" not in vals.columns:
        vals = pd.DataFrame(columns=["cedear_ticker", "current_price", "bull_target_price", "base_target_price", "bear_target_price"])
    vals["cedear_ticker"] = vals["cedear_ticker"].astype(str).str.upper()
    keep = [c for c in ["cedear_ticker", "current_price", "bull_target_price", "base_target_price", "bear_target_price"] if c in vals.columns]
    vals = vals[keep].drop_duplicates("cedear_ticker", keep="last")
    out = out.merge(vals, on="cedear_ticker", how="left", suffixes=("", "_review"))

    review_flags: list[list[str]] = []
    statuses: list[str] = []
    base_upsides: list[float | None] = []
    bull_upsides: list[float | None] = []
    dispersions: list[float | None] = []

    for _, row in out.iterrows():
        price = _num(row.get("current_price"))
        bull = _num(row.get("bull_target_price"))
        base = _num(row.get("base_target_price"))
        bear = _num(row.get("bear_target_price"))
        flags: list[str] = []
        base_up = bull_up = dispersion = None
        if price is not None and price > 0:
            if base is not None:
                base_up = base / price - 1.0
                if base_up > base_upside_threshold:
                    flags.append("EXTREME_BASE_TARGET_UPSIDE")
            if bull is not None:
                bull_up = bull / price - 1.0
                if bull_up > bull_upside_threshold:
                    flags.append("EXTREME_BULL_TARGET_UPSIDE")
            if bull is not None and bear is not None:
                dispersion = (bull - bear) / price
                if dispersion > dispersion_threshold:
                    flags.append("EXTREME_HIGH_LOW_TARGET_DISPERSION")

        review_flags.append(flags)
        base_upsides.append(base_up)
        bull_upsides.append(bull_up)
        dispersions.append(dispersion)
        if str(row.get("g4_status")) == "G4_PASS" and flags:
            statuses.append("EXTREME_TARGET_REQUIRES_REVIEW")
        elif str(row.get("g4_status")) == "G4_PASS":
            statuses.append("ACTIONABLE_IF_GLOBAL_GOVERNANCE_ALLOWS")
        else:
            statuses.append("NOT_ACTIONABLE")

    out["target_review_flags"] = review_flags
    out["target_review_status"] = statuses
    out["base_target_upside_vs_current"] = base_upsides
    out["bull_target_upside_vs_current"] = bull_upsides
    out["high_low_target_dispersion_vs_current"] = dispersions

    review_required = int((out["target_review_status"] == "EXTREME_TARGET_REQUIRES_REVIEW").sum())
    clean_passes = int((out["target_review_status"] == "ACTIONABLE_IF_GLOBAL_GOVERNANCE_ALLOWS").sum())
    metrics = {
        "extreme_target_review_required_count": review_required,
        "clean_g4_pass_count": clean_passes,
        "target_review_thresholds": {
            "base_upside": base_upside_threshold,
            "bull_upside": bull_upside_threshold,
            "high_low_dispersion": dispersion_threshold,
        },
    }
    return out, metrics
