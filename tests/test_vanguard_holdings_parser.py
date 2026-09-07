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


def test_vanguard_embedded_advisor_text_recovers_international_holdings():
    page = """
    <div>Holdings details as of June 30, 2026</div>
    <span>Samsung Electronics Co Ltd (005930)</span><span>3.12%</span>
    <span>SK hynix Inc (000660)</span><span>2.98%</span>
    <span>ASML Holding NV (ASML)</span><span>2.33%</span>
    <span>HSBC Holdings PLC (HSBA)</span><span>0.99%</span>
    """
    rows = IssuerHoldingsConnector._extract_vanguard_embedded_holdings(page)
    assert rows == [
        {"symbol": "005930", "percent": 3.12},
        {"symbol": "000660", "percent": 2.98},
        {"symbol": "ASML", "percent": 2.33},
        {"symbol": "HSBA", "percent": 0.99},
    ]


def test_vanguard_embedded_json_state_recovers_holdings():
    page = r'''<script>{"ticker":"NOVN","percentWeight":"0.89"},{"ticker":"RY","percentWeight":0.88}</script>'''
    rows = IssuerHoldingsConnector._extract_vanguard_embedded_holdings(page)
    assert rows == [
        {"symbol": "NOVN", "percent": 0.89},
        {"symbol": "RY", "percent": 0.88},
    ]


def test_vanguard_embedded_parser_rejects_cash_and_zero_weight():
    page = "Cash (USD) 1.00% Company (ABC) 0.00%"
    assert IssuerHoldingsConnector._extract_vanguard_embedded_holdings(page) == []
