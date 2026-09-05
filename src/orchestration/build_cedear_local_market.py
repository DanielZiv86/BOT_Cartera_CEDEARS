from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.connectors.comafi import ComafiRatioConnector
from src.connectors.data912 import Data912CedearConnector
from src.connectors.iol import IOLCedearConnector
from src.market_data.cedear_local import build_local_market_layer, build_local_market_metrics
from src.market_data.local_market_diagnostics import build_local_market_blocker_diagnostics


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
    comafi = ComafiRatioConnector()

    data912_panel = data912.get_panel()
    ccl_panel = data912.get_ccl_panel()
    ratio_panel = comafi.get_ratios()

    rows = []
    provider_stats = {"iol": 0, "data912": 0, "blocked": 0}
    for ticker in universe["cedear_ticker"].astype(str).str.upper():
        quote = None
        attempts = []
        if iol.configured:
            try:
                quote = iol.get_quote(ticker)
                attempts.append({"provider": "iol", "status": "SUCCESS"})
            except Exception as exc:
                attempts.append({"provider": "iol", "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
        else:
            attempts.append({"provider": "iol", "status": "SKIPPED_NOT_CONFIGURED"})

        fallback = data912_panel.get(ticker)
        if quote is None or not quote.get("last_price_ars"):
            if fallback:
                quote = dict(fallback)
                attempts.append({"provider": "data912", "status": "SUCCESS"})
            else:
                attempts.append({"provider": "data912", "status": "NO_DATA"})

        if quote is None:
            quote = {
                "cedear_ticker": ticker,
                "last_price_ars": None,
                "bid_ars": None,
                "ask_ars": None,
                "nominal_volume": None,
                "cash_volume_ars": None,
                "market_timestamp": None,
                "provider": None,
                "provider_tier": None,
                "source_ref": None,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
                "raw_keys": [],
            }
            provider_stats["blocked"] += 1
        else:
            provider_stats[quote["provider"]] = provider_stats.get(quote["provider"], 0) + 1
        quote["attempt_log"] = attempts
        rows.append(quote)

    local_quotes = pd.DataFrame(rows)
    ratio_registry = pd.DataFrame(list(ratio_panel.values()))
    ccl_reference = pd.DataFrame(list(ccl_panel.values()))

    layer = build_local_market_layer(
        universe,
        underlying,
        local_quotes,
        ratio_registry=ratio_registry,
        ccl_reference=ccl_reference,
        brokerage_rate=args.brokerage_rate,
    )
    metrics = build_local_market_metrics(layer)
    blocker_diagnostics = build_local_market_blocker_diagnostics(layer)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    layer.to_json(out / "cedear_local_market.json", orient="records", indent=2, force_ascii=False)
    parquet = layer.copy()
    for col in ("raw_keys", "attempt_log", "conflicting_ratio_texts"):
        if col in parquet.columns:
            parquet[col] = parquet[col].map(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
    parquet.to_parquet(out / "cedear_local_market.parquet", index=False)

    ccl_cols = [
        "cedear_ticker", "universe_ratio", "comafi_ratio_text", "comafi_ratio_multiplier", "ratio_used", "ratio_status",
        "last_price_ars", "bid_ars", "ask_ars", "validated_mid_ars", "analytical_local_ref_ars", "last_close", "currency",
        "implied_ccl", "market_ccl_reference", "ccl_deviation_vs_market_pct", "market_ccl_crosscheck_status", "ccl_status",
        "ccl_reference_mark", "ccl_deviation_vs_data912_pct", "data912_ccl_diagnostic_status",
        "spread_pct", "book_sanity_status", "market_session_status", "execution_book_status",
        "effective_executable_buy_ars", "effective_executable_sell_ars", "executable_roundtrip_friction_pct",
        "reference_buy_with_commission_ars", "reference_sell_after_commission_ars", "valuation_g4_local_gate", "provider",
    ]
    ccl = layer[[c for c in ccl_cols if c in layer.columns]].copy()
    ccl.to_json(out / "cedear_implied_ccl.json", orient="records", indent=2, force_ascii=False)
    ccl.to_parquet(out / "cedear_implied_ccl.parquet", index=False)

    ratio_audit_cols = [
        "cedear_ticker", "universe_ratio", "comafi_ratio_text", "comafi_ratio_multiplier", "ratio_used",
        "ratio_deviation_vs_universe_pct", "ratio_status", "ratio_conflict", "comafi_program_name",
        "comafi_underlying_ticker", "comafi_caja_code", "comafi_source_ref",
    ]
    ratio_audit = layer[[c for c in ratio_audit_cols if c in layer.columns]].copy()
    ratio_audit.to_json(out / "comafi_ratio_audit.json", orient="records", indent=2, force_ascii=False)
    ratio_audit.to_parquet(out / "comafi_ratio_audit.parquet", index=False)

    (out / "local_market_blockers.json").write_text(
        json.dumps(blocker_diagnostics, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    manifest = {
        "layer": "CEDEAR Local Market + Implied CCL",
        "version": "1.3",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "brokerage_rate_per_side": args.brokerage_rate,
        "ratio_convention": "Comafi CEDEAR:underlying multiplier = numerator/denominator; implied_ccl = local_ARS * multiplier / underlying_USD",
        "provider_priority": ["IOL", "Data912"],
        "ratio_primary_source": "Banco Comafi Programas CEDEARs current registry",
        "ccl_primary_validation": "robust median of cross-sectional implied CCL using Comafi-validated ratios",
        "ccl_secondary_diagnostic": "Data912 /live/ccl per ticker; diagnostic only, never sole blocking source",
        "execution_policy": "bid/ask is executable only during Argentina market session and after sanity validation",
        "provider_stats": provider_stats,
        "comafi_ratio_registry_count": len(ratio_panel),
        "data912_ccl_reference_count": len(ccl_panel),
        "blocker_diagnostics": blocker_diagnostics,
        **metrics,
    }
    (out / "cedear_local_market_metrics.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if metrics["Local_Price_Ready_Count"] == 0:
        raise SystemExit("No local CEDEAR prices acquired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
