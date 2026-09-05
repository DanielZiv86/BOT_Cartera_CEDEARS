from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests


US_MARKET_MARKERS = ("NYSE", "NASDAQ", "CBOE", "NEW YORK")


def _stooq_transport_symbol(symbol: str, market: str | None) -> str:
    value = symbol.strip()
    upper = (market or "").upper()
    if any(marker in upper for marker in US_MARKET_MARKERS) and "." not in value:
        return f"{value}.US"
    return value


def fetch_yahoo_history(symbol: str, range_value: str = "2y", timeout: int = 20) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    encoded = quote(symbol, safe=".-^")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
    response = requests.get(
        url,
        params={
            "range": range_value,
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        },
        headers={"User-Agent": "Mozilla/5.0 BOT_Cartera_CEDEARS/1.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None, {"provider": "yahoo", "source_ref": response.url, "error": "NO_RESULT"}

    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_data = (indicators.get("quote") or [{}])[0]
    adj_data = (indicators.get("adjclose") or [{}])[0]
    adjusted = adj_data.get("adjclose") or [None] * len(timestamps)
    metadata = result.get("meta") or {}

    rows = []
    for idx, ts in enumerate(timestamps):
        close = (quote_data.get("close") or [None] * len(timestamps))[idx]
        if close is None:
            continue
        try:
            close_value = float(close)
        except (TypeError, ValueError):
            continue
        if close_value <= 0:
            continue
        def val(name: str):
            arr = quote_data.get(name) or []
            raw = arr[idx] if idx < len(arr) else None
            try:
                return float(raw) if raw is not None else None
            except (TypeError, ValueError):
                return None
        adj_raw = adjusted[idx] if idx < len(adjusted) else None
        try:
            adj_value = float(adj_raw) if adj_raw is not None else None
        except (TypeError, ValueError):
            adj_value = None
        rows.append({
            "date": datetime.fromtimestamp(int(ts), tz=timezone.utc).date(),
            "open": val("open"),
            "high": val("high"),
            "low": val("low"),
            "close": close_value,
            "adjusted_close": adj_value,
            "volume": val("volume"),
        })

    if not rows:
        return None, {"provider": "yahoo", "source_ref": response.url, "error": "NO_VALID_ROWS"}
    return pd.DataFrame(rows), {
        "provider": "yahoo",
        "provider_tier": "APPROVED_MARKET_DATA_FALLBACK",
        "source_ref": response.url,
        "currency": metadata.get("currency"),
        "adjustment_status": "ADJUSTED_AVAILABLE" if any(r["adjusted_close"] is not None for r in rows) else "UNADJUSTED_ONLY",
        "confidence": "HIGH_SECONDARY",
    }


def fetch_stooq_history(symbol: str, market: str | None, timeout: int = 20) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    transport_symbol = _stooq_transport_symbol(symbol, market)
    end = date.today()
    start = end - timedelta(days=800)
    response = requests.get(
        "https://stooq.com/q/d/l/",
        params={
            "s": transport_symbol.lower(),
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
            "i": "d",
        },
        headers={"User-Agent": "Mozilla/5.0 BOT_Cartera_CEDEARS/1.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    text = response.text.strip()
    if not text or text.lower().startswith("no data"):
        return None, {"provider": "stooq", "source_ref": response.url, "error": "NO_DATA"}
    frame = pd.read_csv(StringIO(text))
    required = {"Date", "Close"}
    if frame.empty or not required.issubset(frame.columns):
        return None, {"provider": "stooq", "source_ref": response.url, "error": "INVALID_SCHEMA"}
    frame = frame.rename(columns={"Date":"date","Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"])
    frame = frame[frame["close"] > 0].copy()
    if frame.empty:
        return None, {"provider": "stooq", "source_ref": response.url, "error": "NO_VALID_ROWS"}
    for col in ["open", "high", "low", "volume"]:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        else:
            frame[col] = None
    frame["adjusted_close"] = None
    return frame[["date","open","high","low","close","adjusted_close","volume"]], {
        "provider": "stooq",
        "provider_tier": "APPROVED_MARKET_DATA_FALLBACK",
        "source_ref": response.url,
        "currency": None,
        "adjustment_status": "UNADJUSTED_ONLY",
        "confidence": "MEDIUM_FALLBACK",
    }


def _classify_history(frame: pd.DataFrame | None) -> str:
    if frame is None or frame.empty:
        return "HISTORY_BLOCKED"
    count = len(frame)
    start = min(frame["date"])
    end = max(frame["date"])
    span_days = (end - start).days
    if count >= 200 and span_days >= 300:
        return "HISTORY_READY"
    if count >= 20 and span_days < 365:
        return "SHORT_HISTORY_BY_AGE"
    return "HISTORY_BLOCKED"


def build_underlying_history(symbol_map: pd.DataFrame, max_workers: int = 12) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    long_frames: list[pd.DataFrame] = []
    statuses: list[dict[str, Any]] = []

    def process(row: dict[str, Any]) -> tuple[pd.DataFrame | None, dict[str, Any]]:
        attempts = []
        market = row.get("underlying_market")
        providers = [
            ("yahoo", row.get("yahoo_symbol")),
            ("stooq", row.get("stooq_symbol")),
        ]
        selected_frame = None
        selected_meta = None
        selected_symbol = None
        for provider, symbol in providers:
            if not symbol:
                attempts.append({"provider": provider, "status": "NO_SYMBOL"})
                continue
            try:
                if provider == "yahoo":
                    frame, meta = fetch_yahoo_history(str(symbol))
                else:
                    frame, meta = fetch_stooq_history(str(symbol), market)
                if frame is not None and not frame.empty:
                    selected_frame, selected_meta, selected_symbol = frame, meta, str(symbol)
                    attempts.append({"provider": provider, "status": "SUCCESS", "observations": len(frame)})
                    break
                attempts.append({"provider": provider, "status": "NO_DATA"})
            except Exception as exc:
                attempts.append({"provider": provider, "status": "ERROR", "error": type(exc).__name__})

        state = _classify_history(selected_frame)
        status = {
            "cedear_ticker": row.get("cedear_ticker"),
            "canonical_underlying": row.get("canonical_underlying"),
            "underlying_market": market,
            "history_status": state,
            "provider_selected": (selected_meta or {}).get("provider"),
            "provider_symbol": selected_symbol,
            "provider_tier": (selected_meta or {}).get("provider_tier"),
            "history_start_date": str(min(selected_frame["date"])) if selected_frame is not None and not selected_frame.empty else None,
            "history_end_date": str(max(selected_frame["date"])) if selected_frame is not None and not selected_frame.empty else None,
            "history_observation_count": int(len(selected_frame)) if selected_frame is not None else 0,
            "history_frequency": "1d" if selected_frame is not None else None,
            "history_currency": (selected_meta or {}).get("currency"),
            "adjustment_status": (selected_meta or {}).get("adjustment_status"),
            "history_confidence": (selected_meta or {}).get("confidence"),
            "source_ref": (selected_meta or {}).get("source_ref"),
            "attempted_providers": attempts,
        }
        if selected_frame is not None and not selected_frame.empty:
            output = selected_frame.copy()
            output.insert(0, "cedear_ticker", row.get("cedear_ticker"))
            output.insert(1, "canonical_underlying", row.get("canonical_underlying"))
            output["provider"] = (selected_meta or {}).get("provider")
            output["currency"] = (selected_meta or {}).get("currency")
            return output, status
        return None, status

    records = symbol_map.to_dict(orient="records")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process, row): row.get("cedear_ticker") for row in records}
        for future in as_completed(futures):
            frame, status = future.result()
            statuses.append(status)
            if frame is not None:
                long_frames.append(frame)

    status_df = pd.DataFrame(statuses).sort_values("cedear_ticker").reset_index(drop=True)
    history_df = pd.concat(long_frames, ignore_index=True) if long_frames else pd.DataFrame()
    if not history_df.empty:
        history_df = history_df.sort_values(["cedear_ticker", "date"]).reset_index(drop=True)

    ready = int((status_df["history_status"] == "HISTORY_READY").sum())
    short = int((status_df["history_status"] == "SHORT_HISTORY_BY_AGE").sum())
    blocked = int((status_df["history_status"] == "HISTORY_BLOCKED").sum())
    metrics = {
        "eligible_count": int(len(status_df)),
        "history_ready_count": ready,
        "short_history_by_age_count": short,
        "history_data_ready_total_count": ready + short,
        "history_data_ready_pct": round((ready + short) / len(status_df) * 100, 2) if len(status_df) else 0.0,
        "history_blocked_count": blocked,
        "total_observations": int(len(history_df)),
        "provider_distribution": status_df["provider_selected"].fillna("BLOCKED").value_counts().to_dict(),
        "pass_history_data": (ready + short) == len(status_df),
    }
    return history_df, status_df, metrics
