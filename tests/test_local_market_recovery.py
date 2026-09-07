import pandas as pd

from src.market_data.local_market_recovery import recover_analytical_local_market


def _base_row(**overrides):
    row = {
        "cedear_ticker": "AAA",
        "universe_ratio": 10.0,
        "ratio_used": 10.0,
        "ratio_status": "RATIO_VALIDATED_COMAFI",
        "last_close": 100.0,
        "analytical_local_ref_ars": 16000.0,
        "market_ccl_reference": 1600.0,
        "implied_ccl": 1600.0,
        "market_ccl_crosscheck_status": "MARKET_CCL_CROSSCHECK_PASS",
        "ccl_status": "CCL_READY_VALIDATED",
        "valuation_g4_local_gate": "PASS",
        "spread_pct": 0.01,
    }
    row.update(overrides)
    return row


def test_missing_local_quote_gets_analytical_reference_but_not_fake_price():
    frame = pd.DataFrame([
        _base_row(
            analytical_local_ref_ars=None,
            implied_ccl=None,
            market_ccl_crosscheck_status="MARKET_CCL_CROSSCHECK_UNAVAILABLE",
            ccl_status="CCL_BLOCKED",
            valuation_g4_local_gate="BLOCKED",
            last_price_ars=None,
            bid_ars=None,
            ask_ars=None,
        )
    ])
    out = recover_analytical_local_market(frame).iloc[0]
    assert out["analytical_local_ref_ars"] == 16000.0
    assert out["analytical_reference_method"] == "SYNTHETIC_FROM_UNDERLYING_MARKET_CCL_RATIO"
    assert out["valuation_g4_local_gate"] == "PASS_WITH_WARNING"
    assert pd.isna(out["last_price_ars"])
    assert pd.isna(out["bid_ars"])
    assert pd.isna(out["ask_ars"])


def test_bad_observed_quote_uses_theoretical_reference_for_analytical_g4():
    frame = pd.DataFrame([
        _base_row(
            analytical_local_ref_ars=10.0,
            implied_ccl=1.0,
            market_ccl_crosscheck_status="MARKET_CCL_CROSSCHECK_BLOCKED",
            ccl_status="CCL_BLOCKED_MARKET_DEVIATION",
            valuation_g4_local_gate="BLOCKED",
        )
    ])
    out = recover_analytical_local_market(frame).iloc[0]
    assert out["observed_analytical_local_ref_ars"] == 10.0
    assert out["analytical_local_ref_ars"] == 16000.0
    assert out["valuation_g4_local_gate"] == "PASS_WITH_WARNING"


def test_canonical_ratio_can_be_reconciled_independently_to_market_ccl():
    frame = pd.DataFrame([
        _base_row(
            ratio_status="RATIO_UNVERIFIED_COMAFI",
            ratio_used=2.0,
            universe_ratio=2.0,
            last_close=50.0,
            analytical_local_ref_ars=40000.0,
            market_ccl_reference=1600.0,
            implied_ccl=1600.0,
            ccl_status="CCL_READY_UNVERIFIED",
            valuation_g4_local_gate="BLOCKED",
        )
    ])
    out = recover_analytical_local_market(frame).iloc[0]
    assert out["ratio_status"] == "RATIO_VALIDATED_CANONICAL_CCL"
    assert out["ratio_validation_method"] == "CANONICAL_RATIO_PLUS_MARKET_CCL_RECONCILIATION"
    assert out["valuation_g4_local_gate"] == "PASS_WITH_WARNING"


def test_bad_canonical_ratio_is_not_recovered():
    frame = pd.DataFrame([
        _base_row(
            ratio_status="RATIO_UNVERIFIED_COMAFI",
            ratio_used=10.0,
            universe_ratio=10.0,
            last_close=100.0,
            analytical_local_ref_ars=1000.0,
            market_ccl_reference=1600.0,
            implied_ccl=100.0,
            market_ccl_crosscheck_status="MARKET_CCL_CROSSCHECK_BLOCKED",
            ccl_status="CCL_READY_UNVERIFIED",
            valuation_g4_local_gate="BLOCKED",
        )
    ])
    out = recover_analytical_local_market(frame).iloc[0]
    assert out["ratio_status"] == "RATIO_UNVERIFIED_COMAFI"
    assert out["valuation_g4_local_gate"] == "BLOCKED"
