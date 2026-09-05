from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Iterable

import pandas as pd

from src.connectors.base import PriceConnector, PriceQuote


FRESH_MAX_AGE_DAYS = 3
STALE_MAX_AGE_DAYS = 10


def classify_freshness(close_date: date, as_of: date | None = None) -> str:
    as_of = as_of or date.today()
    age = (as_of - close_date).days
    if age <= FRESH_MAX_AGE_DAYS:
        return "PRICE_READY_FRESH"
    if age <= STALE_MAX_AGE_DAYS:
        return "PRICE_READY_STALE"
    return "PRICE_READY_STALE"


def acquire_underlying_prices(
    symbol_map: pd.DataFrame,
    connectors: Iterable[PriceConnector],
    as_of: date | None = None,
) -> pd.DataFrame:
    as_of = as_of or date.today()
    records: list[dict] = []

    for row in symbol_map.to_dict(orient="records"):
        attempts: list[dict] = []
        quote: PriceQuote | None = None
        selected_symbol: str | None = None

        for connector in connectors:
            provider_symbol = row.get(f"{connector.name}_symbol")
            if not provider_symbol:
                attempts.append({
                    "provider": connector.name,
                    "status": "SKIPPED_NO_PROVIDER_SYMBOL",
                })
                continue
            try:
                candidate = connector.get_last_close(
                    str(provider_symbol),
                    row.get("underlying_market"),
                )
            except Exception as exc:  # per-ticker fallback must continue
                attempts.append({
                    "provider": connector.name,
                    "provider_symbol": str(provider_symbol),
                    "status": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            if candidate is None:
                attempts.append({
                    "provider": connector.name,
                    "provider_symbol": str(provider_symbol),
                    "status": "NO_DATA",
                })
                continue

            quote = candidate
            selected_symbol = str(provider_symbol)
            attempts.append({
                "provider": connector.name,
                "provider_symbol": selected_symbol,
                "status": "SUCCESS",
            })
            break

        base = {
            "cedear_ticker": row.get("cedear_ticker"),
            "canonical_underlying": row.get("canonical_underlying"),
            "underlying_market": row.get("underlying_market"),
            "instrument_type": row.get("instrument_type"),
            "ratio": row.get("ratio"),
            "mandate_exception": bool(row.get("mandate_exception", False)),
            "mapping_status": row.get("mapping_status"),
            "mapping_version": row.get("mapping_version"),
            "attempt_log": attempts,
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "data_as_of": as_of.isoformat(),
        }

        if quote is None:
            base.update({
                "provider_symbol": selected_symbol,
                "last_close": None,
                "last_close_date": None,
                "prior_close": None,
                "currency": None,
                "provider_selected": None,
                "provider_tier": None,
                "source_ref": None,
                "data_confidence": "NONE",
                "freshness_status": "PRICE_BLOCKED",
                "blocker_reason": "ALL_CONFIGURED_PROVIDERS_FAILED",
            })
        else:
            quote_data = asdict(quote)
            base.update({
                "provider_symbol": quote_data["symbol"],
                "last_close": quote_data["close"],
                "last_close_date": quote_data["close_date"].isoformat(),
                "prior_close": quote_data["prior_close"],
                "currency": quote_data["currency"],
                "provider_selected": quote_data["source"],
                "provider_tier": quote_data["provider_tier"],
                "source_ref": quote_data["source_ref"],
                "data_confidence": quote_data["confidence"],
                "freshness_status": classify_freshness(quote_data["close_date"], as_of),
                "blocker_reason": None,
            })

        records.append(base)

    return pd.DataFrame(records).sort_values("cedear_ticker").reset_index(drop=True)


def build_price_metrics(frame: pd.DataFrame) -> dict:
    total = int(len(frame))
    fresh = int((frame["freshness_status"] == "PRICE_READY_FRESH").sum())
    stale = int((frame["freshness_status"] == "PRICE_READY_STALE").sum())
    blocked = int((frame["freshness_status"] == "PRICE_BLOCKED").sum())
    ready = fresh + stale
    providers = (
        frame["provider_selected"].fillna("NONE").value_counts().to_dict()
        if total else {}
    )
    return {
        "Eligible_Count": total,
        "Price_Ready_Fresh_Count": fresh,
        "Price_Ready_Stale_Count": stale,
        "Price_Blocked_Count": blocked,
        "Underlying_Price_Total_Ready_Count": ready,
        "Underlying_Price_Total_Ready_Pct": round((ready / total * 100), 4) if total else 0.0,
        "Fresh_Price_Coverage_Pct": round((fresh / total * 100), 4) if total else 0.0,
        "Provider_Distribution": providers,
        "PASS_UNDERLYING_PRICE_LAYER": ready == total and total > 0,
    }
