from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml


DEFAULT_PROVIDER = "canonical"


def load_alias_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, dict):
        raise ValueError("Alias config must be a mapping")
    return payload


def normalize_provider_symbol(
    underlying_ticker: str,
    provider: str,
    aliases: dict[str, Any],
    underlying_market: str | None = None,
) -> str:
    ticker = underlying_ticker.strip()
    provider_aliases = aliases.get("providers", {}).get(provider, {})

    if ticker in provider_aliases:
        return str(provider_aliases[ticker])

    market_rules = aliases.get("market_suffixes", {}).get(provider, {})
    if underlying_market and underlying_market in market_rules:
        suffix = str(market_rules[underlying_market])
        if suffix and not ticker.endswith(suffix):
            return f"{ticker}{suffix}"

    return ticker


def build_symbol_map(
    eligible_universe: pd.DataFrame,
    aliases: dict[str, Any],
    providers: tuple[str, ...] = ("yahoo", "stooq", "iol", "data912"),
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []

    for row in eligible_universe.to_dict(orient="records"):
        base = {
            "cedear_ticker": row["cedear_ticker"],
            "canonical_underlying": row["underlying_ticker"],
            "underlying_market": row.get("underlying_market"),
            "instrument_type": row.get("instrument_type"),
            "ratio": row.get("ratio"),
            "mandate_exception": row.get("mandate_exception", False),
            "mapping_status": "RESOLVED",
            "mapping_version": aliases.get("mapping_version", "1.0"),
        }

        for provider in providers:
            base[f"{provider}_symbol"] = normalize_provider_symbol(
                str(row["underlying_ticker"]),
                provider,
                aliases,
                row.get("underlying_market"),
            )

        records.append(base)

    return pd.DataFrame(records).sort_values("cedear_ticker").reset_index(drop=True)
