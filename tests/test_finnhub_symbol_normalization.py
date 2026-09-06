from src.connectors.finnhub import FinnhubConnector


def test_finnhub_normalizes_berkshire_class_b_symbols():
    assert FinnhubConnector._provider_symbol("BRK/B") == "BRK.B"
    assert FinnhubConnector._provider_symbol("BRKB") == "BRK.B"
    assert FinnhubConnector._provider_symbol("brk/b") == "BRK.B"


def test_finnhub_leaves_standard_symbols_unchanged():
    assert FinnhubConnector._provider_symbol("AAPL") == "AAPL"
    assert FinnhubConnector._provider_symbol("VIG") == "VIG"
