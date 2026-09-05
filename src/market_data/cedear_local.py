from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def argentina_market_session_status(now: datetime | None = None) -> str:
    local = (now or datetime.now(timezone.utc)).astimezone(AR_TZ)
    if local.weekday() >= 5:
        return "SESSION_CLOSED_WEEKEND"
    if time(10, 30) <= local.time().replace(tzinfo=None) <= time(17, 0):
        return "SESSION_OPEN_BY_CLOCK"
    return "SESSION_CLOSED_BY_CLOCK"


def _book_sanity(out: pd.DataFrame) -> pd.Series:
    last = out["last_price_ars"]
    bid = out["bid_ars"]
    ask = out["ask_ars"]
    mid = (bid + ask) / 2.0
    spread = (ask - bid) / mid
    return (
        last.gt(0)
        & bid.gt(0)
        & ask.gt(0)
        & ask.ge(bid)
        & bid.div(last).between(0.50, 1.50)
        & ask.div(last).between(0.50, 1.50)
        & spread.between(0.0, 0.25)
    )


def build_local_market_layer(
    universe: pd.DataFrame,
    underlying_prices: pd.DataFrame,
    local_quotes: pd.DataFrame,
    ratio_registry: pd.DataFrame | None = None,
    ccl_reference: pd.DataFrame | None = None,
    brokerage_rate: float = 0.006,
    now: datetime | None = None,
) -> pd.DataFrame:
    if not {"cedear_ticker", "ratio"}.issubset(universe.columns):
        raise ValueError("universe missing cedear_ticker/ratio")
    if not {"cedear_ticker", "last_close", "currency", "freshness_status"}.issubset(underlying_prices.columns):
        raise ValueError("underlying prices missing required fields")

    base_cols = {"cedear_ticker", "ratio", "instrument_type", "underlying_market", "underlying_ticker", "canonical_underlying"}
    base = universe[[c for c in universe.columns if c in base_cols]].copy().rename(columns={"ratio": "universe_ratio"})
    base["cedear_ticker"] = base["cedear_ticker"].astype(str).str.upper()

    px_cols = {"cedear_ticker", "last_close", "last_close_date", "currency", "freshness_status", "provider_selected"}
    px = underlying_prices[[c for c in underlying_prices.columns if c in px_cols]].copy()
    px["cedear_ticker"] = px["cedear_ticker"].astype(str).str.upper()

    quotes = local_quotes.copy()
    if quotes.empty:
        quotes = pd.DataFrame({"cedear_ticker": base["cedear_ticker"]})
    quotes["cedear_ticker"] = quotes["cedear_ticker"].astype(str).str.upper()
    out = base.merge(px, on="cedear_ticker", how="left").merge(quotes, on="cedear_ticker", how="left")

    if ratio_registry is not None and not ratio_registry.empty:
        ratios = ratio_registry.copy()
        ratios["cedear_ticker"] = ratios["cedear_ticker"].astype(str).str.upper()
        out = out.merge(ratios, on="cedear_ticker", how="left")
    else:
        out["comafi_ratio_multiplier"] = np.nan
        out["comafi_ratio_text"] = None
        out["ratio_conflict"] = False

    if ccl_reference is not None and not ccl_reference.empty:
        refs = ccl_reference.copy()
        refs["cedear_ticker"] = refs["cedear_ticker"].astype(str).str.upper()
        out = out.merge(refs, on="cedear_ticker", how="left")
    else:
        out["ccl_reference_mark"] = np.nan

    for col in ("universe_ratio", "comafi_ratio_multiplier", "last_price_ars", "bid_ars", "ask_ars", "last_close", "ccl_reference_mark"):
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")

    conflict = out.get("ratio_conflict", pd.Series(False, index=out.index)).fillna(False).astype(bool)
    comafi_ok = out["comafi_ratio_multiplier"].gt(0) & ~conflict
    out["ratio_status"] = "RATIO_UNVERIFIED_COMAFI"
    out.loc[comafi_ok, "ratio_status"] = "RATIO_VALIDATED_COMAFI"
    out.loc[conflict, "ratio_status"] = "RATIO_BLOCKED_CONFLICT"
    out["ratio_used"] = out["comafi_ratio_multiplier"].where(comafi_ok, out["universe_ratio"])
    out["ratio_deviation_vs_universe_pct"] = (
        out["comafi_ratio_multiplier"] / out["universe_ratio"] - 1.0
    ).where(comafi_ok & out["universe_ratio"].gt(0))

    raw_mid = (out["bid_ars"] + out["ask_ars"]) / 2.0
    raw_spread = (out["ask_ars"] - out["bid_ars"]) / raw_mid
    sane_book = _book_sanity(out)
    out["book_sanity_status"] = "BOOK_INVALID_SANITY"
    out.loc[sane_book, "book_sanity_status"] = "BOOK_SANITY_PASS"
    out.loc[out["bid_ars"].isna() | out["ask_ars"].isna(), "book_sanity_status"] = "BOOK_UNAVAILABLE"
    out["validated_mid_ars"] = raw_mid.where(sane_book)
    out["spread_ars"] = (out["ask_ars"] - out["bid_ars"]).where(sane_book)
    out["spread_pct"] = raw_spread.where(sane_book)
    out["analytical_local_ref_ars"] = out["validated_mid_ars"].fillna(out["last_price_ars"])

    session_status = argentina_market_session_status(now)
    out["market_session_status"] = session_status
    out["execution_book_status"] = "BOOK_NOT_EXECUTABLE_OUTSIDE_SESSION"
    if session_status == "SESSION_OPEN_BY_CLOCK":
        out["execution_book_status"] = "BOOK_INVALID_OR_UNAVAILABLE"
        out.loc[sane_book, "execution_book_status"] = "BOOK_EXECUTABLE_BY_SANITY"
    executable = sane_book & (session_status == "SESSION_OPEN_BY_CLOCK")
    out["executable_buy_ars"] = out["ask_ars"].where(executable)
    out["executable_sell_ars"] = out["bid_ars"].where(executable)
    out["effective_executable_buy_ars"] = out["executable_buy_ars"] * (1.0 + brokerage_rate)
    out["effective_executable_sell_ars"] = out["executable_sell_ars"] * (1.0 - brokerage_rate)
    out["executable_roundtrip_friction_pct"] = (
        out["effective_executable_buy_ars"] / out["effective_executable_sell_ars"] - 1.0
    ).where(out["effective_executable_sell_ars"].gt(0))
    out["reference_buy_with_commission_ars"] = out["last_price_ars"] * (1.0 + brokerage_rate)
    out["reference_sell_after_commission_ars"] = out["last_price_ars"] * (1.0 - brokerage_rate)

    valid_ccl = (
        out["analytical_local_ref_ars"].gt(0)
        & out["ratio_used"].gt(0)
        & out["last_close"].gt(0)
        & out["currency"].eq("USD")
        & ~conflict
    )
    out["implied_ccl"] = np.nan
    out.loc[valid_ccl, "implied_ccl"] = (
        out.loc[valid_ccl, "analytical_local_ref_ars"] * out.loc[valid_ccl, "ratio_used"] / out.loc[valid_ccl, "last_close"]
    )

    # Primary cross-check: robust market CCL from the cross-section of official Comafi ratios.
    consensus_pool = out.loc[
        valid_ccl & out["ratio_status"].eq("RATIO_VALIDATED_COMAFI") & out["implied_ccl"].gt(0),
        "implied_ccl",
    ]
    market_ccl = float(consensus_pool.median()) if not consensus_pool.empty else np.nan
    out["market_ccl_reference"] = market_ccl
    out["ccl_deviation_vs_market_pct"] = (out["implied_ccl"] / market_ccl - 1.0) if np.isfinite(market_ccl) and market_ccl > 0 else np.nan
    market_abs_dev = out["ccl_deviation_vs_market_pct"].abs()
    out["market_ccl_crosscheck_status"] = "MARKET_CCL_CROSSCHECK_UNAVAILABLE"
    out.loc[market_abs_dev.le(0.05), "market_ccl_crosscheck_status"] = "MARKET_CCL_CROSSCHECK_PASS"
    out.loc[market_abs_dev.gt(0.05) & market_abs_dev.le(0.10), "market_ccl_crosscheck_status"] = "MARKET_CCL_CROSSCHECK_WARNING"
    out.loc[market_abs_dev.gt(0.10), "market_ccl_crosscheck_status"] = "MARKET_CCL_CROSSCHECK_BLOCKED"

    # Secondary diagnostic only: Data912 per-ticker CCL can be internally inconsistent for some ADRs/ratios.
    out["ccl_deviation_vs_data912_pct"] = (
        out["implied_ccl"] / out["ccl_reference_mark"] - 1.0
    ).where(out["implied_ccl"].gt(0) & out["ccl_reference_mark"].gt(0))
    data912_abs_dev = out["ccl_deviation_vs_data912_pct"].abs()
    out["data912_ccl_diagnostic_status"] = "DATA912_CCL_DIAGNOSTIC_UNAVAILABLE"
    out.loc[data912_abs_dev.le(0.05), "data912_ccl_diagnostic_status"] = "DATA912_CCL_DIAGNOSTIC_ALIGNED"
    out.loc[data912_abs_dev.gt(0.05) & data912_abs_dev.le(0.10), "data912_ccl_diagnostic_status"] = "DATA912_CCL_DIAGNOSTIC_WARNING"
    out.loc[data912_abs_dev.gt(0.10), "data912_ccl_diagnostic_status"] = "DATA912_CCL_DIAGNOSTIC_DIVERGENT"

    out["local_price_status"] = "LOCAL_PRICE_BLOCKED"
    out.loc[out["last_price_ars"].gt(0), "local_price_status"] = "LOCAL_PRICE_READY"

    out["ccl_status"] = "CCL_BLOCKED"
    ccl_calc = out["implied_ccl"].gt(0)
    out.loc[ccl_calc, "ccl_status"] = "CCL_READY_UNVERIFIED"
    out.loc[
        ccl_calc & out["ratio_status"].eq("RATIO_VALIDATED_COMAFI") & out["market_ccl_crosscheck_status"].eq("MARKET_CCL_CROSSCHECK_PASS"),
        "ccl_status",
    ] = "CCL_READY_VALIDATED"
    out.loc[
        ccl_calc & out["ratio_status"].eq("RATIO_VALIDATED_COMAFI") & out["market_ccl_crosscheck_status"].eq("MARKET_CCL_CROSSCHECK_WARNING"),
        "ccl_status",
    ] = "CCL_WARNING_MARKET_DEVIATION"
    out.loc[out["market_ccl_crosscheck_status"].eq("MARKET_CCL_CROSSCHECK_BLOCKED"), "ccl_status"] = "CCL_BLOCKED_MARKET_DEVIATION"
    out.loc[conflict, "ccl_status"] = "CCL_BLOCKED_RATIO_CONFLICT"

    out["valuation_g4_local_gate"] = "BLOCKED"
    pass_base = out["local_price_status"].eq("LOCAL_PRICE_READY") & out["ratio_status"].eq("RATIO_VALIDATED_COMAFI")
    out.loc[pass_base & out["ccl_status"].eq("CCL_READY_VALIDATED"), "valuation_g4_local_gate"] = "PASS"
    out.loc[pass_base & out["ccl_status"].eq("CCL_WARNING_MARKET_DEVIATION"), "valuation_g4_local_gate"] = "PASS_WITH_WARNING"

    out["loaded_at_layer"] = datetime.now(timezone.utc).isoformat()
    return out.sort_values("cedear_ticker").reset_index(drop=True)


