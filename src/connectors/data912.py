from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests


class Data912CedearConnector:
    name = "data912"
    provider_tier = "APPROVED_MARKET_DATA_FALLBACK"
    url = "https://data912.com/live/arg_cedears"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    @staticmethod
    def _first(row: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                return row[key]
        return None

    def get_panel(self) -> dict[str, dict[str, Any]]:
        response = requests.get(self.url, timeout=self.timeout, headers={"User-Agent": "CEDEAR-Data-Engine/1.0"})
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            for key in ("data", "results", "cedears", "items"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        if not isinstance(payload, list):
            raise ValueError("Unexpected Data912 CEDEAR payload shape")

        panel: dict[str, dict[str, Any]] = {}
        loaded_at = datetime.now(timezone.utc).isoformat()
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            symbol = self._first(raw, "symbol", "ticker", "simbolo", "Símbolo", "especie")
            if not symbol:
                continue
            ticker = str(symbol).strip().upper()
            last = self._first(raw, "c", "last", "price", "close", "ultimo", "Último", "ultimoPrecio")
            bid = self._first(raw, "px_bid", "bid", "bidPrice", "compra", "precioCompra")
            ask = self._first(raw, "px_ask", "ask", "askPrice", "venta", "precioVenta")
            volume = self._first(raw, "v", "volume", "nominalVolume", "volumenNominal", "volumen")
            cash_volume = self._first(raw, "cashVolume", "amountVolume", "volumenMonto", "monto")
            timestamp = self._first(raw, "timestamp", "date", "datetime", "fecha")
            panel[ticker] = {
                "cedear_ticker": ticker,
                "last_price_ars": _to_float(last),
                "bid_ars": _to_float(bid),
                "ask_ars": _to_float(ask),
                "nominal_volume": _to_float(volume),
                "cash_volume_ars": _to_float(cash_volume),
                "market_timestamp": str(timestamp) if timestamp is not None else None,
                "provider": self.name,
                "provider_tier": self.provider_tier,
                "source_ref": self.url,
                "loaded_at": loaded_at,
                "raw_keys": sorted(raw.keys()),
            }
        return panel


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None
