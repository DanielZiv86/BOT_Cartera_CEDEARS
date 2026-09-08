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
from src.market_data.local_market_recovery import recover_analytical_local_market


def _identity_candidates(row: pd.Series) -> list[str]:
    """Canonical-first local-market identities with audited legacy fallbacks."""
    candidates: list[str] = []
    for column in ("cedear_ticker", "legacy_cedear_ticker"):
        value = row.get(column)
        if value is None or pd.isna(value):
            continue
        symbol = str(value).strip().upper()
        if symbol and symbol not in candidates:
            candidates.append(symbol)
    return candidates


def _lookup_panel(panel: dict, candidates: list[str]):
    for symbol in candidates:
        if symbol in panel:
            return panel[symbol], symbol
    return None, None


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
    normalized_ratios = []
    normalized_ccl = []
    provider_stats = {"iol": 0, "data912": 0, "blocked": 0}
    for _, universe_row in universe.iterrows():
        ticker = str(universe_row.get("cedear_ticker") or "").strip().upper()
        candidates = _identity_candidates(universe_row)
        quote = None
        resolved_symbol = None
        attempts = []
        if iol.configured:
            for symbol in candidates:
                try:
                    quote = iol.get_quote(symbol)
                    attempts.append({"provider": "iol", "symbol": symbol, "status": "SUCCESS"})
                    if quote and quote.get("last_price_ars"):
                        resolved_symbol = symbol
                        break
                except Exception as exc:
                    attempts.append({"provider": "iol", "symbol": symbol, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
        else:
            attempts.append({"provider": "iol", "status": "SKIPPED_NOT_CONFIGURED"})

        fallback, fallback_symbol = _lookup_panel(data912_panel, candidates)
        if quote is None or not quote.get("last_price_ars"):
            if fallback:
                quote = dict(fallback)
                resolved_symbol = fallback_symbol
                attempts.append({"provider": "data912", "symbol": fallback_symbol, "status": "SUCCESS"})
            else:
                attempts.append({"provider": "data912", "symbols": candidates, "status": "NO_DATA"})

        if quote is None:
            quote = {"last_price_ars": None, "bid_ars": None, "ask_ars": None, "nominal_volume": None, "cash_volume_ars": None, "market_timestamp": None, "provider": None, "provider_tier": None, "source_ref": None, "loaded_at": datetime.now(timezone.utc).isoformat(), "raw_keys": []}
            provider_stats["blocked"] += 1
        else:
            provider_stats[quote["provider"]] = provider_stats.get(quote["provider"], 0) + 1
        quote["cedear_ticker"] = ticker
        quote["market_identity_resolved"] = resolved_symbol
        quote["market_identity_candidates"] = candidates
        quote["attempt_log"] = attempts
        rows.append(quote)

        ratio, ratio_symbol = _lookup_panel(ratio_panel, candidates)
        if ratio:
            ratio = dict(ratio); ratio["cedear_ticker"] = ticker; ratio["ratio_identity_resolved"] = ratio_symbol
            normalized_ratios.append(ratio)
        ccl, ccl_symbol = _lookup_panel(ccl_panel, candidates)
        if ccl:
            ccl = dict(ccl); ccl["cedear_ticker"] = ticker; ccl["ccl_identity_resolved"] = ccl_symbol
            normalized_ccl.append(ccl)

    local_quotes = pd.DataFrame(rows)
    ratio_registry = pd.DataFrame(normalized_ratios)
    ccl_reference = pd.DataFrame(normalized_ccl)
    layer = build_local_market_layer(universe, underlying, local_quotes, ratio_registry=ratio_registry, ccl_reference=ccl_reference, brokerage_rate=args.brokerage_rate)
    layer = recover_analytical_local_market(layer)
    metrics = build_local_market_metrics(layer)
    blocker_diagnostics = build_local_market_blocker_diagnostics(layer)

    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    layer.to_json(out / "cedear_local_market.json", orient="records", indent=2, force_ascii=False)
    parquet = layer.copy()
    for col in ("raw_keys", "attempt_log", "conflicting_ratio_texts", "market_identity_candidates"):
        if col in parquet.columns:
            parquet[col] = parquet[col].map(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
    parquet.to_parquet(out / "cedear_local_market.parquet", index=False)

    ccl_cols = ["cedear_ticker", "universe_ratio", "comafi_ratio_text", "comafi_ratio_multiplier", "ratio_used", "ratio_status", "ratio_validation_method", "canonical_ratio_ccl_deviation_pct", "last_price_ars", "bid_ars", "ask_ars", "validated_mid_ars", "observed_analytical_local_ref_ars", "analytical_local_ref_ars", "analytical_reference_method", "analytical_recovery_applied", "last_close", "currency", "implied_ccl", "market_ccl_reference", "ccl_deviation_vs_market_pct", "market_ccl_crosscheck_status", "ccl_status", "ccl_reference_mark", "ccl_deviation_vs_data912_pct", "data912_ccl_diagnostic_status", "spread_pct", "book_sanity_status", "market_session_status", "execution_book_status", "effective_executable_buy_ars", "effective_executable_sell_ars", "executable_roundtrip_friction_pct", "reference_buy_with_commission_ars", "reference_sell_after_commission_ars", "valuation_g4_local_gate", "provider", "market_identity_resolved"]
    ccl = layer[[c for c in ccl_cols if c in layer.columns]].copy(); ccl.to_json(out / "cedear_implied_ccl.json", orient="records", indent=2, force_ascii=False); ccl.to_parquet(out / "cedear_implied_ccl.parquet", index=False)
    ratio_audit_cols = ["cedear_ticker", "universe_ratio", "comafi_ratio_text", "comafi_ratio_multiplier", "ratio_used", "ratio_deviation_vs_universe_pct", "ratio_status", "ratio_validation_method", "canonical_ratio_ccl_deviation_pct", "ratio_conflict", "comafi_program_name", "comafi_underlying_ticker", "comafi_caja_code", "comafi_source_ref", "ratio_identity_resolved"]
    ratio_audit = layer[[c for c in ratio_audit_cols if c in layer.columns]].copy(); ratio_audit.to_json(out / "comafi_ratio_audit.json", orient="records", indent=2, force_ascii=False); ratio_audit.to_parquet(out / "comafi_ratio_audit.parquet", index=False)
    (out / "local_market_blockers.json").write_text(json.dumps(blocker_diagnostics, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {"layer": "CEDEAR Local Market + Implied CCL", "version": "1.5", "created_at": datetime.now(timezone.utc).isoformat(), "brokerage_rate_per_side": args.brokerage_rate, "identity_policy": "CANONICAL_CEDEAR_THEN_AUDITED_LEGACY_CEDEAR", "provider_priority": ["IOL", "Data912"], "provider_stats": provider_stats, "comafi_ratio_registry_count": len(ratio_panel), "data912_ccl_reference_count": len(ccl_panel), "blocker_diagnostics": blocker_diagnostics, **metrics}
    (out / "cedear_local_market_metrics.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if metrics["Local_Price_Ready_Count"] == 0:
        raise SystemExit("No local CEDEAR prices acquired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
