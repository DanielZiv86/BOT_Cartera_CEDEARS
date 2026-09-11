import json

import pandas as pd
import pytest

from src.orchestration.build_investment_committee import main


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_yaml(path, text):
    path.write_text(text, encoding="utf-8")


def _lineage(**overrides):
    base = {
        "e2e_run_id": "E2E-1", "universe_run_id": 1, "research_run_id": 2, "valuation_run_id": 3,
        "local_market_run_id": 4, "portfolio_run_id": 5, "g4_run_id": 6,
    }
    base.update(overrides)
    return base


def _setup_goal_inputs(tmp_path, *, nav_total_usd=50000.0, target_additional_usd=1000.0):
    portfolio_dir = tmp_path / "portfolio_state"; portfolio_dir.mkdir()
    _write_json(portfolio_dir / "portfolio_state_manifest.json", {
        "portfolio_state_validation": {"nav_total_usd": nav_total_usd},
    })
    goal_path = tmp_path / "financial_goal.yml"
    _write_yaml(goal_path, (
        "goal:\n"
        f"  target_additional_usd: {target_additional_usd}\n"
        "  set_as_of: \"2024-01-01\"\n"
        "  horizon_months: 24\n"
    ))
    return portfolio_dir / "portfolio_state_manifest.json", goal_path


def _setup_common(tmp_path, *, g4_manifest_overrides, g4_rows):
    g4_dir = tmp_path / "g4"; risk_dir = tmp_path / "risk"; out_dir = tmp_path / "out"
    g4_dir.mkdir(); risk_dir.mkdir()

    g4_lineage = _lineage()
    _write_json(g4_dir / "e2e_lineage.json", g4_lineage)
    g4_manifest = {
        "ticker_count": 30, "evaluated_count": 30, "blocked_count": 0,
        "pass_count": 0, "fail_count": 30, "g4_accounting_complete": True,
    }
    g4_manifest.update(g4_manifest_overrides)
    _write_json(g4_dir / "g4_manifest.json", g4_manifest)
    pd.DataFrame(g4_rows).to_parquet(g4_dir / "g4_cash_hurdle.parquet", index=False)

    risk_lineage = _lineage(decisional_risk_run_id=7)
    _write_json(risk_dir / "e2e_lineage.json", risk_lineage)
    risk_status = {"risk_status": "PASS", "risk_veto": "NO", "deployment_decision": "G4_CANDIDATES_MAY_PROCEED"}
    _write_json(risk_dir / "decisional_risk.json", risk_status)

    return g4_dir, risk_dir, out_dir


def _g4_row(ticker, **overrides):
    row = {
        "cedear_ticker": ticker, "g4_status": "G4_FAIL_DOWNSIDE", "risk_adjusted_er": 0.0,
        "bear_return_net": -0.10, "fx_stress_return_net": -0.10, "existing_weight": 0.0,
    }
    row.update(overrides)
    return row


def test_no_pass_candidates_keeps_new_trades_empty_and_status_no_action(tmp_path, monkeypatch, capsys):
    g4_dir, risk_dir, out_dir = _setup_common(
        tmp_path,
        g4_manifest_overrides={"pass_count": 0, "fail_count": 30, "deployment_decision": "NO_NEW_DEPLOYMENT"},
        g4_rows=[_g4_row(f"T{i}") for i in range(30)],
    )
    manifest_path, goal_path = _setup_goal_inputs(tmp_path)
    monkeypatch.setattr("sys.argv", [
        "build_investment_committee",
        "--g4-dir", str(g4_dir), "--risk-dir", str(risk_dir),
        "--output-dir", str(out_dir), "--committee-run-id", "999",
        "--portfolio-state-manifest", str(manifest_path), "--financial-goal", str(goal_path),
        "--as-of-date", "2024-01-01",
    ])
    main()
    decision = json.loads((out_dir / "committee_decision.json").read_text())
    shadow = json.loads((out_dir / "shadow_book.json").read_text())
    assert decision["decision"] == "HOLD_CASH_NO_ACTION"
    assert decision["new_trades"] == []
    assert decision["allocation_metrics"] is None
    assert shadow["status"] == "NO_ACTION_PERSISTED"
    assert shadow["order_count"] == 0

    goal = decision["goal_tracking"]
    assert goal["goal_status"] == "COMPUTABLE"
    assert goal["goal_current_nav_usd"] == 50000.0
    assert goal["goal_target_wealth_usd"] == 51000.0
    assert goal["goal_new_deployment_weighted_expected_return"] is None
    assert goal["goal_pace_status"] == "NO_NEW_DEPLOYMENT_THIS_CYCLE"


def test_pass_candidates_populate_sized_trades_and_pending_execution_status(tmp_path, monkeypatch):
    rows = [_g4_row(f"T{i}") for i in range(28)]
    rows.append(_g4_row("BEST", g4_status="G4_PASS", risk_adjusted_er=0.15, bear_return_net=-0.10, fx_stress_return_net=-0.08))
    rows.append(_g4_row("SECOND", g4_status="G4_PASS", risk_adjusted_er=0.10, bear_return_net=-0.09, fx_stress_return_net=-0.07))
    g4_dir, risk_dir, out_dir = _setup_common(
        tmp_path,
        g4_manifest_overrides={"pass_count": 2, "fail_count": 28, "deployment_decision": "ALLOW_NEW_DEPLOYMENT"},
        g4_rows=rows,
    )
    manifest_path, goal_path = _setup_goal_inputs(tmp_path)
    monkeypatch.setattr("sys.argv", [
        "build_investment_committee",
        "--g4-dir", str(g4_dir), "--risk-dir", str(risk_dir),
        "--output-dir", str(out_dir), "--committee-run-id", "1000",
        "--portfolio-state-manifest", str(manifest_path), "--financial-goal", str(goal_path),
        "--as-of-date", "2024-01-01",
    ])
    main()
    decision = json.loads((out_dir / "committee_decision.json").read_text())
    shadow = json.loads((out_dir / "shadow_book.json").read_text())

    assert decision["decision"] == "CANDIDATES_REQUIRE_EXECUTION_GATE"
    assert decision["fabricated_trade_count"] == 0
    assert len(decision["new_trades"]) == 2
    tickers = [t["cedear_ticker"] for t in decision["new_trades"]]
    assert tickers == ["BEST", "SECOND"]
    assert decision["new_trades"][0]["target_weight"] > 0
    assert decision["allocation_metrics"]["allocated_count"] == 2

    assert shadow["status"] == "PENDING_EXECUTION_GATE"
    assert shadow["order_count"] == 2 == len(shadow["orders"])

    goal = decision["goal_tracking"]
    assert goal["goal_status"] == "COMPUTABLE"
    # target_additional_usd=1000 on a 50000 NAV over 24 months is a required
    # annual return under 1% -- both BEST (0.15) and SECOND (0.10) clear it
    # by a wide margin regardless of how the allocator weights them.
    assert goal["goal_required_annual_return"] < 0.02
    assert goal["goal_new_deployment_weighted_expected_return"] is not None
    assert goal["goal_new_deployment_weighted_expected_return"] > goal["goal_required_annual_return"]
    assert goal["goal_pace_status"] == "NEW_DEPLOYMENT_MEETS_OR_EXCEEDS_PACE"
