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


def test_vanguard_additional_fund_data_parses_equity_holdings_and_as_of_date():
    # Real shape of investor.vanguard.com/irr/funds/profile/{ticker}-AdditionalFundData,
    # the replacement for the old portfolio-holding/stock API (found 2026-09-14 --
    # that one now 301-redirects to Vanguard's Angular app shell instead of JSON).
    payload = {
        "holdingDetails": {
            "asOfDate": "07/31/2026",
            "equityHoldings": [
                {"ticker": "AVGO", "marketValuePercentage": "4.62%", "securityLongDescription": "Broadcom Inc"},
                {"ticker": "AAPL", "marketValuePercentage": "4.44%", "securityLongDescription": "Apple Inc"},
            ],
            "shortTermReservesHoldings": [{"marketValuePercentage": "0.29%", "securityLongDescription": "MKTLIQ"}],
        }
    }
    rows, as_of = IssuerHoldingsConnector._parse_vanguard_additional_fund_data(payload)
    assert rows == [{"symbol": "AVGO", "percent": 4.62}, {"symbol": "AAPL", "percent": 4.44}]
    assert as_of == "2026-07-31"


def test_vanguard_additional_fund_data_rejects_cash_and_zero_weight_entries():
    payload = {
        "holdingDetails": {
            "asOfDate": "07/31/2026",
            "equityHoldings": [
                {"ticker": "CASH", "marketValuePercentage": "1.00%"},
                {"ticker": "ABC", "marketValuePercentage": "0.00%"},
                {"ticker": "AAPL", "marketValuePercentage": "4.44%"},
            ],
        }
    }
    rows, as_of = IssuerHoldingsConnector._parse_vanguard_additional_fund_data(payload)
    assert rows == [{"symbol": "AAPL", "percent": 4.44}]
    assert as_of == "2026-07-31"


def test_vanguard_additional_fund_data_missing_holding_details_yields_no_rows_and_no_as_of():
    rows, as_of = IssuerHoldingsConnector._parse_vanguard_additional_fund_data({"historicalPrice": {}})
    assert rows == []
    assert as_of is None


def test_vanguard_additional_fund_data_unparseable_as_of_date_yields_none():
    payload = {"holdingDetails": {"asOfDate": "not-a-date", "equityHoldings": [{"ticker": "AAPL", "marketValuePercentage": "4.44%"}]}}
    rows, as_of = IssuerHoldingsConnector._parse_vanguard_additional_fund_data(payload)
    assert rows == [{"symbol": "AAPL", "percent": 4.44}]
    assert as_of is None
