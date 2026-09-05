from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.connectors.data912 import Data912CedearConnector
from src.connectors.iol import IOLCedearConnector
from src.market_data.cedear_local import build_local_market_layer, build_local_market_metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Build CEDEAR Local Market + implied CCL layer")
    parser.add_argument("--universe", required=True)
    parser.add_argument("--underlying-prices", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--brokerage-rate", type=float, default=0.006)
    args = parser.parse_args()

    universe = pd.read_parquet(args.universe)
    underlying = pd.read_parquet(args.underlying_prices)

    iol = IOLCedearConnector()
    data912 = Data912CedearConnector()
    data912_panel = data912.get_panel()

    rows = []
    provider_stats = {"iol": 0, "data912": 0, "blocked": 0}
    for ticker in universe["cedear_ticker"].astype(str).str.upper():
        quote = None
        attempts = []
        if iol.configured:
            try:
                quote = iol.get_quote(ticker)
                attempts.append({"provider":"iol","status":"SUCCESS"})
            except Exception as exc:
                attempts.append({"provider":"iol","status":"ERROR","error":f"{type(exc).__name__}: {exc}"})
        else:
            attempts.append({"provider":"iol","status":"SKIPPED_NOT_CONFIGURED"})

        fallback = data912_panel.get(ticker)
        if quote is None or not quote.get("last_price_ars"):
            if fallback:
                quote = dict(fallback)
                attempts.append({"provider":"data912","status":"SUCCESS"})
            else:
                attempts.append({"provider":"data912","status":"NO_DATA"})

        if quote is None:
            quote = {"cedear_ticker":ticker,"last_price_ars":None,"bid_ars":None,"ask_ars":None,"nominal_volume":None,"cash_volume_ars":None,"market_timestamp":None,"provider":None,"provider_tier":None,"source_ref":None,"loaded_at":datetime.now(timezone.utc).isoformat(),"raw_keys":[]}
            provider_stats["blocked"] += 1
        else:
            provider_stats[quote["provider"]] = provider_stats.get(quote["provider"], 0) + 1
        quote["attempt_log"] = attempts
        rows.append(quote)

    local_quotes = pd.DataFrame(rows)
    layer = build_local_market_layer(universe, underlying, local_quotes, brokerage_rate=args.brokerage_rate)
    metrics = build_local_market_metrics(layer)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    layer.to_json(out / "cedear_local_market.json", orient="records", indent=2, force_ascii=False)
    parquet = layer.copy()
    for col in ("raw_keys","attempt_log"):
        if col in parquet.columns:
            parquet[col] = parquet[col].map(lambda x: json.dumps(x, ensure_ascii=False))
    parquet.to_parquet(out / "cedear_local_market.parquet", index=False)

    ccl = layer[[c for c in ["cedear_ticker","ratio","last_price_ars","bid_ars","ask_ars","mid_ars","last_close","currency","implied_ccl","spread_pct","roundtrip_friction_pct","provider","ccl_status"] if c in layer.columns]].copy()
    ccl.to_json(out / "cedear_implied_ccl.json", orient="records", indent=2, force_ascii=False)
    ccl.to_parquet(out / "cedear_implied_ccl.parquet", index=False)

    manifest = {
        "layer":"CEDEAR Local Market + Implied CCL",
        "version":"1.0",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "brokerage_rate_per_side":args.brokerage_rate,
        "ratio_convention":"ratio = CEDEAR units per 1 underlying unit; implied_ccl = local_ARS * ratio / underlying_USD",
        "provider_priority":["IOL","Data912"],
        "provider_stats":provider_stats,
        **metrics,
    }
    (out / "cedear_local_market_metrics.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if metrics["Local_Price_Ready_Count"] == 0:
        raise SystemExit("No local CEDEAR prices acquired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
