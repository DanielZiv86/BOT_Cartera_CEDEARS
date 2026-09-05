import pandas as pd

from src.universe.loader import eligible_universe_frame, validate_universe
from src.universe.symbol_map import build_symbol_map


def _sample_payload():
    return {
        "version": "test-v1",
        "Universe_Count": 2,
        "Eligible_Count": 2,
        "rows": [
            {
                "cedear_ticker": "BRKB",
                "underlying_ticker": "BRK/B",
                "issuer_name": "Berkshire Hathaway",
                "instrument_type": "Acción",
                "ratio": 20.0,
                "underlying_market": "NYSE",
                "comafi_status": "PRIMARY_ACTIVE",
                "caja_byma_status": "BASELINE_CROSS_VALIDATED",
                "eligible": True,
                "exclusion_reason": "NONE_APPLICABLE",
                "mandate_exception": False,
                "first_seen": "2026-09-04",
                "last_verified": "2026-09-04",
                "source_refs": ["test"],
                "source_dates": ["2026-09-04"],
                "universe_version": "test-v1",
                "row_status": "HYDRATED_BASELINE_VALIDATED",
            },
            {
                "cedear_ticker": "IWDA",
                "underlying_ticker": "IWDA",
                "issuer_name": "iShares Core MSCI World UCITS ETF",
                "instrument_type": "ETF tradicional",
                "ratio": 24.0,
                "underlying_market": "EUROCLEAR",
                "comafi_status": "PRIMARY_ACTIVE",
                "caja_byma_status": "BASELINE_CROSS_VALIDATED",
                "eligible": True,
                "exclusion_reason": "NONE_APPLICABLE",
                "mandate_exception": True,
                "first_seen": "2026-09-04",
                "last_verified": "2026-09-04",
                "source_refs": ["test"],
                "source_dates": ["2026-09-04"],
                "universe_version": "test-v1",
                "row_status": "HYDRATED_BASELINE_VALIDATED",
            },
        ],
    }


def test_universe_validation_passes():
    result = validate_universe(_sample_payload())
    assert result.is_valid
    assert result.eligible_rows == 2


def test_iwda_exception_is_enforced():
    payload = _sample_payload()
    payload["rows"][1]["mandate_exception"] = False
    result = validate_universe(payload)
    assert not result.is_valid
    assert any("IWDA" in error for error in result.errors)


def test_symbol_aliases_and_market_suffixes():
    frame = eligible_universe_frame(_sample_payload())
    aliases = {
        "mapping_version": "1.0",
        "providers": {
            "yahoo": {"BRK/B": "BRK-B", "IWDA": "IWDA.L"},
            "stooq": {"BRK/B": "BRK-B.US", "IWDA": "IWDA.UK"},
        },
        "market_suffixes": {"yahoo": {"EUROCLEAR": ".L"}},
    }
    result = build_symbol_map(frame, aliases, providers=("yahoo", "stooq"))
    assert isinstance(result, pd.DataFrame)
    brkb = result[result["cedear_ticker"] == "BRKB"].iloc[0]
    iwda = result[result["cedear_ticker"] == "IWDA"].iloc[0]
    assert brkb["yahoo_symbol"] == "BRK-B"
    assert brkb["stooq_symbol"] == "BRK-B.US"
    assert iwda["yahoo_symbol"] == "IWDA.L"
