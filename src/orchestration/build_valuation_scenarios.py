from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from src.connectors.finnhub import FinnhubConnector
from src.connectors.issuer_holdings import IssuerHoldingsConnector
from src.connectors.non_equity_tracker import NonEquityTrackerConnector
from src.valuation.equity_engine import build_equity_scenario
from src.valuation.etf_engine import build_etf_scenario
from src.valuation.etf_issuer_engine import build_issuer_etf_scenario
from src.valuation.non_equity_tracker_engine import build_non_equity_tracker_scenario


def _is_etf(cedear_ticker: str, instrument_type: object, issuer_name: object, policy: dict) -> bool:
    text = f"{instrument_type or ''} {issuer_name or ''}".upper()
    if re.search(r"\bETF\b|\bETP\b|EXCHANGE\s+TRADED\s+FUND", text):
        return True
    overrides = policy.get("instrument_overrides", {}).get("etf_like_tickers", [])
    override_set = {str(t).strip().upper() for t in overrides if str(t).strip()}
    return cedear_ticker.upper() in override_set


def _price_map(prices: pd.DataFrame) -> dict[str, float]:
    frame = prices.copy()
    ticker_col = "cedear_ticker" if "cedear_ticker" in frame.columns else "ticker"
    if ticker_col not in frame.columns:
        return {}
    price_col = next((c for c in ("last_close", "close", "adjusted_close", "current_price") if c in frame.columns), None)
    if price_col is None:
        return {}
    frame[price_col] = pd.to_numeric(frame[price_col], errors="coerce")
    return frame.dropna(subset=[price_col]).set_index(ticker_col)[price_col].astype(float).to_dict()


