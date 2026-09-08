from __future__ import annotations

import numpy as np
import pandas as pd

OFFICIAL_RATIO_STATUSES = {"RATIO_VALIDATED_COMAFI"}
DERIVED_RATIO_STATUS = "RATIO_VALIDATED_CANONICAL_CCL"
PASSABLE_RATIO_STATUSES = OFFICIAL_RATIO_STATUSES | {DERIVED_RATIO_STATUS}


def _series(out: pd.DataFrame, column: str, default=np.nan) -> pd.Series:
    """Always return an index-aligned Series, including when an optional column is absent."""
    if column in out.columns:
        return out[column]
    return pd.Series(default, index=out.index)


def recover_analytical_local_market(
    frame: pd.DataFrame,
    *,
    canonical_ratio_ccl_tolerance: float = 0.05,
) -> pd.DataFrame:
    """Recover analytical references only from validated evidence; never fabricate execution data."""
    out = frame.copy()
    if out.empty:
        return out

    for col in (
        "universe_ratio",
        "ratio_used",
        "last_close",
        "analytical_local_ref_ars",
        "market_ccl_reference",
        "implied_ccl",
        "spread_pct",
    ):
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")

    if "ratio_status" not in out:
        out["ratio_status"] = "RATIO_UNVERIFIED_COMAFI"
    if "market_ccl_crosscheck_status" not in out:
        out["market_ccl_crosscheck_status"] = "MARKET_CCL_CROSSCHECK_UNAVAILABLE"
    if "valuation_g4_local_gate" not in out:
        out["valuation_g4_local_gate"] = "BLOCKED"

    out["observed_analytical_local_ref_ars"] = out["analytical_local_ref_ars"]
    out["analytical_reference_method"] = "OBSERVED_LOCAL_MARKET"
    out["ratio_validation_method"] = np.where(
        out["ratio_status"].eq("RATIO_VALIDATED_COMAFI"),
        "COMAFI_OFFICIAL_REGISTRY",
        "UNVERIFIED",
    )

    market_ccl = pd.to_numeric(out["market_ccl_reference"], errors="coerce")
    canonical_ratio = pd.to_numeric(out["universe_ratio"], errors="coerce")
    underlying = pd.to_numeric(out["last_close"], errors="coerce")
    observed = pd.to_numeric(out["observed_analytical_local_ref_ars"], errors="coerce")

    canonical_implied = (observed * canonical_ratio / underlying).where(
        observed.gt(0) & canonical_ratio.gt(0) & underlying.gt(0)
    )
    dev = (canonical_implied / market_ccl - 1.0).where(market_ccl.gt(0))
    out["canonical_ratio_ccl_deviation_pct"] = dev

    ratio_recoverable = (
        ~out["ratio_status"].eq("RATIO_VALIDATED_COMAFI")
        & canonical_ratio.gt(0)
        & canonical_implied.gt(0)
        & dev.abs().le(float(canonical_ratio_ccl_tolerance))
    )
    out.loc[ratio_recoverable, "ratio_status"] = DERIVED_RATIO_STATUS
    out.loc[ratio_recoverable, "ratio_used"] = canonical_ratio[ratio_recoverable]
    out.loc[ratio_recoverable, "ratio_validation_method"] = "CANONICAL_RATIO_PLUS_MARKET_CCL_RECONCILIATION"
    out.loc[ratio_recoverable, "implied_ccl"] = canonical_implied[ratio_recoverable]
    out.loc[ratio_recoverable, "market_ccl_crosscheck_status"] = "MARKET_CCL_CROSSCHECK_PASS"
    out.loc[ratio_recoverable, "ccl_status"] = "CCL_READY_VALIDATED_CANONICAL"
    out.loc[ratio_recoverable, "valuation_g4_local_gate"] = "PASS_WITH_WARNING"

    ratio_ok = out["ratio_status"].isin(PASSABLE_RATIO_STATUSES) & pd.to_numeric(out["ratio_used"], errors="coerce").gt(0)
    market_ok = market_ccl.gt(0) & underlying.gt(0)
    missing = observed.isna() | observed.le(0)
    inconsistent = out["market_ccl_crosscheck_status"].eq("MARKET_CCL_CROSSCHECK_BLOCKED")
    analytical_fallback = ratio_ok & market_ok & (missing | inconsistent)

    synthetic = (underlying * market_ccl / pd.to_numeric(out["ratio_used"], errors="coerce")).where(analytical_fallback)
    out.loc[analytical_fallback, "analytical_local_ref_ars"] = synthetic[analytical_fallback]
    out.loc[analytical_fallback, "analytical_reference_method"] = "SYNTHETIC_FROM_UNDERLYING_MARKET_CCL_RATIO"
    out.loc[analytical_fallback, "ccl_status"] = "CCL_ANALYTICAL_REFERENCE_ONLY"
    out.loc[analytical_fallback, "valuation_g4_local_gate"] = "PASS_WITH_WARNING"
    out["analytical_recovery_applied"] = ratio_recoverable | analytical_fallback

    # Explicit two-gate contract. Analytical readiness may use a derived reference;
    # execution readiness always requires real executable prices and a sane real book.
    out["analysis_ready"] = (
        out["valuation_g4_local_gate"].isin(["PASS", "PASS_WITH_WARNING"])
        & pd.to_numeric(out["analytical_local_ref_ars"], errors="coerce").gt(0)
        & out["ratio_status"].isin(PASSABLE_RATIO_STATUSES)
    )
    execution_status = _series(out, "execution_book_status", "")
    executable_buy = pd.to_numeric(_series(out, "effective_executable_buy_ars"), errors="coerce")
    executable_sell = pd.to_numeric(_series(out, "effective_executable_sell_ars"), errors="coerce")
    out["execution_ready"] = (
        execution_status.eq("BOOK_EXECUTABLE_BY_SANITY")
        & executable_buy.gt(0)
        & executable_sell.gt(0)
    )
    return out
