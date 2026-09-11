import json

import pandas as pd
import pytest

from src.orchestration.build_investment_committee import main


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _lineage(**overrides):
    base = {
        "e2e_run_id": "E2E-1", "universe_run_id": 1, "research_run_id": 2, "valuation_run_id": 3,
        "local_market_run_id": 4, "portfolio_run_id": 5, "g4_run_id": 6,
    }
    base.update(overrides)
    return base


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
    monkeypatch.setattr("sys.argv", [
        "build_investment_committee",
        "--g4-dir", str(g4_dir), "--risk-dir", str(risk_dir),
        "--output-dir", str(out_dir), "--committee-run-id", "999",
    ])
    main()
    decision = json.loads((out_dir / "committee_decision.json").read_text())
    shadow = json.loads((out_dir / "shadow_book.json").read_text())
    assert decision["decision"] == "HOLD_CASH_NO_ACTION"
    assert decision["new_trades"] == []
    assert decision["allocation_metrics"] is None
    assert shadow["status"] == "NO_ACTION_PERSISTED"
    assert shadow["order_count"] == 0


def test_pass_candidates_populate_sized_trades_and_pending_execution_status(tmp_path, monkeypatch):
    rows = [_g4_row(f"T{i}") for i in range(28)]
    rows.append(_g4_row("BEST", g4_status="G4_PASS", risk_adjusted_er=0.15, bear_return_net=-0.10, fx_stress_return_net=-0.08))
    rows.append(_g4_row("SECOND", g4_status="G4_PASS", risk_adjusted_er=0.10, bear_return_net=-0.09, fx_stress_return_net=-0.07))
    g4_dir, risk_dir, out_dir = _setup_common(
        tmp_path,
        g4_manifest_overrides={"pass_count": 2, "fail_count": 28, "deployment_decision": "ALLOW_NEW_DEPLOYMENT"},
        g4_rows=rows,
    )
    monkeypatch.setattr("sys.argv", [
        "build_investment_committee",
        "--g4-dir", str(g4_dir), "--risk-dir", str(risk_dir),
        "--output-dir", str(out_dir), "--committee-run-id", "1000",
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