def _load_issuer_sources(path: str) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sources = raw.get("sources", {}) or {}
    secondary_template = str(raw.get("secondary_template") or "").strip()
    fallback_tickers = {str(t).upper() for t in raw.get("secondary_fallback_tickers", [])}
    for ticker, cfg in sources.items():
        if str(ticker).upper() in fallback_tickers and secondary_template and isinstance(cfg, dict) and "secondary" not in cfg:
            cfg["secondary"] = {
                "provider": "StockAnalysis",
                "mode": "html_table",
                "url": secondary_template.format(ticker=str(ticker).lower()),
            }
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical Equity + ETF valuation scenarios")
    parser.add_argument("--universe", required=True)
    parser.add_argument("--underlying-prices", required=True)
    parser.add_argument("--policy", default="config/valuation_policy.yml")
    parser.add_argument("--etf-sources", default="config/etf_issuer_sources.yml")
    parser.add_argument("--non-equity-policy", default="config/non_equity_tracker_policy.yml")
    parser.add_argument("--output-dir", default="data/canonical/valuation")
    args = parser.parse_args()

    universe = pd.read_parquet(args.universe).sort_values("cedear_ticker")
    prices = pd.read_parquet(args.underlying_prices)
    policy = yaml.safe_load(Path(args.policy).read_text(encoding="utf-8")) or {}
    tracker_policy = yaml.safe_load(Path(args.non_equity_policy).read_text(encoding="utf-8")) or {}
    finnhub = FinnhubConnector()
    issuer_holdings = IssuerHoldingsConnector(_load_issuer_sources(args.etf_sources))
    tracker_connector = NonEquityTrackerConnector(tracker_policy)
    prices_by_cedear = _price_map(prices)

    classified: list[tuple[pd.Series, bool]] = []
    for _, item in universe.iterrows():
        cedear = str(item.get("cedear_ticker") or "").upper()
        classified.append((item, _is_etf(cedear, item.get("instrument_type"), item.get("issuer_name"), policy)))

    rows_by_cedear: dict[str, dict] = {}
    equity_scenarios: dict[str, dict] = {}
    equity_count = 0
    etf_count = 0
    issuer_ready_count = 0
    finnhub_etf_ready_count = 0
    non_equity_ready_count = 0

    for item, is_etf in classified:
        if is_etf:
            continue
        cedear = str(item.get("cedear_ticker") or "").upper()
        underlying = str(item.get("underlying_ticker") or cedear).upper()
        scenario = build_equity_scenario(underlying, prices_by_cedear.get(cedear), finnhub, policy)
        scenario.update({
            "cedear_ticker": cedear,
            "underlying_ticker": underlying,
            "instrument_type": item.get("instrument_type"),
            "valuation_engine_type": "EQUITY",
            "methodology_version": policy.get("methodology_version", "VAL-1.0"),
        })
        rows_by_cedear[cedear] = scenario
        equity_scenarios[underlying] = scenario
        equity_count += 1

    non_equity = {str(t).upper() for t in policy.get("instrument_overrides", {}).get("non_equity_trackers", [])}
    for item, is_etf in classified:
        if not is_etf:
            continue
        cedear = str(item.get("cedear_ticker") or "").upper()
        underlying = str(item.get("underlying_ticker") or cedear).upper()
        current_price = prices_by_cedear.get(cedear)

        if underlying in non_equity:
            scenario = build_non_equity_tracker_scenario(
                underlying,
                current_price,
                tracker_connector,
                tracker_policy,
            )
            if scenario.get("valuation_status") == "VALUATION_READY":
                non_equity_ready_count += 1
        else:
            scenario = build_issuer_etf_scenario(
                underlying,
                current_price,
                finnhub,
                issuer_holdings,
                policy,
                equity_scenarios=equity_scenarios,
            )
            if scenario.get("valuation_status") == "VALUATION_READY":
                issuer_ready_count += 1
            else:
                premium = build_etf_scenario(underlying, current_price, finnhub, policy)
                if premium.get("valuation_status") == "VALUATION_READY":
                    scenario = premium
                    finnhub_etf_ready_count += 1

        scenario.update({
            "cedear_ticker": cedear,
            "underlying_ticker": underlying,
            "instrument_type": item.get("instrument_type"),
            "valuation_engine_type": "ETF",
            "methodology_version": policy.get("methodology_version", "VAL-1.0"),
        })
        rows_by_cedear[cedear] = scenario
        etf_count += 1

    result = pd.DataFrame([rows_by_cedear[str(item.get("cedear_ticker") or "").upper()] for item, _ in classified])
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
    cached_constituents = int(pd.to_numeric(result.get("etf_cached_equity_count"), errors="coerce").fillna(0).sum()) if "etf_cached_equity_count" in result else 0
    direct_constituents = int(pd.to_numeric(result.get("etf_direct_finnhub_count"), errors="coerce").fillna(0).sum()) if "etf_direct_finnhub_count" in result else 0
    metrics = {
        "layer": "Canonical Valuation Scenarios",
        "methodology_version": policy.get("methodology_version", "VAL-1.0"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finnhub_configured": finnhub.configured,
        "ticker_count": int(len(result)),
        "equity_count": equity_count,
        "etf_count": etf_count,
        "ready_count": ready,
        "blocked_count": blocked,
        "equity_ready_count": equity_ready,
        "etf_ready_count": etf_ready,
        "issuer_etf_ready_count": issuer_ready_count,
        "finnhub_premium_etf_ready_count": finnhub_etf_ready_count,
        "non_equity_tracker_ready_count": non_equity_ready_count,
        "etf_cached_constituent_valuations_used": cached_constituents,
        "etf_direct_finnhub_constituent_valuations_used": direct_constituents,
        "coverage_pct": round(ready / len(result) * 100.0, 2) if len(result) else 0.0,
        "freshness_policy": policy.get("freshness", {}),
        "instrument_overrides": policy.get("instrument_overrides", {}),
        "pass_full_valuation": bool(len(result) > 0 and ready == len(result)),
        "note": "Operating equities use Finnhub; equity ETFs use issuer look-through; GLD/IBIT/ETHA use dedicated issuer-NAV stress models. Missing/stale material data remains BLOCKED_BY_DATA.",
    }
    (out / "valuation_scenarios_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
