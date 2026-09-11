from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class G4Policy:
    cash_return_assumption: float = 0.00
    minimum_excess_return_over_cash: float = 0.05
    capital_preservation_buffer: float = 0.03
    minimum_margin_over_hurdle: float = 0.02
    max_bear_downside: float = -0.15
    candidate_test_weight_nav: float = 0.05
    max_single_name_weight: float = 0.20
    soft_single_name_weight: float = 0.12
    warning_single_name_weight: float = 0.15
    correlation_warning: float = 0.75
    uncertainty_penalty_max: float = 0.10
    local_warning_penalty: float = 0.02
    correlation_penalty_max: float = 0.03
    concentration_penalty_max: float = 0.03
    fx_regulatory_stress_ccl_haircut: float = 0.25
    max_fx_regulatory_stress_downside: float = -0.20

    @property
    def cash_hurdle(self) -> float:
        return (
            self.cash_return_assumption
            + self.minimum_excess_return_over_cash
            + self.capital_preservation_buffer
        )


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _scenario_return(
    target_underlying: float,
    ratio: float,
    market_ccl: float,
    entry_ars: float,
    brokerage_rate: float,
    exit_spread_assumption: float,
) -> float:
    future_local_gross = target_underlying / ratio * market_ccl
    future_local_net = future_local_gross * (1.0 - brokerage_rate - exit_spread_assumption)
    return future_local_net / entry_ars - 1.0


def _validate_probabilities(row: pd.Series) -> tuple[bool, float | None, float | None, float | None]:
    bull_p = _num(row.get("bull_probability"))
    base_p = _num(row.get("base_probability"))
    bear_p = _num(row.get("bear_probability"))
    if bull_p is None or base_p is None or bear_p is None:
        return False, bull_p, base_p, bear_p
    if min(bull_p, base_p, bear_p) < 0:
        return False, bull_p, base_p, bear_p
    return abs((bull_p + base_p + bear_p) - 1.0) <= 1e-6, bull_p, base_p, bear_p


