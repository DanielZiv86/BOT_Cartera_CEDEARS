from __future__ import annotations

from datetime import date

import pytest

from src.portfolio.goals import FinancialGoal, evaluate_goal, load_financial_goal


def test_load_financial_goal_parses_yaml(tmp_path):
    path = tmp_path / "goal.yml"
    path.write_text(
        "goal:\n"
        "  target_additional_usd: 20000\n"
        "  set_as_of: \"2026-09-11\"\n"
        "  horizon_months: 24\n",
        encoding="utf-8",
    )
    goal = load_financial_goal(path)
    assert goal.target_additional_usd == 20000
    assert goal.set_as_of == date(2026, 9, 11)
    assert goal.horizon_months == 24
    assert goal.target_date == date(2028, 9, 11)


def test_load_financial_goal_rejects_missing_fields(tmp_path):
    path = tmp_path / "goal.yml"
    path.write_text("goal:\n  target_additional_usd: 1000\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_financial_goal(path)


def test_target_date_clamps_shorter_month():
    goal = FinancialGoal(target_additional_usd=1000, set_as_of=date(2024, 1, 31), horizon_months=1)
    assert goal.target_date == date(2024, 2, 29)  # 2024 is a leap year


def test_evaluate_goal_computes_required_annual_return():
    goal = FinancialGoal(target_additional_usd=10000, set_as_of=date(2024, 1, 1), horizon_months=24)
    status = evaluate_goal(50000.0, goal, as_of=date(2024, 1, 1))
    assert status["goal_status"] == "COMPUTABLE"
    assert status["goal_target_wealth_usd"] == 60000.0
    years = status["goal_years_remaining"]
    expected = (60000.0 / 50000.0) ** (1.0 / years) - 1.0
    assert status["goal_required_annual_return"] == pytest.approx(expected)
    assert status["goal_required_annual_return"] > 0


def test_evaluate_goal_already_met_returns_zero_required_return():
    # target_additional_usd=0 means target_wealth == current_nav: the goal
    # (no additional capital needed) is met by construction.
    goal = FinancialGoal(target_additional_usd=0, set_as_of=date(2024, 1, 1), horizon_months=24)
    status = evaluate_goal(50000.0, goal, as_of=date(2024, 1, 1))
    assert status["goal_status"] == "GOAL_ALREADY_MET"
    assert status["goal_required_annual_return"] == 0.0


def test_evaluate_goal_horizon_elapsed():
    goal = FinancialGoal(target_additional_usd=10000, set_as_of=date(2024, 1, 1), horizon_months=12)
    status = evaluate_goal(50000.0, goal, as_of=date(2025, 6, 1))
    assert status["goal_status"] == "HORIZON_ELAPSED"
    assert status["goal_required_annual_return"] is None


def test_evaluate_goal_rejects_non_positive_nav():
    goal = FinancialGoal(target_additional_usd=10000, set_as_of=date(2024, 1, 1), horizon_months=12)
    with pytest.raises(ValueError):
        evaluate_goal(0.0, goal, as_of=date(2024, 1, 1))
