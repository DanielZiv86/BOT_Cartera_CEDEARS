from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd


def build_local_market_layer(
    universe: pd.DataFrame,
    underlying_prices: pd.DataFrame,
    local_quotes: pd.DataFrame,
    brokerage_rate: float = 0.006,
) -> pd.DataFrame:
    required_u = {"cedear_ticker", "ratio"}
    required_p = {"cedear_ticker", "last_close", "currency", "freshness_status"}
    if not required_u.issubset(universe.columns):
        raise ValueError("universe missing cedear_ticker/ratio")
    if not required_p.issubset(underlying_prices.columns):
        raise ValueError("underlying prices missing required fields")

    base = universe[[c for c in universe.columns if c in {"cedear_ticker","ratio","instrument_type","underlying_market","underlying_ticker","canonical_underlying"}]].copy()
    base["cedear_ticker"] = base["cedear_ticker"].astype(str).str.upper()
    px = underlying_prices[[c for c in underlying_prices.columns if c in {"cedear_ticker","last_close","last_close_date","currency","freshness_status","provider_selected"}]].copy()
    px["cedear_ticker"] = px["cedear_ticker"].astype(str).str.upper()
    quotes = local_quotes.copy()
    if not quotes.empty:
        quotes["cedear_ticker"] = quotes["cedear_ticker"].astype(str).str.upper()

    out = base.merge(px, on="cedear_ticker", how="left").merge(quotes, on="cedear_ticker", how="left")
    out["ratio"] = pd.to_numeric(out["ratio"], errors="coerce")
    out["last_price_ars"] = pd.to_numeric(out.get("last_price_ars"), errors="coerce")
    out["bid_ars"] = pd.to_numeric(out.get("bid_ars"), errors="coerce")
    out["ask_ars"] = pd.to_numeric(out.get("ask_ars"), errors="coerce")
    out["last_close"] = pd.to_numeric(out["last_close"], errors="coerce")

    mid = (out["bid_ars"] + out["ask_ars"]) / 2.0
    out["mid_ars"] = mid.where((out["bid_ars"] > 0) & (out["ask_ars"] > 0))
    out["spread_ars"] = (out["ask_ars"] - out["bid_ars"]).where(out["mid_ars"].notna())
    out["spread_pct"] = (out["spread_ars"] / out["mid_ars"]).where(out["mid_ars"] > 0)

    ref_local = out["mid_ars"].fillna(out["last_price_ars"])
    valid_ccl = (ref_local > 0) & (out["ratio"] > 0) & (out["last_close"] > 0) & (out["currency"] == "USD")
    out["implied_ccl"] = None
    out.loc[valid_ccl, "implied_ccl"] = (
        ref_local[valid_ccl] * out.loc[valid_ccl, "ratio"] / out.loc[valid_ccl, "last_close"]
    )
    out["implied_ccl"] = pd.to_numeric(out["implied_ccl"], errors="coerce")

    out["buy_price_ars"] = out["ask_ars"].fillna(out["last_price_ars"])
    out["sell_price_ars"] = out["bid_ars"].fillna(out["last_price_ars"])
    out["effective_buy_ars"] = out["buy_price_ars"] * (1.0 + brokerage_rate)
    out["effective_sell_ars"] = out["sell_price_ars"] * (1.0 - brokerage_rate)
    out["roundtrip_friction_pct"] = (out["effective_buy_ars"] / out["effective_sell_ars"] - 1.0).where(out["effective_sell_ars"] > 0)

    out["book_status"] = "BOOK_UNAVAILABLE"
    out.loc[out["mid_ars"].notna(), "book_status"] = "BOOK_READY"
    out["local_price_status"] = "LOCAL_PRICE_BLOCKED"
    out.loc[out["last_price_ars"].notna() & (out["last_price_ars"] > 0), "local_price_status"] = "LOCAL_PRICE_READY"
    out["ccl_status"] = "CCL_BLOCKED"
    out.loc[out["implied_ccl"].notna() & (out["implied_ccl"] > 0), "ccl_status"] = "CCL_READY"
    out["loaded_at_layer"] = datetime.now(timezone.utc).isoformat()
    return out.sort_values("cedear_ticker").reset_index(drop=True)


def build_local_market_metrics(frame: pd.DataFrame) -> dict:
    total = len(frame)
    price_ready = int((frame["local_price_status"] == "LOCAL_PRICE_READY").sum())
    book_ready = int((frame["book_status"] == "BOOK_READY").sum())
    ccl_ready = int((frame["ccl_status"] == "CCL_READY").sum())
    return {
        "Eligible_Count": total,
        "Local_Price_Ready_Count": price_ready,
        "Book_Ready_Count": book_ready,
        "Implied_CCL_Ready_Count": ccl_ready,
        "Local_Price_Coverage_Pct": round(price_ready / total * 100, 4) if total else 0.0,
        "Book_Coverage_Pct": round(book_ready / total * 100, 4) if total else 0.0,
        "Implied_CCL_Coverage_Pct": round(ccl_ready / total * 100, 4) if total else 0.0,
        "PASS_LOCAL_PRICE_LAYER": price_ready == total and total > 0,
        "PASS_CCL_LAYER": ccl_ready == total and total > 0,
    }
