import pandas as pd
import pytest

from src.portfolio.allocation import AllocationPolicy, build_portfolio_allocation

P = AllocationPolicy(
    position_stress_budget_nav=0.02,
    portfolio_stress_budget_nav=0.10,
    max_single_name_weight=0.20,
    max_positions=10,
    min_position_weight=0.02,
    max_new_deployment_weight_nav=1.00,
)


def _row(ticker, *, g4_status="G4_PASS", er=0.10, bear=-0.10, fx=-0.10, existing=0.0):
    return {
        "cedear_ticker": ticker,
        "g4_status": g4_status,
        "risk_adjusted_er": er,
        "bear_return_net": bear,
        "fx_stress_return_net": fx,
        "existing_weight": existing,
    }


def test_no_pass_candidates_yields_empty_allocation():
    g4 = pd.DataFrame([_row("A", g4_status="G4_FAIL_DOWNSIDE"), _row("B", g4_status="BLOCKED_BY_DATA")])
    allocated, metrics = build_portfolio_allocation(g4, P)
    assert allocated.empty
    assert metrics["candidate_count"] == 0 and metrics["allocated_count"] == 0
    assert metrics["total_new_deployment_weight"] == 0.0


def test_single_candidate_sized_by_position_stress_budget():
    # loss=0.10 -> position budget caps weight at 0.02/0.10 = 0.20, which also
    # happens to equal the single-name cap here.
    g4 = pd.DataFrame([_row("A", er=0.10, bear=-0.10, fx=-0.05)])
    allocated, metrics = build_portfolio_allocation(g4, P)
    assert len(allocated) == 1
    row = allocated.iloc[0]
    assert row["worst_case_stress_loss"] == pytest.approx(0.10)
    assert row["target_weight"] == pytest.approx(0.20)
    assert row["weight_delta"] == pytest.approx(0.20)
    assert metrics["total_new_deployment_weight"] == pytest.approx(0.20)


def test_higher_ranked_candidate_fills_first_when_portfolio_budget_binds():
    # Two candidates each want 0.20 by position budget (loss=0.10), but the
    # portfolio stress budget (0.10) only supports 0.10/0.10=1.0 NAV of gross
    # stress in aggregate; the better-ranked one should be filled to its full
    # request first, leaving less room for the second.
    g4 = pd.DataFrame([
        _row("BEST", er=0.20, bear=-0.10, fx=-0.08),
        _row("SECOND", er=0.05, bear=-0.10, fx=-0.08),
    ])
    tight = AllocationPolicy(position_stress_budget_nav=0.02, portfolio_stress_budget_nav=0.03, max_single_name_weight=0.20, max_positions=10, min_position_weight=0.02)
    allocated, metrics = build_portfolio_allocation(g4, tight)
    assert list(allocated["cedear_ticker"]) == ["BEST", "SECOND"]
    best = allocated[allocated.cedear_ticker == "BEST"].iloc[0]
    second = allocated[allocated.cedear_ticker == "SECOND"].iloc[0]
    assert best["target_weight"] == pytest.approx(0.20)
    # Remaining portfolio stress budget after BEST: 0.03 - 0.20*0.10 = 0.01 -> 0.01/0.10 = 0.10
    assert second["target_weight"] == pytest.approx(0.10)
    assert metrics["portfolio_stress_budget_ok"]


def test_existing_position_never_shrinks_and_delta_is_incremental():
    g4 = pd.DataFrame([_row("A", er=0.10, bear=-0.10, fx=-0.05, existing=0.15)])
    allocated, _ = build_portfolio_allocation(g4, P)
    row = allocated.iloc[0]
    assert row["existing_weight"] == pytest.approx(0.15)
    assert row["target_weight"] == pytest.approx(0.20)
    assert row["weight_delta"] == pytest.approx(0.05)


def test_max_positions_excludes_lowest_ranked_candidates():
    g4 = pd.DataFrame([_row(f"T{i}", er=1.0 - i * 0.01, bear=-0.05, fx=-0.05) for i in range(5)])
    tight = AllocationPolicy(position_stress_budget_nav=0.02, portfolio_stress_budget_nav=0.50, max_single_name_weight=0.20, max_positions=2, min_position_weight=0.02)
    allocated, metrics = build_portfolio_allocation(g4, tight)
    assert len(allocated) == 2
    assert list(allocated["cedear_ticker"]) == ["T0", "T1"]
    assert metrics["unallocated_count"] == 3


def test_below_minimum_position_weight_is_skipped_not_dust_allocated():
    # Deployment budget nearly exhausted: only 0.005 left, below min_position_weight.
    g4 = pd.DataFrame([
        _row("A", er=0.20, bear=-0.10, fx=-0.08),
        _row("B", er=0.10, bear=-0.10, fx=-0.08),
    ])
    tiny_budget = AllocationPolicy(position_stress_budget_nav=0.02, portfolio_stress_budget_nav=0.10, max_single_name_weight=0.20, max_positions=10, min_position_weight=0.02, max_new_deployment_weight_nav=0.205)
    allocated, metrics = build_portfolio_allocation(g4, tiny_budget)
    assert list(allocated["cedear_ticker"]) == ["A"]
    assert metrics["allocated_count"] == 1
    assert metrics["unallocated_count"] == 1


def test_zero_stress_loss_falls_back_to_single_name_cap():
    g4 = pd.DataFrame([_row("A", er=0.10, bear=0.05, fx=0.02)])
    allocated, _ = build_portfolio_allocation(g4, P)
    assert allocated.iloc[0]["target_weight"] == pytest.approx(P.max_single_name_weight)


def test_worst_case_loss_takes_the_larger_of_fundamental_and_fx_stress():
    g4 = pd.DataFrame([_row("A", er=0.10, bear=-0.05, fx=-0.18)])
    allocated, _ = build_portfolio_allocation(g4, P)
    assert allocated.iloc[0]["worst_case_stress_loss"] == pytest.approx(0.18)


def test_missing_required_column_fails_closed():
    g4 = pd.DataFrame([{"cedear_ticker": "A", "g4_status": "G4_PASS"}])
    with pytest.raises(ValueError):
        build_portfolio_allocation(g4, P)
