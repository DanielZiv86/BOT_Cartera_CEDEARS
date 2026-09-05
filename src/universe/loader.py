from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .schema import UniverseValidationResult, validate_row


def load_universe_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    if not isinstance(payload, dict):
        raise ValueError("Universe payload must be a JSON object")
    if "rows" not in payload or not isinstance(payload["rows"], list):
        raise ValueError("Universe payload must contain a 'rows' list")
    return payload


def validate_universe(payload: dict[str, Any]) -> UniverseValidationResult:
    rows = payload["rows"]
    errors: list[str] = []
    tickers: list[str] = []
    valid_rows = 0

    for idx, row in enumerate(rows):
        row_errors = validate_row(row, idx)
        if row_errors:
            errors.extend(row_errors)
        else:
            valid_rows += 1
        tickers.append(str(row.get("cedear_ticker") or "").strip())

    duplicates = sorted({ticker for ticker in tickers if ticker and tickers.count(ticker) > 1})
    eligible_rows = sum(1 for row in rows if row.get("eligible") is True)

    declared_count = payload.get("Universe_Count")
    declared_eligible = payload.get("Eligible_Count")
    if declared_count is not None and int(declared_count) != len(rows):
        errors.append(
            f"Universe_Count mismatch: declared={declared_count}, actual={len(rows)}"
        )
    if declared_eligible is not None and int(declared_eligible) != eligible_rows:
        errors.append(
            f"Eligible_Count mismatch: declared={declared_eligible}, actual={eligible_rows}"
        )

    return UniverseValidationResult(
        total_rows=len(rows),
        eligible_rows=eligible_rows,
        valid_rows=valid_rows,
        invalid_rows=len(rows) - valid_rows,
        duplicate_tickers=tuple(duplicates),
        errors=tuple(errors),
    )


def eligible_universe_frame(payload: dict[str, Any]) -> pd.DataFrame:
    rows = [row for row in payload["rows"] if row.get("eligible") is True]
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("cedear_ticker").reset_index(drop=True)
    return frame
