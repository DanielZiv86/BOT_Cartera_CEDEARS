import pandas as pd

from src.connectors.comafi import canonical_comafi_symbol
from src.connectors.issuer_holdings import IssuerHoldingsConnector
from src.market_data.local_market_recovery import recover_analytical_local_market


def test_comafi_iwda_ln_market_id_maps_to_canonical_iwda():
    assert canonical_comafi_symbol("IWDA LN", "IWDA LN") == "IWDA"
    assert canonical_comafi_symbol("AAPL", "AAPL") == "AAPL"
    assert canonical_comafi_symbol("UNRELATED VENUE", "OTHER") == ""


def test_ishares_ucits_table_normalizer_accepts_official_columns():
    frame = pd.DataFrame({"Issuer Ticker": ["NVDA", "AAPL"], "Name": ["NVIDIA", "APPLE"], "Weight (%)": [5.74, 5.10]})
    rows = IssuerHoldingsConnector._normalize_table(frame)
    assert rows == [{"symbol": "NVDA", "percent": 5.74}, {"symbol": "AAPL", "percent": 5.10}]


def test_iwda_analytical_reference_requires_validated_ratio_and_never_creates_execution_book():
    frame = pd.DataFrame([{
        "cedear_ticker":"IWDA", "universe_ratio":24.0, "ratio_used":24.0,
        "ratio_status":"RATIO_VALIDATED_COMAFI", "last_close":147.87,
        "analytical_local_ref_ars":None, "market_ccl_reference":1600.0,
        "implied_ccl":None, "market_ccl_crosscheck_status":"MARKET_CCL_CROSSCHECK_UNAVAILABLE",
        "ccl_status":"CCL_BLOCKED", "valuation_g4_local_gate":"BLOCKED",
        "last_price_ars":None, "bid_ars":None, "ask_ars":None,
        "effective_executable_buy_ars":None, "effective_executable_sell_ars":None,
        "execution_book_status":"BOOK_INVALID_OR_UNAVAILABLE", "spread_pct":None,
    }])
    out=recover_analytical_local_market(frame).iloc[0]
    assert round(out["analytical_local_ref_ars"],2)==round(147.87*1600/24,2)
    assert out["analysis_ready"]
    assert not out["execution_ready"]
    assert pd.isna(out["last_price_ars"]) and pd.isna(out["bid_ars"]) and pd.isna(out["ask_ars"])


def test_iwda_unverified_ratio_cannot_synthesize_reference_from_nothing():
    frame=pd.DataFrame([{
        "cedear_ticker":"IWDA","universe_ratio":24.0,"ratio_used":24.0,
        "ratio_status":"RATIO_UNVERIFIED_COMAFI","last_close":147.87,
        "analytical_local_ref_ars":None,"market_ccl_reference":1600.0,"implied_ccl":None,
        "market_ccl_crosscheck_status":"MARKET_CCL_CROSSCHECK_UNAVAILABLE","ccl_status":"CCL_BLOCKED",
        "valuation_g4_local_gate":"BLOCKED","execution_book_status":"BOOK_INVALID_OR_UNAVAILABLE",
        "effective_executable_buy_ars":None,"effective_executable_sell_ars":None,"spread_pct":None,
    }])
    out=recover_analytical_local_market(frame).iloc[0]
    assert pd.isna(out["analytical_local_ref_ars"])
    assert not out["analysis_ready"]
    assert not out["execution_ready"]
