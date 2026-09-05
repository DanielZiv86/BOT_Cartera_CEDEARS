from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import numpy as np


def as_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for candidate in (text[:10], text):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return None


def age_days(value: Any, as_of: date | None = None) -> int | None:
    d = parse_date(value)
    if d is None:
        return None
    ref = as_of or datetime.now(timezone.utc).date()
    return (ref - d).days


def latest_series_period(financials: dict[str, Any]) -> date | None:
    series = financials.get("series") if isinstance(financials, dict) else None
    if not isinstance(series, dict):
        return None
    dates: list[date] = []
    for frequency in series.values():
        if not isinstance(frequency, dict):
            continue
        for observations in frequency.values():
            if not isinstance(observations, list):
                continue
            for obs in observations:
                if isinstance(obs, dict):
                    d = parse_date(obs.get("period"))
                    if d:
                        dates.append(d)
    return max(dates) if dates else None


def normalized_probabilities(values: tuple[float, float, float]) -> tuple[float, float, float]:
    arr = np.array(values, dtype=float)
    arr = np.clip(arr, 0.0, None)
    total = float(arr.sum())
    if total <= 0:
        return 0.25, 0.50, 0.25
    arr = arr / total
    return float(arr[0]), float(arr[1]), float(arr[2])
