from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class AllocationPolicy:
    position_stress_budget_nav: float = 0.02
    portfolio_stress_budget_nav: float = 0.10
    max_single_name_weight: float = 0.20
    max_positions: int = 10
    min_position_weight: float = 0.02
    max_new_deployment_weight_nav: float = 1.00


REQUIRED_COLUMNS = {"cedear_ticker", "g4_status", "risk_adjusted_er", "bear_return_net", "fx_stress_return_net", "existing_weight"}


def build_portfolio_allocation(g4_result: pd.DataFrame, policy: AllocationPolicy | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Decide joint position sizes among every G4_PASS candidate.

    G4 already certifies each candidate independently: positive risk-adjusted
    margin vs cash, and compatible with both the fundamental and FX/regulatory
    Stress downside vetoes at a fixed 5% test weight. This layer answers the
    question G4 deliberately does not -- given N simultaneous PASS candidates,
    how much of NAV should each actually receive?

    Sizing is risk-budget constrained, not mean-variance optimized. With a
    handful of PASS candidates (often one or two), expected-return estimates
    carry far more uncertainty than a correlation matrix can safely exploit,
    and Markowitz-style optimizers are well known to amplify that estimation
    error into extreme, unstable weights -- a poor fit for a capital
    preservation mandate. Instead, each candidate's TOTAL weight (existing +
    new) is capped by: the existing per-name concentration limit, a
    per-position stress budget divided by that candidate's worst-case stress
    loss (the worse of the fundamental and FX/regulatory Stress scenarios G4
    already computed), and the remaining portfolio-level stress budget.
    Candidates are filled in risk-adjusted-expected-return rank order against
    a new-capital deployment budget; cash is the residual, never a forced
    allocation target, and no position is ever sized down by this function --
    it only decides new buys among what G4 already certified.

    Out of scope: this does not decide sells or rebalances of currently-held
    names that no longer pass G4 -- a name simply absent from the returned
    frame should be left exactly as held, not liquidated. That decision
    belongs to a separate divestment/rebalance policy this layer does not make.
    """
    policy = policy or AllocationPolicy()
    missing = sorted(REQUIRED_COLUMNS - set(g4_result.columns))
    if missing:
        raise ValueError("g4 result missing columns: " + ", ".join(missing))
    if policy.max_positions < 1:
        raise ValueError("max_positions must be >= 1")

    passed = g4_result[g4_result["g4_status"] == "G4_PASS"].copy()
    if passed.empty:
        empty = pd.DataFrame(columns=[
            "cedear_ticker", "target_weight", "existing_weight", "weight_delta",
            "worst_case_stress_loss", "risk_adjusted_er", "position_stress_contribution_nav", "allocation_rationale",
        ])
        return empty, _metrics(empty, 0, policy)

    passed["existing_weight"] = pd.to_numeric(passed["existing_weight"], errors="coerce").fillna(0.0)
    passed["worst_case_stress_loss"] = passed[["bear_return_net", "fx_stress_return_net"]].abs().max(axis=1)
    passed = passed.sort_values(["risk_adjusted_er", "cedear_ticker"], ascending=[False, True]).reset_index(drop=True)

    remaining_deployment_budget = policy.max_new_deployment_weight_nav
    remaining_stress_budget = policy.portfolio_stress_budget_nav
    rows: list[dict[str, Any]] = []
    for _, row in passed.iterrows():
        if len(rows) >= policy.max_positions or remaining_deployment_budget < 1e-12:
            break
        existing = float(row["existing_weight"])
        loss = float(row["worst_case_stress_loss"])
        max_by_position_budget = (policy.position_stress_budget_nav / loss) if loss > 0 else policy.max_single_name_weight
        max_by_portfolio_budget = (remaining_stress_budget / loss) if loss > 0 else policy.max_single_name_weight
        max_by_deployment_budget = existing + remaining_deployment_budget
        weight = min(policy.max_single_name_weight, max_by_position_budget, max_by_portfolio_budget, max_by_deployment_budget)
        weight = max(weight, existing)
        delta = weight - existing
        if delta < 1e-12:
            continue
        if weight + 1e-12 < policy.min_position_weight:
            continue
        remaining_deployment_budget -= delta
        remaining_stress_budget -= weight * loss
        rows.append({
            "cedear_ticker": row["cedear_ticker"],
            "target_weight": weight,
            "existing_weight": existing,
            "weight_delta": delta,
            "worst_case_stress_loss": loss,
            "risk_adjusted_er": float(row["risk_adjusted_er"]),
            "position_stress_contribution_nav": weight * loss,
            "allocation_rationale": "RISK_BUDGET_CONSTRAINED_RANK_FILL",
        })

    allocated = pd.DataFrame(rows)
    return allocated, _metrics(allocated, int(len(passed)), policy)


def _metrics(allocated: pd.DataFrame, candidate_count: int, policy: AllocationPolicy) -> dict[str, Any]:
    total_invested = float(allocated["target_weight"].sum()) if not allocated.empty else 0.0
    total_stress = float(allocated["position_stress_contribution_nav"].sum()) if not allocated.empty else 0.0
    return {
        "methodology_version": "PORTFOLIO-ALLOCATION-1.0",
        "candidate_count": candidate_count,
        "allocated_count": int(len(allocated)),
        "unallocated_count": candidate_count - int(len(allocated)),
        "total_new_deployment_weight": total_invested,
        "cash_weight_is_endogenous_residual": True,
        "total_portfolio_stress_contribution_nav": total_stress,
        "portfolio_stress_budget_nav": policy.portfolio_stress_budget_nav,
        "portfolio_stress_budget_ok": total_stress <= policy.portfolio_stress_budget_nav + 1e-9,
        "max_positions": policy.max_positions,
        "scope_note": "New-buy sizing only; does not decide sells or rebalances of existing holdings that fall off the PASS list.",
    }
