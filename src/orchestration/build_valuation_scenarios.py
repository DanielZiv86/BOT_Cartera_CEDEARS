from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.connectors.finnhub import FinnhubConnector
from src.connectors.issuer_holdings import HoldingsSnapshot, IssuerHoldingsConnector, IssuerHoldingsError
from src.connectors.non_equity_tracker import NonEquityTrackerConnector
from src.valuation.equity_engine import build_equity_scenario
from src.valuation.etf_engine import ConstituentScenario, build_etf_scenario
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


def _ready_equity(row: dict[str, Any] | None) -> bool:
    return bool(row and row.get("valuation_status") == "VALUATION_READY")


def _estimate_etf_plan(snapshot: HoldingsSnapshot, equity_scenarios: dict[str, dict], policy: dict) -> dict[str, Any]:
    """Estimate how many uncached constituent lookups could make an ETF cross the hurdle.

    This is deliberately deterministic and provider-call free. It lets the global
    budget favor funds that are closest to becoming usable instead of allocating
    scarce calls in universe/FIFO order.
    """
    quality = policy.get("quality", {}) or {}
    min_covered = float(quality.get("minimum_etf_covered_weight", 0.50))
    min_valid = int(quality.get("minimum_etf_valid_holdings", 5))
    default_limit = int(quality.get("maximum_etf_holdings_to_analyze", 50))
    per_fund_cap = int(quality.get("maximum_direct_constituent_lookups_per_etf", 12))
    max_holdings = snapshot.max_holdings_to_analyze or default_limit
    holdings = sorted(snapshot.holdings, key=lambda x: float(x.get("percent") or 0), reverse=True)[:max_holdings]
    total_raw = sum(float(h.get("percent") or 0) for h in holdings)
    scale = 1.0 if total_raw <= 1.5 else 100.0

    cached_weight = 0.0
    cached_count = 0
    missing_weights: list[float] = []
    for holding in holdings:
        symbol = str(holding.get("symbol") or "").strip().upper()
        try:
            weight = float(holding.get("percent") or 0) / scale
        except (TypeError, ValueError):
            continue
        if not symbol or weight <= 0:
            continue
        if _ready_equity(equity_scenarios.get(symbol)):
            cached_weight += weight
            cached_count += 1
        else:
            missing_weights.append(weight)

    if cached_weight >= min_covered and cached_count >= min_valid:
        needed = 0
        feasible = True
    else:
        running_weight = cached_weight
        running_count = cached_count
        needed = 0
        feasible = False
        for weight in missing_weights:
            needed += 1
            running_weight += weight
            running_count += 1
            if running_weight >= min_covered and running_count >= min_valid:
                feasible = needed <= per_fund_cap
                break
        if needed > per_fund_cap:
            feasible = False

    return {
        "cached_weight": cached_weight,
        "cached_count": cached_count,
        "uncached_count": len(missing_weights),
        "estimated_lookups_needed": needed if feasible else per_fund_cap + 1,
        "estimated_feasible_within_per_fund_cap": feasible,
        "coverage_gap": max(0.0, min_covered - cached_weight),
    }


