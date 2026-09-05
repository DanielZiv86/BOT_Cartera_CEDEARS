from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def load_portfolio_state(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "portfolio_state_version", "snapshot_id", "as_of", "nav_total_usd",
        "cash_usd", "cash_weight", "cedear_weight", "positions",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError("portfolio state missing fields: " + ", ".join(missing))
    if not isinstance(payload["positions"], list) or not payload["positions"]:
        raise ValueError("portfolio state positions must be a non-empty list")
    return payload


def validate_portfolio_state(payload: dict[str, Any], tolerance: float = 1e-6) -> dict[str, Any]:
    positions = pd.DataFrame(payload["positions"])
    required_cols = {"cedear_ticker", "weight"}
    missing_cols = sorted(required_cols - set(positions.columns))
    if missing_cols:
        raise ValueError("portfolio positions missing columns: " + ", ".join(missing_cols))

    positions["weight"] = pd.to_numeric(positions["weight"], errors="coerce")
    if positions["weight"].isna().any() or (positions["weight"] <= 0).any():
        raise ValueError("all live position weights must be positive numbers")
    if positions["cedear_ticker"].duplicated().any():
        raise ValueError("portfolio positions contain duplicate tickers")

    risky_weight = float(positions["weight"].sum())
    cash_weight = float(payload["cash_weight"])
    total_weight = risky_weight + cash_weight
    declared_risky = float(payload["cedear_weight"])

    if abs(risky_weight - declared_risky) > tolerance:
        raise ValueError(f"position weights {risky_weight:.10f} != declared cedear_weight {declared_risky:.10f}")
    if abs(total_weight - 1.0) > tolerance:
        raise ValueError(f"portfolio weights including cash must equal 1.0; got {total_weight:.10f}")

    nav_total = float(payload["nav_total_usd"])
    cash_usd = float(payload["cash_usd"])
    implied_cash_weight = cash_usd / nav_total
    if abs(implied_cash_weight - cash_weight) > 1e-5:
        raise ValueError("cash USD and cash weight are inconsistent with NAV")

    return {
        "portfolio_state_status": "PORTFOLIO_STATE_VALIDATED",
        "portfolio_state_version": payload["portfolio_state_version"],
        "snapshot_id": payload["snapshot_id"],
        "as_of": payload["as_of"],
        "position_count": int(len(positions)),
        "risky_weight": risky_weight,
        "cash_weight": cash_weight,
        "total_weight": total_weight,
        "nav_total_usd": nav_total,
        "cash_usd": cash_usd,
    }


def positions_frame(payload: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(payload["positions"]).copy()
    frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce")
    return frame


def load_classification_registry(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries = payload.get("entries") or {}
    rows = [
        {"cedear_ticker": ticker, "sector": values.get("sector"), "factor": values.get("factor")}
        for ticker, values in entries.items()
    ]
    frame = pd.DataFrame(rows)
    sector = frame[["cedear_ticker", "sector"]].copy() if not frame.empty else pd.DataFrame()
    factor = frame[["cedear_ticker", "factor"]].copy() if not frame.empty else pd.DataFrame()
    meta = {
        "classification_version": payload.get("classification_version"),
        "classification_scope": payload.get("classification_scope"),
        "methodology": payload.get("methodology"),
    }
    return sector, factor, meta
