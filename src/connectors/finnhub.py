from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


class FinnhubError(RuntimeError):
    pass


class FinnhubRateLimit(FinnhubError):
    pass


class FinnhubAccessDenied(FinnhubError):
    pass


@dataclass
class FinnhubConnector:
    token: str | None = None
    timeout: int = 15
    # Conservative sustained cadence. If Finnhub still returns 429, perform one
    # short bounded backoff and fail fast instead of sleeping for minutes.
    min_interval_seconds: float = 1.05
    max_retries: int = 2
    default_rate_limit_sleep_seconds: float = 3.0
    max_rate_limit_sleep_seconds: float = 10.0

    def __post_init__(self) -> None:
        self.token = self.token or os.getenv("FINNHUB_TOKEN", "")
        self.base_url = "https://finnhub.io/api/v1"
        self._cache: dict[tuple[str, tuple[tuple[str, Any], ...]], Any] = {}
        self._last_call = 0.0
        self._request_count = 0
        self._cache_hit_count = 0
        self._rate_limit_count = 0
        self._rate_limit_sleep_seconds_total = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.token)

    @staticmethod
    def _provider_symbol(symbol: str) -> str:
        """Normalize canonical symbols only where Finnhub uses different notation."""
        ticker = str(symbol).strip().upper()
        return {"BRK/B": "BRK.B", "BRKB": "BRK.B"}.get(ticker, ticker)

    def _get(self, endpoint: str, **params: Any) -> Any:
        if not self.token:
            raise FinnhubAccessDenied("FINNHUB_TOKEN_NOT_CONFIGURED")
        key = (endpoint, tuple(sorted(params.items())))
        if key in self._cache:
            self._cache_hit_count += 1
            return self._cache[key]

        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    f"{self.base_url}{endpoint}",
                    params={**params, "token": self.token},
                    timeout=self.timeout,
                    headers={"User-Agent": "CEDEAR-Valuation-Engine/1.4"},
                )
                self._request_count += 1
                self._last_call = time.monotonic()
                if response.status_code in {401, 403}:
                    raise FinnhubAccessDenied(f"FINNHUB_ACCESS_{response.status_code}")
                if response.status_code == 429:
                    self._rate_limit_count += 1
                    retry_after = response.headers.get("Retry-After")
                    try:
                        requested_delay = float(retry_after) if retry_after is not None else self.default_rate_limit_sleep_seconds
                    except ValueError:
                        requested_delay = self.default_rate_limit_sleep_seconds
                    last_error = FinnhubRateLimit("FINNHUB_RATE_LIMIT_429")
                    if attempt >= self.max_retries - 1:
                        raise last_error
                    delay = max(self.min_interval_seconds, min(requested_delay, self.max_rate_limit_sleep_seconds))
                    self._rate_limit_sleep_seconds_total += delay
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                data = response.json()
                self._cache[key] = data
                return data
            except FinnhubAccessDenied:
                raise
            except FinnhubRateLimit as exc:
                last_error = exc
                if attempt >= self.max_retries - 1:
                    break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 4))
        raise FinnhubError(str(last_error or "FINNHUB_REQUEST_FAILED"))

    def price_target(self, symbol: str) -> dict[str, Any]:
        data = self._get("/stock/price-target", symbol=self._provider_symbol(symbol))
        return data if isinstance(data, dict) else {}

    def recommendation_trends(self, symbol: str) -> list[dict[str, Any]]:
        data = self._get("/stock/recommendation", symbol=self._provider_symbol(symbol))
        return data if isinstance(data, list) else []

    def basic_financials(self, symbol: str) -> dict[str, Any]:
        data = self._get("/stock/metric", symbol=self._provider_symbol(symbol), metric="all")
        return data if isinstance(data, dict) else {}

    def quote(self, symbol: str) -> dict[str, Any]:
        data = self._get("/quote", symbol=self._provider_symbol(symbol))
        return data if isinstance(data, dict) else {}

    def etf_profile(self, symbol: str) -> dict[str, Any]:
        data = self._get("/etf/profile", symbol=symbol)
        return data if isinstance(data, dict) else {}

    def etf_holdings(self, symbol: str) -> dict[str, Any]:
        data = self._get("/etf/holdings", symbol=symbol)
        return data if isinstance(data, dict) else {}

    def diagnostics(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "min_interval_seconds": self.min_interval_seconds,
            "request_timeout_seconds": self.timeout,
            "max_retries": self.max_retries,
            "request_count": self._request_count,
            "cache_hit_count": self._cache_hit_count,
            "rate_limit_429_count": self._rate_limit_count,
            "rate_limit_sleep_seconds_total": round(self._rate_limit_sleep_seconds_total, 3),
        }

    @staticmethod
    def retrieved_at() -> str:
        return datetime.now(timezone.utc).isoformat()
