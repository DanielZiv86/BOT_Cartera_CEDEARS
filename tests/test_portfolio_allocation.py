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


def _row(ticker, *, g4_status="G4_PASS", er=0.10, bear=-0.10, fx=-0.10, existing=0.0, diversification_score=None):
    row = {
        "cedear_ticker": ticker,
        "g4_status": g4_status,
        "risk_adjusted_er": er,
        "bear_return_net": bear,
        "fx_stress_return_net": fx,
        "existing_weight": existing,
    }
    if diversification_score is not None:
        row["diversification_score"] = diversification_score
    return row


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


def test_diversification_score_scales_position_stress_budget():
    # Same loss (0.10) and same policy as test_single_candidate_sized_by_
    # position_stress_budget, but a low diversification_score (heavily
    # correlated with what's already held) should shrink the position budget
    # below the plain 0.02/0.10=0.20 that a neutral (score-less) candidate
    # gets, and a high score should let it grow (capped by max_single_name_weight).
    correlated = pd.DataFrame([_row("CORR", er=0.10, bear=-0.10, fx=-0.05, diversification_score=0)])
    allocated, _ = build_portfolio_allocation(correlated, P)
    # multiplier at score=0 is diversification_multiplier_min (0.5) -> effective budget 0.01 -> 0.01/0.10=0.10
    assert allocated.iloc[0]["target_weight"] == pytest.approx(0.10)
    assert allocated.iloc[0]["diversification_multiplier"] == pytest.approx(0.5)

    diversifying = pd.DataFrame([_row("DIV", er=0.10, bear=-0.10, fx=-0.05, diversification_score=100)])
    allocated2, _ = build_portfolio_allocation(diversifying, P)
    # multiplier at score=100 is diversification_multiplier_max (1.5) -> effective budget 0.03 -> 0.03/0.10=0.30, capped at max_single_name_weight=0.20
    assert allocated2.iloc[0]["target_weight"] == pytest.approx(0.20)
    assert allocated2.iloc[0]["diversification_multiplier"] == pytest.approx(1.5)


def test_missing_diversification_score_is_neutral_same_as_before():
    g4 = pd.DataFrame([_row("A", er=0.10, bear=-0.10, fx=-0.05)])
    allocated, _ = build_portfolio_allocation(g4, P)
    assert allocated.iloc[0]["diversification_multiplier"] == pytest.approx(1.0)
    assert allocated.iloc[0]["target_weight"] == pytest.approx(0.20)


def test_existing_holdings_stress_reduces_room_for_new_candidates():
    g4 = pd.DataFrame([_row("A", er=0.10, bear=-0.10, fx=-0.08)])
    # Same candidate as test_single_candidate_sized_by_position_stress_budget
    # (which gets 0.20 with a fresh 0.10 portfolio budget), but now 0.08 of
    # that 0.10 whole-portfolio stress budget is already used by currently
    # held positions -- only 0.02 remains for new buys -> 0.02/0.10=0.20 is
    # still the position-budget cap (0.02), but the *portfolio* cap now binds
    # tighter: 0.02 remaining / 0.10 loss = 0.20 -- exactly at the position
    # cap here, so tighten further to make the portfolio cap the binding one.
    allocated, metrics = build_portfolio_allocation(g4, P, existing_holdings_stress_nav=0.085)
    # remaining portfolio budget = 0.10-0.085=0.015 -> 0.015/0.10=0.15, tighter than the 0.20 position-budget cap
    assert allocated.iloc[0]["target_weight"] == pytest.approx(0.15)
    assert metrics["existing_holdings_stress_contribution_nav"] == pytest.approx(0.085)
    assert metrics["total_portfolio_stress_contribution_nav"] == pytest.approx(0.085 + 0.15 * 0.10)
    assert metrics["portfolio_stress_budget_ok"]


def test_existing_holdings_stress_cannot_be_negative():
    g4 = pd.DataFrame([_row("A")])
    with pytest.raises(ValueError):
        build_portfolio_allocation(g4, P, existing_holdings_stress_nav=-0.01)


def test_missing_required_column_fails_closed():
    g4 = pd.DataFrame([{"cedear_ticker": "A", "g4_status": "G4_PASS"}])
    with pytest.raises(ValueError):
        build_portfolio_allocation(g4, P)
