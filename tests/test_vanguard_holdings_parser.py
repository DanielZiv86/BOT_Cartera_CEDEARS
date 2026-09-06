import pandas as pd

from src.connectors.issuer_holdings import IssuerHoldingsConnector


def test_vanguard_holdings_name_column_extracts_parenthesized_ticker():
    frame = pd.DataFrame(
        {
            "HOLDINGS": ["Broadcom Inc (AVGO)", "Apple Inc (AAPL)", "Microsoft Corp (MSFT)"],
            "% OF FUNDS": ["4.62%", "4.44%", "4.33%"],
        }
    )

    rows = IssuerHoldingsConnector._normalize_table(frame)

    assert rows == [
        {"symbol": "AVGO", "percent": 4.62},
        {"symbol": "AAPL", "percent": 4.44},
        {"symbol": "MSFT", "percent": 4.33},
    ]


def test_standard_ticker_column_behavior_is_preserved():
    frame = pd.DataFrame({"Ticker": ["AAPL"], "Weight (%)": ["5.0"]})
    assert IssuerHoldingsConnector._normalize_table(frame) == [{"symbol": "AAPL", "percent": 5.0}]