def calculate_g4_cash_hurdle(
    local_market: pd.DataFrame,
    valuation_inputs: pd.DataFrame,
    portfolio_fit: pd.DataFrame,
    positions: pd.DataFrame | None = None,
    policy: G4Policy | None = None,
    brokerage_rate: float = 0.006,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Calculate analytical G4 Cash Hurdle decisions.

    Valuation inputs must contain one row per ticker with bull/base/bear target
    prices and probabilities. Missing material valuation data never receives a PASS.
    Returns are measured economically in USD: the local CEDEAR entry cost is
    translated through the robust market CCL while future local value is derived
    from the underlying target price and the validated Comafi ratio.

    A separate, zero-probability FX/regulatory Stress scenario is evaluated for
    every candidate alongside the fundamental Bull/Base/Bear/Stress fan: the Base
    target realized through a degraded CCL (policy.fx_regulatory_stress_ccl_haircut
    below today's market CCL), representing capital-control tightening or forced
    settlement through a worse conversion channel at exit. This is a market-wide
    risk factor, not an idiosyncratic one, so the same haircut applies uniformly
    to every candidate. It is never blended into expected return -- like the
    fundamental Stress scenario, it is a hard downside veto only, kept auditably
    separate from the fundamental downside veto (G4_FAIL_FX_REGULATORY_STRESS vs
    G4_FAIL_DOWNSIDE) so a failure's cause is never ambiguous between "the company
    is risky" and "the currency channel is risky".
    """
    policy = policy or G4Policy()
    local = local_market.copy()
    local["cedear_ticker"] = local["cedear_ticker"].astype(str).str.upper()

    valuations = valuation_inputs.copy()
    if valuations.empty:
        valuations = pd.DataFrame(columns=["cedear_ticker"])
    if "cedear_ticker" not in valuations.columns:
        valuations["cedear_ticker"] = pd.Series(dtype=str)
    valuations["cedear_ticker"] = valuations["cedear_ticker"].astype(str).str.upper()

    fit = portfolio_fit.copy()
    if fit.empty:
        fit = pd.DataFrame(columns=["cedear_ticker"])
    if "cedear_ticker" not in fit.columns:
        fit["cedear_ticker"] = pd.Series(dtype=str)
    fit["cedear_ticker"] = fit["cedear_ticker"].astype(str).str.upper()

    merged = local.merge(valuations, on="cedear_ticker", how="left", suffixes=("", "_valuation"))
    merged = merged.merge(fit, on="cedear_ticker", how="left", suffixes=("", "_fit"))

    existing_weights: dict[str, float] = {}
    if positions is not None and not positions.empty and {"cedear_ticker", "weight"}.issubset(positions.columns):
        p = positions.copy()
        p["cedear_ticker"] = p["cedear_ticker"].astype(str).str.upper()
        p["weight"] = pd.to_numeric(p["weight"], errors="coerce").fillna(0.0)
        existing_weights = p.groupby("cedear_ticker")["weight"].sum().to_dict()

    rows: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        ticker = row["cedear_ticker"]
        blockers: list[str] = []

        local_gate = str(row.get("valuation_g4_local_gate") or "BLOCKED")
        if local_gate == "BLOCKED":
            blockers.append("LOCAL_MARKET_GATE_BLOCKED")

        ratio = _num(row.get("ratio_used"))
        market_ccl = _num(row.get("market_ccl_reference"))
        local_ref = _num(row.get("analytical_local_ref_ars"))
        if ratio is None or ratio <= 0:
            blockers.append("RATIO_MISSING_OR_INVALID")
        if market_ccl is None or market_ccl <= 0:
            blockers.append("MARKET_CCL_MISSING")
        if local_ref is None or local_ref <= 0:
            blockers.append("LOCAL_ENTRY_REFERENCE_MISSING")

        bull_target = _num(row.get("bull_target_price"))
        base_target = _num(row.get("base_target_price"))
        bear_target = _num(row.get("bear_target_price"))
        valuation_status = str(row.get("valuation_status") or "BLOCKED_BY_VALUATION_DATA")
        if valuation_status not in {"VALUATION_READY", "VALUATION_READY_WITH_WARNING"}:
            blockers.append("VALUATION_NOT_READY")
        if bull_target is None or base_target is None or bear_target is None or min(bull_target or 0, base_target or 0, bear_target or 0) <= 0:
            blockers.append("SCENARIO_TARGETS_MISSING_OR_INVALID")

        probs_valid, bull_p, base_p, bear_p = _validate_probabilities(row)
        if not probs_valid:
            blockers.append("SCENARIO_PROBABILITIES_INVALID")

        fit_status = str(row.get("portfolio_fit_status") or "BLOCKED_BY_CORRELATION_DATA")
        diversification_score = _num(row.get("diversification_score"))
        max_corr = _num(row.get("max_corr_to_portfolio"))
        if fit_status != "PORTFOLIO_FIT_QUANT_READY" or diversification_score is None:
            blockers.append("PORTFOLIO_FIT_NOT_READY")

        confidence = _num(row.get("valuation_confidence"))
        if confidence is None or not 0 <= confidence <= 1:
            blockers.append("VALUATION_CONFIDENCE_MISSING")

        execution_book_status = str(row.get("execution_book_status") or "NOT_EXECUTABLE")
        execution_ready = execution_book_status == "EXECUTABLE_BOOK_READY"

        existing_weight = float(existing_weights.get(ticker, 0.0))
        projected_weight = existing_weight + policy.candidate_test_weight_nav
        hard_concentration_fail = projected_weight > policy.max_single_name_weight + 1e-12

        result: dict[str, Any] = {
            "cedear_ticker": ticker,
            "valuation_method": row.get("valuation_method"),
            "valuation_status": valuation_status,
            "valuation_confidence": confidence,
            "local_gate": local_gate,
            "execution_ready": execution_ready,
            "portfolio_fit_status": fit_status,
            "diversification_score": diversification_score,
            "max_corr_to_portfolio": max_corr,
            "existing_weight": existing_weight,
            "candidate_test_weight_nav": policy.candidate_test_weight_nav,
            "projected_weight": projected_weight,
            "cash_hurdle": policy.cash_hurdle,
            "minimum_margin_over_hurdle": policy.minimum_margin_over_hurdle,
            "max_bear_downside_allowed": policy.max_bear_downside,
            "fx_regulatory_stress_ccl_haircut": policy.fx_regulatory_stress_ccl_haircut,
            "max_fx_regulatory_stress_downside_allowed": policy.max_fx_regulatory_stress_downside,
            "blockers": blockers.copy(),
        }

        if blockers:
            result.update({
                "bull_return_net": None,
                "base_return_net": None,
                "bear_return_net": None,
                "fx_stress_market_ccl": None,
                "fx_stress_return_net": None,
                "expected_return_net": None,
                "uncertainty_penalty": None,
                "correlation_penalty": None,
                "concentration_penalty": None,
                "risk_adjusted_er": None,
                "net_benefit_vs_cash": None,
                "g4_status": "BLOCKED_BY_DATA",
                "g4_reason": ";".join(blockers),
            })
            rows.append(result)
            continue

        spread_pct = _num(row.get("spread_pct"))
        exit_spread_assumption = min(max((spread_pct or 0.0) / 2.0, 0.0), 0.02)
        entry_spread_assumption = exit_spread_assumption
        analytical_entry_ars = local_ref * (1.0 + brokerage_rate + entry_spread_assumption)

        bull_return = _scenario_return(bull_target, ratio, market_ccl, analytical_entry_ars, brokerage_rate, exit_spread_assumption)
        base_return = _scenario_return(base_target, ratio, market_ccl, analytical_entry_ars, brokerage_rate, exit_spread_assumption)
        bear_return = _scenario_return(bear_target, ratio, market_ccl, analytical_entry_ars, brokerage_rate, exit_spread_assumption)
        expected = bull_p * bull_return + base_p * base_return + bear_p * bear_return

        fx_stress_market_ccl = market_ccl * (1.0 - policy.fx_regulatory_stress_ccl_haircut)
        fx_stress_return = _scenario_return(base_target, ratio, fx_stress_market_ccl, analytical_entry_ars, brokerage_rate, exit_spread_assumption)

        uncertainty_penalty = (1.0 - confidence) * policy.uncertainty_penalty_max
        if local_gate == "PASS_WITH_WARNING":
            uncertainty_penalty += policy.local_warning_penalty

        correlation_penalty = 0.0
        if max_corr is not None and max_corr > policy.correlation_warning:
            correlation_penalty = min(
                (max_corr - policy.correlation_warning) / max(1.0 - policy.correlation_warning, 1e-9)
                * policy.correlation_penalty_max,
                policy.correlation_penalty_max,
            )

        concentration_penalty = 0.0
        if projected_weight > policy.soft_single_name_weight:
            span = max(policy.max_single_name_weight - policy.soft_single_name_weight, 1e-9)
            concentration_penalty = min(
                (projected_weight - policy.soft_single_name_weight) / span * policy.concentration_penalty_max,
                policy.concentration_penalty_max,
            )

        risk_adjusted_er = expected - uncertainty_penalty - correlation_penalty - concentration_penalty
        net_benefit = risk_adjusted_er - policy.cash_hurdle
        downside_ok = bear_return >= policy.max_bear_downside
        fx_stress_downside_ok = fx_stress_return >= policy.max_fx_regulatory_stress_downside
        return_ok = net_benefit >= policy.minimum_margin_over_hurdle

        if hard_concentration_fail:
            g4_status = "G4_FAIL_CONCENTRATION"
            reason = "PROJECTED_SINGLE_NAME_WEIGHT_ABOVE_HARD_LIMIT"
        elif not downside_ok:
            g4_status = "G4_FAIL_DOWNSIDE"
            reason = "BEAR_DOWNSIDE_EXCEEDS_POLICY"
        elif not fx_stress_downside_ok:
            g4_status = "G4_FAIL_FX_REGULATORY_STRESS"
            reason = "FX_REGULATORY_STRESS_DOWNSIDE_EXCEEDS_POLICY"
        elif not return_ok:
            g4_status = "G4_FAIL_RETURN"
            reason = "INSUFFICIENT_RISK_ADJUSTED_MARGIN_VS_CASH"
        else:
            g4_status = "G4_PASS"
            reason = "POSITIVE_MARGIN_VS_CASH_AND_DOWNSIDE_AND_FX_STRESS_COMPATIBLE"

        result.update({
            "bull_return_net": bull_return,
            "base_return_net": base_return,
            "bear_return_net": bear_return,
            "fx_stress_market_ccl": fx_stress_market_ccl,
            "fx_stress_return_net": fx_stress_return,
            "expected_return_net": expected,
            "uncertainty_penalty": uncertainty_penalty,
            "correlation_penalty": correlation_penalty,
            "concentration_penalty": concentration_penalty,
            "risk_adjusted_er": risk_adjusted_er,
            "net_benefit_vs_cash": net_benefit,
            "g4_status": g4_status,
            "g4_reason": reason,
            "analytical_entry_ars": analytical_entry_ars,
            "exit_spread_assumption": exit_spread_assumption,
            "bull_probability": bull_p,
            "base_probability": base_p,
            "bear_probability": bear_p,
        })
        rows.append(result)

    result_df = pd.DataFrame(rows)
    if not result_df.empty:
        result_df["g4_rank"] = result_df["net_benefit_vs_cash"].rank(method="min", ascending=False, na_option="bottom")
        result_df = result_df.sort_values(["g4_rank", "cedear_ticker"], na_position="last").reset_index(drop=True)

    total = int(len(result_df))
    pass_count = int((result_df["g4_status"] == "G4_PASS").sum()) if total else 0
    blocked_count = int((result_df["g4_status"] == "BLOCKED_BY_DATA").sum()) if total else 0
    evaluated_count = total - blocked_count
    if total == 0 or blocked_count > 0:
        cash_optimality = "NOT_DEMONSTRATED"
    elif pass_count > 0:
        cash_optimality = "CASH_NOT_OPTIMAL_BY_MODEL"
    else:
        cash_optimality = "CASH_OPTIMAL_BY_MODEL"

    fx_stress_fail_count = int((result_df["g4_status"] == "G4_FAIL_FX_REGULATORY_STRESS").sum()) if total else 0

    metrics = {
        "methodology_version": "G4-1.0",
        "ticker_count": total,
        "evaluated_count": evaluated_count,
        "blocked_count": blocked_count,
        "pass_count": pass_count,
        "fail_count": evaluated_count - pass_count,
        "fx_regulatory_stress_fail_count": fx_stress_fail_count,
        "cash_hurdle": policy.cash_hurdle,
        "cash_optimality_status": cash_optimality,
        "deployment_decision": "ALLOW_NEW_DEPLOYMENT" if pass_count > 0 else ("RESEARCH_BLOCKED" if blocked_count > 0 else "NO_NEW_DEPLOYMENT"),
        "return_currency": "USD_ECONOMIC_RETURN",
        "execution_separate_from_analytical_g4": True,
        "note": "G4 PASS requires complete scenario valuation, validated local data, quantitative portfolio fit, sufficient risk-adjusted margin vs cash, compatible bear downside, and compatible FX/regulatory stress downside.",
    }
    return result_df, metrics
