from __future__ import annotations

from typing import Any

from src.valuation.common import normalized_probabilities


def build_index_etf_scenario(symbol: str, current_price: float | None, policy: dict[str, Any]) -> dict[str, Any]:
    """Value a broad index ETF from versioned aggregate index economics.

    This engine is intentionally independent of constituent analyst targets. It is
    appropriate only for explicitly configured broad, diversified index trackers.
    Inputs are versioned policy evidence: aggregate earnings yield (or P/E),
    dividend yield, long-run earnings-growth assumption and scenario-specific
    terminal P/E. No missing input is silently fabricated.
    """
    ticker = str(symbol).upper()
    cfg = (policy.get("index_etf_models", {}) or {}).get(ticker)
    if not isinstance(cfg, dict):
        return {"underlying_ticker": ticker, "valuation_method": "INDEX_ETF_AGGREGATE_FUNDAMENTALS_V1", "valuation_status": "BLOCKED_BY_DATA", "valuation_confidence": None, "blockers": ["INDEX_ETF_MODEL_NOT_CONFIGURED"]}

    blockers: list[str] = []
    if current_price is None or current_price <= 0:
        blockers.append("CURRENT_PRICE_MISSING")
    required = ("current_pe", "dividend_yield", "base_earnings_growth", "bull_terminal_pe", "base_terminal_pe", "bear_terminal_pe", "bull_growth", "bear_growth", "source_ref", "source_date")
    for key in required:
        if cfg.get(key) in (None, ""):
            blockers.append(f"INDEX_ETF_{key.upper()}_MISSING")
    if blockers:
        return {"underlying_ticker": ticker, "valuation_method": "INDEX_ETF_AGGREGATE_FUNDAMENTALS_V1", "valuation_status": "BLOCKED_BY_DATA", "valuation_confidence": None, "blockers": blockers, "source_ref": cfg.get("source_ref"), "source_date": cfg.get("source_date")}

    try:
        current_pe = float(cfg["current_pe"])
        dividend_yield = float(cfg["dividend_yield"])
        growth = {"bull": float(cfg["bull_growth"]), "base": float(cfg["base_earnings_growth"]), "bear": float(cfg["bear_growth"])}
        terminal_pe = {"bull": float(cfg["bull_terminal_pe"]), "base": float(cfg["base_terminal_pe"]), "bear": float(cfg["bear_terminal_pe"])}
    except (TypeError, ValueError):
        return {"underlying_ticker": ticker, "valuation_method": "INDEX_ETF_AGGREGATE_FUNDAMENTALS_V1", "valuation_status": "BLOCKED_BY_DATA", "valuation_confidence": None, "blockers": ["INDEX_ETF_MODEL_INPUT_INVALID"], "source_ref": cfg.get("source_ref"), "source_date": cfg.get("source_date")}
    if current_pe <= 0 or dividend_yield < 0 or min(terminal_pe.values()) <= 0:
        blockers.append("INDEX_ETF_MODEL_INPUT_INVALID")

    # 12m total-return identity: earnings growth * terminal multiple re-rating + income.
    returns = {k: ((1.0 + growth[k]) * terminal_pe[k] / current_pe - 1.0) + dividend_yield for k in ("bull", "base", "bear")}
    if not (returns["bear"] <= returns["base"] <= returns["bull"]):
        blockers.append("ETF_SCENARIO_ORDER_INVALID")
    if blockers:
        return {"underlying_ticker": ticker, "valuation_method": "INDEX_ETF_AGGREGATE_FUNDAMENTALS_V1", "valuation_status": "BLOCKED_BY_DATA", "valuation_confidence": None, "blockers": blockers, "source_ref": cfg.get("source_ref"), "source_date": cfg.get("source_date")}

    prior = policy.get("probabilities", {}) or {}
    probs = normalized_probabilities((float(prior.get("prior_bull", .25)), float(prior.get("prior_base", .50)), float(prior.get("prior_bear", .25))))
    confidence = min(1.0, max(0.0, float(cfg.get("confidence", 0.62))))
    return {
        "underlying_ticker": ticker,
        "valuation_method": "INDEX_ETF_AGGREGATE_FUNDAMENTALS_V1",
        "valuation_status": "VALUATION_READY",
        "valuation_confidence": round(confidence, 4),
        "current_price": current_price,
        "bull_target_price": current_price * (1.0 + returns["bull"]),
        "base_target_price": current_price * (1.0 + returns["base"]),
        "bear_target_price": current_price * (1.0 + returns["bear"]),
        "bull_probability": probs[0], "base_probability": probs[1], "bear_probability": probs[2],
        "index_current_pe": current_pe, "index_dividend_yield": dividend_yield,
        "index_bull_growth": growth["bull"], "index_base_growth": growth["base"], "index_bear_growth": growth["bear"],
        "index_bull_terminal_pe": terminal_pe["bull"], "index_base_terminal_pe": terminal_pe["base"], "index_bear_terminal_pe": terminal_pe["bear"],
        "blockers": [], "source_ref": cfg["source_ref"], "source_date": cfg["source_date"],
    }
