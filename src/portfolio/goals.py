from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FinancialGoal:
    target_additional_usd: float
    set_as_of: date
    horizon_months: int

    @property
    def target_date(self) -> date:
        total_month = self.set_as_of.month - 1 + self.horizon_months
        year = self.set_as_of.year + total_month // 12
        month = total_month % 12 + 1
        day = min(self.set_as_of.day, _days_in_month(year, month))
        return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, 12, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def load_financial_goal(path: str | Path) -> FinancialGoal:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    g = raw.get("goal", {}) or {}
    target = float(g.get("target_additional_usd", -1))
    horizon = int(g.get("horizon_months", 0))
    set_as_of_raw = g.get("set_as_of")
    if target < 0:
        raise ValueError("financial goal target_additional_usd must be >= 0")
    if horizon <= 0:
        raise ValueError("financial goal horizon_months must be > 0")
    if not set_as_of_raw:
        raise ValueError("financial goal set_as_of is required")
    set_as_of = datetime.strptime(str(set_as_of_raw), "%Y-%m-%d").date()
    return FinancialGoal(target_additional_usd=target, set_as_of=set_as_of, horizon_months=horizon)


def evaluate_goal(current_nav_usd: float, goal: FinancialGoal, as_of: date) -> dict[str, Any]:
    """Report progress toward a fixed-date, fixed-amount financial goal.

    This is a monitoring/pace metric only -- it never gates or vetoes any
    individual G4 candidate and never changes the G4 cash hurdle. The mandate
    is to maximize risk-adjusted return within the existing G4/allocation
    risk budget every cycle, re-selecting the best available Top-30 weekly;
    this function just makes it visible whether that ongoing selection is
    tracking to, ahead of, or behind the pace needed to clear the goal by its
    target date, so a human (or a future policy) can decide what to do about
    it -- it decides nothing on its own.
    """
    if current_nav_usd <= 0:
        raise ValueError("current_nav_usd must be > 0")

    target_wealth_usd = current_nav_usd + goal.target_additional_usd
    target_date = goal.target_date
    days_remaining = (target_date - as_of).days

    result: dict[str, Any] = {
        "goal_methodology_version": "GOALS-HURDLE-1.0",
        "goal_target_additional_usd": goal.target_additional_usd,
        "goal_set_as_of": goal.set_as_of.isoformat(),
        "goal_horizon_months": goal.horizon_months,
        "goal_target_date": target_date.isoformat(),
        "goal_current_nav_usd": current_nav_usd,
        "goal_target_wealth_usd": target_wealth_usd,
        "goal_as_of": as_of.isoformat(),
        "goal_days_remaining": days_remaining,
    }

    if target_wealth_usd <= current_nav_usd:
        result.update(goal_status="GOAL_ALREADY_MET", goal_required_annual_return=0.0)
        return result

    if days_remaining <= 0:
        result.update(goal_status="HORIZON_ELAPSED", goal_required_annual_return=None)
        return result

    years_remaining = days_remaining / 365.25
    required = (target_wealth_usd / current_nav_usd) ** (1.0 / years_remaining) - 1.0
    result.update(
        goal_status="COMPUTABLE",
        goal_years_remaining=years_remaining,
        goal_required_annual_return=required,
    )
    return result
