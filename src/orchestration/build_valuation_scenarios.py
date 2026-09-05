from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from src.connectors.finnhub import FinnhubConnector
from src.valuation.equity_engine import build_equity_scenario
from src.valuation.etf_engine import build_etf_scenario


def _is_etf(instrument_type: object, issuer_name: object) -> bool:
    text = f"{instrument_type or ''} {issuer_name or ''}".upper()
    return any(token in text for token in ("ETF", "ETP", "EXCHANGE TRADED FUND"))


def _price_map(prices: pd.DataFrame) -> dict[str, float]:
    frame = prices.copy()
    ticker_col = "cedear_ticker" if "cedear_ticker" in frame.columns else "ticker"
    if ticker_col not in frame.columns:
        return {}
    price_col = None
    for candidate in ("last_close", "close", "adjusted_close", "current_price"):
        if candidate in frame.columns:
            price_col = candidate
            break
    if price_col is None:
        return {}
    frame[price_col] = pd.to_numeric(frame[price_col], errors="coerce")
    return frame.dropna(subset=[price_col]).set_index(ticker_col)[price_col].astype(float).to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical Equity + ETF valuation scenarios")
    parser.add_argument("--universe", required=True)
    parser.add_argument("--underlying-prices", required=True)
    parser.add_argument("--policy", default="config/valuation_policy.yml")
    parser.add_argument("--output-dir", default="data/canonical/valuation")
    args = parser.parse_args()

    universe = pd.read_parquet(args.universe)
    prices = pd.read_parquet(args.underlying_prices)
    policy = yaml.safe_load(Path(args.policy).read_text(encoding="utf-8")) or {}
    connector = FinnhubConnector()
    prices_by_cedear = _price_map(prices)

    rows: list[dict] = []
    equity_count = 0
    etf_count = 0
    for _, item in universe.sort_values("cedear_ticker").iterrows():
        cedear = str(item.get("cedear_ticker") or "").upper()
        underlying = str(item.get("underlying_ticker") or cedear).upper()
        current_price = prices_by_cedear.get(cedear)
        is_etf = _is_etf(item.get("instrument_type"), item.get("issuer_name"))
        if is_etf:
            etf_count += 1
            scenario = build_etf_scenario(underlying, current_price, connector, policy)
            engine_type = "ETF"
        else:
            equity_count += 1
            scenario = build_equity_scenario(underlying, current_price, connector, policy)
            engine_type = "EQUITY"
        scenario.update({
            "cedear_ticker": cedear,
            "underlying_ticker": underlying,
            "instrument_type": item.get("instrument_type"),
            "valuation_engine_type": engine_type,
            "methodology_version": policy.get("methodology_version", "VAL-1.0"),
        })
        rows.append(scenario)

    result = pd.DataFrame(rows)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_df = result.copy()
    for col in ("blockers", "holding_error_counts"):
        if col in json_df.columns:
            json_df[col] = json_df[col].map(lambda x: x if isinstance(x, (list, dict)) else ([] if col == "blockers" else {}))
    json_df.to_json(out / "valuation_scenarios.json", orient="records", indent=2, force_ascii=False)

    parquet = result.copy()
    for col in ("blockers", "holding_error_counts"):
        if col in parquet.columns:
            parquet[col] = parquet[col].map(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
    parquet.to_parquet(out / "valuation_scenarios.parquet", index=False)

    ready = int((result["valuation_status"] == "VALUATION_READY").sum()) if not result.empty else 0
    blocked = int((result["valuation_status"] == "BLOCKED_BY_DATA").sum()) if not result.empty else 0
    equity_ready = int(((result["valuation_engine_type"] == "EQUITY") & (result["valuation_status"] == "VALUATION_READY")).sum()) if not result.empty else 0
    etf_ready = int(((result["valuation_engine_type"] == "ETF") & (result["valuation_status"] == "VALUATION_READY")).sum()) if not result.empty else 0
    metrics = {
        "layer": "Canonical Valuation Scenarios",
        "methodology_version": policy.get("methodology_version", "VAL-1.0"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finnhub_configured": connector.configured,
        "ticker_count": int(len(result)),
        "equity_count": equity_count,
        "etf_count": etf_count,
        "ready_count": ready,
        "blocked_count": blocked,
        "equity_ready_count": equity_ready,
        "etf_ready_count": etf_ready,
        "coverage_pct": round(ready / len(result) * 100.0, 2) if len(result) else 0.0,
        "freshness_policy": policy.get("freshness", {}),
        "pass_full_valuation": bool(len(result) > 0 and ready == len(result)),
        "note": "All 305 rows are emitted. Missing/stale material data remains BLOCKED_BY_DATA; no technical-price proxy is substituted for valuation.",
    }
    (out / "valuation_scenarios_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
