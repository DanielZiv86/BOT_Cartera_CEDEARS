from datetime import date

from src.valuation.etf_engine import _holding_scenario_return


class InternationalFinnhubStub:
    def __init__(self):
        self.queries = []
        self.quotes = []
        self.targets = []

    def symbol_search(self, query):
        self.queries.append(query)
        if query == "005930":
            return [
                {"symbol": "005930.KS", "displaySymbol": "005930", "description": "Samsung Electronics", "type": "Common Stock"},
                {"symbol": "005935.KS", "displaySymbol": "005935", "description": "Samsung Electronics Pref", "type": "Common Stock"},
            ]
        return []

    def quote(self, symbol):
        self.quotes.append(symbol)
        if symbol == "005930.KS":
            return {"c": 100.0}
        return {}

    def price_target(self, symbol):
        self.targets.append(symbol)
        if symbol == "005930.KS":
            return {"targetHigh": 140.0, "targetMean": 120.0, "targetMedian": 118.0, "targetLow": 85.0, "numberAnalysts": 20, "lastUpdated": "2026-09-01"}
        return {}


def test_international_constituent_resolves_exact_base_exchange_symbol():
    connector = InternationalFinnhubStub()
    scenario, error = _holding_scenario_return("005930", connector, 45, date(2026, 9, 7))
    assert error is None
    assert scenario is not None
    assert scenario["resolved_symbol"] == "005930.KS"
    assert scenario["bear"] < scenario["base"] < scenario["bull"]
    assert connector.queries == ["005930"]
    assert "005935.KS" not in connector.quotes


def test_international_constituent_fails_closed_without_exact_base_match():
    class AmbiguousStub(InternationalFinnhubStub):
        def symbol_search(self, query):
            return [{"symbol": "SAMSUNG.OTHER", "displaySymbol": "SAMSUNG", "type": "Common Stock"}]

    scenario, error = _holding_scenario_return("005930", AmbiguousStub(), 45, date(2026, 9, 7))
    assert scenario is None
    assert error == "HOLDING_TARGET_MISSING"
