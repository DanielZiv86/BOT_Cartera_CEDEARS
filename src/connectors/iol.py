from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests


class IOLCedearConnector:
    name = "iol"
    provider_tier = "PRIMARY_OFFICIAL_BROKER_MARKET_DATA"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.base_url = os.getenv("IOL_API_BASE", "https://api.invertironline.com")
        self.username = os.getenv("IOL_USERNAME")
        self.password = os.getenv("IOL_PASSWORD")
        self._access_token: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password)

    def _login(self) -> str:
        if self._access_token:
            return self._access_token
        if not self.configured:
            raise RuntimeError("IOL credentials are not configured")
        response = requests.post(
            f"{self.base_url}/token",
            data={"username": self.username, "password": self.password, "grant_type": "password"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ValueError("IOL token response missing access_token")
        self._access_token = str(token)
        return self._access_token

    @staticmethod
    def _money(payload: Any) -> float | None:
        if payload is None:
            return None
        if isinstance(payload, (int, float)):
            return float(payload)
        if isinstance(payload, dict):
            for key in ("valor", "value", "precio", "price"):
                if payload.get(key) is not None:
                    return float(payload[key])
        return None

    def get_quote(self, ticker: str, term: str = "t1") -> dict[str, Any]:
        token = self._login()
        url = f"{self.base_url}/api/v2/bCBA/Titulos/{ticker}/Cotizacion"
        response = requests.get(
            url,
            params={"plazo": term},
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        raw = response.json()

        last = self._money(raw.get("ultimoPrecio") or raw.get("lastPrice") or raw.get("precioUltimo"))
        bid = self._money(raw.get("puntas", {}).get("precioCompra") if isinstance(raw.get("puntas"), dict) else raw.get("precioCompra"))
        ask = self._money(raw.get("puntas", {}).get("precioVenta") if isinstance(raw.get("puntas"), dict) else raw.get("precioVenta"))
        if isinstance(raw.get("puntas"), list) and raw["puntas"]:
            first = raw["puntas"][0]
            bid = bid or self._money(first.get("precioCompra"))
            ask = ask or self._money(first.get("precioVenta"))

        return {
            "cedear_ticker": ticker.upper(),
            "last_price_ars": last,
            "bid_ars": bid,
            "ask_ars": ask,
            "nominal_volume": _to_float(raw.get("volumenNominal") or raw.get("totalNominal")),
            "cash_volume_ars": _to_float(raw.get("montoOperado") or raw.get("volumenMonto")),
            "market_timestamp": str(raw.get("fechaHora") or raw.get("timestamp") or raw.get("fecha")) if raw else None,
            "provider": self.name,
            "provider_tier": self.provider_tier,
            "source_ref": url,
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "raw_keys": sorted(raw.keys()) if isinstance(raw, dict) else [],
        }


def _to_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