def _blocker_diagnostics(result: pd.DataFrame) -> tuple[dict[str, int], dict[str, list[str]]]:
    counts: Counter[str] = Counter()
    tickers: defaultdict[str, list[str]] = defaultdict(list)
    if result.empty or "blockers" not in result.columns:
        return {}, {}
    for _, row in result.iterrows():
        ticker = str(row.get("cedear_ticker") or row.get("underlying_ticker") or "UNKNOWN")
        blockers = row.get("blockers")
        if isinstance(blockers, str):
            try:
                parsed = json.loads(blockers)
                blockers = parsed if isinstance(parsed, list) else [blockers]
            except json.JSONDecodeError:
                blockers = [blockers]
        if not isinstance(blockers, list):
            continue
        for blocker in blockers:
            code = str(blocker).strip()
            if not code:
                continue
            counts[code] += 1
            tickers[code].append(ticker)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))), {
        code: sorted(set(names)) for code, names in sorted(tickers.items())
    }


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
    constituent_cache: dict[str, ConstituentScenario] = {}
    quality = policy.get("quality", {}) or {}
    global_direct_limit = int(quality.get("maximum_global_direct_constituent_lookups", 60))
    preferred_direct_limit = int(quality.get("preferred_global_direct_constituent_lookups", min(40, global_direct_limit)))
    direct_lookup_budget = {"initial": global_direct_limit, "remaining": global_direct_limit}
    provider_fallbacks = policy.get("provider_fallbacks", {}) or {}
    premium_etf_fallback_enabled = bool(provider_fallbacks.get("finnhub_premium_etf_enabled", False))
    equity_count = 0
    etf_count = 0
    issuer_ready_count = 0
    finnhub_etf_ready_count = 0
    non_equity_ready_count = 0

    # Stage 1: all canonical equities first so ETF planning can reuse every ready valuation.
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

    # Stage 2: prefetch issuer snapshots once and estimate marginal calls needed.
    etf_work: list[dict[str, Any]] = []
    for item, is_etf in classified:
        if not is_etf:
            continue
        cedear = str(item.get("cedear_ticker") or "").upper()
        underlying = str(item.get("underlying_ticker") or cedear).upper()
        if underlying in non_equity:
            etf_work.append({"item": item, "cedear": cedear, "underlying": underlying, "snapshot": None, "plan": None, "non_equity": True})
            continue
        snapshot = None
        fetch_error = None
        try:
            snapshot = issuer_holdings.fetch(underlying)
        except IssuerHoldingsError as exc:
            fetch_error = str(exc)
        plan = _estimate_etf_plan(snapshot, equity_scenarios, policy) if snapshot is not None else {
            "cached_weight": 0.0,
            "cached_count": 0,
            "uncached_count": 0,
            "estimated_lookups_needed": 10**6,
            "estimated_feasible_within_per_fund_cap": False,
            "coverage_gap": 1.0,
        }
        etf_work.append({
            "item": item,
            "cedear": cedear,
            "underlying": underlying,
            "snapshot": snapshot,
            "fetch_error": fetch_error,
            "plan": plan,
            "non_equity": False,
        })

    # Dedicated non-equity models first; issuer equity ETFs are then ordered by
    # cheapest expected path to the 50% hurdle, not by ticker/FIFO order.
    issuer_work = [w for w in etf_work if not w["non_equity"]]
    issuer_work.sort(key=lambda w: (
        0 if w["plan"].get("estimated_feasible_within_per_fund_cap") else 1,
        int(w["plan"].get("estimated_lookups_needed", 10**6)),
        float(w["plan"].get("coverage_gap", 1.0)),
        w["underlying"],
    ))
    ordered_work = [w for w in etf_work if w["non_equity"]] + issuer_work

    planner_order: list[dict[str, Any]] = []
    for work in ordered_work:
        item = work["item"]
        cedear = work["cedear"]
        underlying = work["underlying"]
        current_price = prices_by_cedear.get(cedear)

        if work["non_equity"]:
            scenario = build_non_equity_tracker_scenario(
                underlying,
                current_price,
                tracker_connector,
                tracker_policy,
            )
            if scenario.get("valuation_status") == "VALUATION_READY":
                non_equity_ready_count += 1
        else:
            before = direct_lookup_budget["remaining"]
            scenario = build_issuer_etf_scenario(
                underlying,
                current_price,
                finnhub,
                issuer_holdings,
                policy,
                equity_scenarios=equity_scenarios,
                constituent_cache=constituent_cache,
                direct_lookup_budget=direct_lookup_budget,
                holdings_snapshot=work.get("snapshot"),
            )
            used = before - direct_lookup_budget["remaining"]
            planner_order.append({
                "ticker": underlying,
                "estimated_lookups_needed": work["plan"].get("estimated_lookups_needed"),
                "estimated_feasible": work["plan"].get("estimated_feasible_within_per_fund_cap"),
                "cached_weight_estimate": round(float(work["plan"].get("cached_weight", 0.0)), 6),
                "actual_direct_lookups_used": used,
                "valuation_status": scenario.get("valuation_status"),
            })
            if scenario.get("valuation_status") == "VALUATION_READY":
                issuer_ready_count += 1
            elif premium_etf_fallback_enabled:
                premium = build_etf_scenario(
                    underlying,
                    current_price,
                    finnhub,
                    policy,
                    constituent_cache=constituent_cache,
                    direct_lookup_budget=direct_lookup_budget,
                )
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

    blocker_counts, blocker_tickers = _blocker_diagnostics(result)

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
    shared_cache_hits = int(pd.to_numeric(result.get("etf_shared_constituent_cache_hits"), errors="coerce").fillna(0).sum()) if "etf_shared_constituent_cache_hits" in result else 0
    direct_constituents = int(pd.to_numeric(result.get("etf_direct_finnhub_count"), errors="coerce").fillna(0).sum()) if "etf_direct_finnhub_count" in result else 0
    direct_constituents += int(pd.to_numeric(result.get("etf_direct_constituent_lookups"), errors="coerce").fillna(0).sum()) if "etf_direct_constituent_lookups" in result else 0
    metrics = {
        "layer": "Canonical Valuation Scenarios",
        "methodology_version": policy.get("methodology_version", "VAL-1.0"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finnhub_configured": finnhub.configured,
        "finnhub_diagnostics": finnhub.diagnostics(),
        "ticker_count": int(len(result)),
        "equity_count": equity_count,
        "etf_count": etf_count,
        "ready_count": ready,
        "blocked_count": blocked,
        "equity_ready_count": equity_ready,
        "etf_ready_count": etf_ready,
        "issuer_etf_ready_count": issuer_ready_count,
        "finnhub_premium_etf_ready_count": finnhub_etf_ready_count,
        "finnhub_premium_etf_fallback_enabled": premium_etf_fallback_enabled,
        "non_equity_tracker_ready_count": non_equity_ready_count,
        "etf_cached_equity_valuations_used": cached_constituents,
        "etf_shared_constituent_cache_hits": shared_cache_hits,
        "etf_unique_constituents_cached": len(constituent_cache),
        "etf_direct_finnhub_constituent_lookups": direct_constituents,
        "etf_direct_lookup_budget_preferred": preferred_direct_limit,
        "etf_direct_lookup_budget_initial": direct_lookup_budget["initial"],
        "etf_direct_lookup_budget_remaining": direct_lookup_budget["remaining"],
        "etf_budget_allocation_strategy": "MARGINAL_COVERAGE_EFFICIENCY_V1",
        "etf_planner_order": planner_order,
        "coverage_pct": round(ready / len(result) * 100.0, 2) if len(result) else 0.0,
        "blocker_counts": blocker_counts,
        "blocker_tickers": blocker_tickers,
        "freshness_policy": policy.get("freshness", {}),
        "instrument_overrides": policy.get("instrument_overrides", {}),
        "pass_full_valuation": bool(len(result) > 0 and ready == len(result)),
        "note": "VAL-1.7 preplans issuer ETFs by marginal coverage efficiency, reuses all canonical equity scenarios, applies a bounded shared direct-constituent hard cap, inherits fund-specific freshness across fallbacks, and retries fragile issuer transport. Finnhub Premium ETF fallback remains opt-in only. GLD/IBIT/ETHA use dedicated issuer-NAV stress models.",
    }
    (out / "valuation_scenarios_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