def build_local_market_metrics(frame: pd.DataFrame) -> dict:
    total = len(frame)
    price_ready = int((frame["local_price_status"] == "LOCAL_PRICE_READY").sum())
    sane_books = int((frame["book_sanity_status"] == "BOOK_SANITY_PASS").sum())
    executable_books = int((frame["execution_book_status"] == "BOOK_EXECUTABLE_BY_SANITY").sum())
    ratio_validated = int((frame["ratio_status"] == "RATIO_VALIDATED_COMAFI").sum())
    ccl_validated = int((frame["ccl_status"] == "CCL_READY_VALIDATED").sum())
    ccl_warning = int((frame["ccl_status"] == "CCL_WARNING_MARKET_DEVIATION").sum())
    ccl_blocked = int((frame["ccl_status"] == "CCL_BLOCKED_MARKET_DEVIATION").sum())
    g4_pass = int(frame["valuation_g4_local_gate"].isin(["PASS", "PASS_WITH_WARNING"]).sum())
    market_ref = pd.to_numeric(frame.get("market_ccl_reference"), errors="coerce").dropna()
    return {
        "Eligible_Count": total,
        "Local_Price_Ready_Count": price_ready,
        "Book_Sanity_Pass_Count": sane_books,
        "Executable_Book_Count": executable_books,
        "Comafi_Ratio_Validated_Count": ratio_validated,
        "Implied_CCL_Validated_Count": ccl_validated,
        "Implied_CCL_Warning_Count": ccl_warning,
        "CCL_Blocked_Market_Deviation_Count": ccl_blocked,
        "Valuation_G4_Local_Gate_Pass_Count": g4_pass,
        "Market_CCL_Reference": float(market_ref.iloc[0]) if not market_ref.empty else None,
        "Local_Price_Coverage_Pct": round(price_ready / total * 100, 4) if total else 0.0,
        "Comafi_Ratio_Coverage_Pct": round(ratio_validated / total * 100, 4) if total else 0.0,
        "Validated_CCL_Coverage_Pct": round(ccl_validated / total * 100, 4) if total else 0.0,
        "Valuation_G4_Local_Gate_Pass_Pct": round(g4_pass / total * 100, 4) if total else 0.0,
        "Market_Session_Status": frame["market_session_status"].iloc[0] if total else None,
        "PASS_LOCAL_PRICE_LAYER": price_ready == total and total > 0,
        "PASS_COMAFI_RATIO_LAYER": ratio_validated == total and total > 0,
        "PASS_VALIDATED_CCL_LAYER": (ccl_validated + ccl_warning) == total and total > 0,
    }
