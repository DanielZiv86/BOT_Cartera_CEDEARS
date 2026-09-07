from __future__ import annotations

import numpy as np
import pandas as pd


OFFICIAL_RATIO_STATUSES = {"RATIO_VALIDATED_COMAFI"}
DERIVED_RATIO_STATUS = "RATIO_VALIDATED_CANONICAL_CCL"
PASSABLE_RATIO_STATUSES = OFFICIAL_RATIO_STATUSES | {DERIVED_RATIO_STATUS}


def recover_analytical_local_market(
    frame: pd.DataFrame,
    *,
    canonical_ratio_ccl_tolerance: float = 0.05,
) -> pd.DataFrame:
    """Recover analytical G4 inputs without fabricating executable market data.

    This recovery is deliberately separated from execution readiness. It does two
    evidence-based things only:

    1. If the official Comafi scraper did not return a ratio, a positive canonical
       universe ratio may be accepted *with warning* when the independently
       observed local CEDEAR price and underlying price imply a CCL within the
       configured tolerance of the robust market CCL.
    2. If a current local quote is missing or clearly inconsistent with the robust
       market CCL, an analytical-only local reference can be synthesized from
       underlying price × market CCL / validated ratio. The observed quote is
       preserved and execution remains not-ready.

    Nothing here creates bid/ask liquidity, changes provider provenance, or makes
    a ticker trade-ready. It only prevents execution-data gaps from blocking the
    economic G4 comparison against cash.
    """
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

    if "ratio_status" not in out.columns:
        out["ratio_status"] = "RATIO_UNVERIFIED_COMAFI"
    if "market_ccl_crosscheck_status" not in out.columns:
        out["market_ccl_crosscheck_status"] = "MARKET_CCL_CROSSCHECK_UNAVAILABLE"
    if "valuation_g4_local_gate" not in out.columns:
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
    observed_local = pd.to_numeric(out["observed_analytical_local_ref_ars"], errors="coerce")

    canonical_implied = (observed_local * canonical_ratio / underlying).where(
        observed_local.gt(0) & canonical_ratio.gt(0) & underlying.gt(0)
    )
    canonical_dev = (canonical_implied / market_ccl - 1.0).where(market_ccl.gt(0))
    out["canonical_ratio_ccl_deviation_pct"] = canonical_dev

    ratio_recoverable = (
        ~out["ratio_status"].eq("RATIO_VALIDATED_COMAFI")
        & canonical_ratio.gt(0)
        & canonical_implied.gt(0)
        & canonical_dev.abs().le(float(canonical_ratio_ccl_tolerance))
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
    quote_missing = observed_local.isna() | observed_local.le(0)
    quote_inconsistent = out["market_ccl_crosscheck_status"].eq("MARKET_CCL_CROSSCHECK_BLOCKED")
    analytical_fallback = ratio_ok & market_ok & (quote_missing | quote_inconsistent)

    synthetic_ref = (underlying * market_ccl / pd.to_numeric(out["ratio_used"], errors="coerce")).where(analytical_fallback)
    out.loc[analytical_fallback, "analytical_local_ref_ars"] = synthetic_ref[analytical_fallback]
    out.loc[analytical_fallback, "analytical_reference_method"] = "SYNTHETIC_FROM_UNDERLYING_MARKET_CCL_RATIO"
    out.loc[analytical_fallback, "ccl_status"] = "CCL_ANALYTICAL_REFERENCE_ONLY"
    out.loc[analytical_fallback, "valuation_g4_local_gate"] = "PASS_WITH_WARNING"

    # Preserve strict execution semantics: synthetic analytical recovery never
    # manufactures a last price, bid, ask, or executable book.
    out["analytical_recovery_applied"] = ratio_recoverable | analytical_fallback
    return out
