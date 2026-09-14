import json

import pandas as pd

from src.orchestration.build_decisional_risk import main


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _setup(tmp_path, *, deployment_decision, blocked_count, ranking_status="COMPLETE_WITH_DATA_GAPS", evaluated_count=29, ticker_count=30):
    g4_dir = tmp_path / "g4"; g4_dir.mkdir()
    portfolio_dir = tmp_path / "portfolio"; portfolio_dir.mkdir()
    lineage = {
        "e2e_run_id": "E2E-1", "research_run_id": 2, "universe_run_id": 1,
        "valuation_run_id": 3, "local_market_run_id": 4, "portfolio_run_id": 5, "g4_run_id": 6,
    }
    _write_json(g4_dir / "e2e_lineage.json", lineage)
    manifest = {
        "ticker_count": ticker_count, "evaluated_count": evaluated_count, "blocked_count": blocked_count,
        "ranking_status": ranking_status, "deployment_decision": deployment_decision,
        "cash_optimality_status": "CASH_NOT_OPTIMAL_BY_MODEL",
        "pass_count": 1, "fail_count": max(evaluated_count - 1, 0),
    }
    _write_json(g4_dir / "g4_manifest.json", manifest)
    pd.DataFrame([{"cedear_ticker": "A", "weight": 0.1}]).to_parquet(portfolio_dir / "portfolio_positions.parquet", index=False)
    _write_json(portfolio_dir / "portfolio_state_manifest.json", {
        "portfolio_state_validation": {"portfolio_state_status": "PORTFOLIO_STATE_VALIDATED"},
        "portfolio_risk": {"portfolio_risk_status": "PORTFOLIO_RISK_READY"},
    })
    return g4_dir, portfolio_dir


def test_clean_candidates_allowed_to_proceed_despite_unrelated_blocked_ticker(tmp_path, monkeypatch):
    # 2026-09-12 fix: Risk used to re-impose its own independent data-gap
    # veto (blocked_count>0 => NO_NEW_DEPLOYMENT) even when G4's own
    # deployment_decision already correctly allowed deployment around an
    # unrelated blocked ticker -- double-counting the same isolated gap.
    g4_dir, portfolio_dir = _setup(tmp_path, deployment_decision="ALLOW_NEW_DEPLOYMENT", blocked_count=1)
    out_dir = tmp_path / "out"
    monkeypatch.setattr("sys.argv", [
        "build_decisional_risk", "--g4-dir", str(g4_dir), "--portfolio-dir", str(portfolio_dir),
        "--output-dir", str(out_dir), "--risk-run-id", "999",
    ])
    main()
    payload = json.loads((out_dir / "decisional_risk.json").read_text())
    assert payload["deployment_decision"] == "G4_CANDIDATES_MAY_PROCEED"
    assert payload["risk_status"] == "PASS"
    assert payload["risk_veto"] == "NO"
    assert payload["data_gap_hold"] is True


def test_no_deployment_when_g4_itself_holds_on_data_gaps(tmp_path, monkeypatch):
    g4_dir, portfolio_dir = _setup(tmp_path, deployment_decision="NO_NEW_DEPLOYMENT_DATA_GAPS", blocked_count=1)
    out_dir = tmp_path / "out"
    monkeypatch.setattr("sys.argv", [
        "build_decisional_risk", "--g4-dir", str(g4_dir), "--portfolio-dir", str(portfolio_dir),
        "--output-dir", str(out_dir), "--risk-run-id", "1000",
    ])
    main()
    payload = json.loads((out_dir / "decisional_risk.json").read_text())
    assert payload["deployment_decision"] == "NO_NEW_DEPLOYMENT"
