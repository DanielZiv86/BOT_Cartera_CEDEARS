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
    """Validate the canonical hydrated universe payload.

    Contract note:
    - Universe_Count is the size of the reconciled source universe before exclusions.
    - Eligible_Count is the size of the hydrated rows persisted in ``rows``.

    The canonical v2 artifact intentionally persists only eligible hydrated rows while
    retaining Universe_Count as lineage for the broader reconciled source universe.
    Therefore len(rows) must reconcile to Eligible_Count, not Universe_Count.
    """

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

    declared_source_count = payload.get("Universe_Count")
    declared_eligible = payload.get("Eligible_Count")

    if declared_eligible is not None and int(declared_eligible) != len(rows):
        errors.append(
            f"Eligible_Count/rows mismatch: declared={declared_eligible}, actual_rows={len(rows)}"
        )

    if declared_eligible is not None and int(declared_eligible) != eligible_rows:
        errors.append(
            f"Eligible_Count mismatch: declared={declared_eligible}, actual_eligible={eligible_rows}"
        )

    if declared_source_count is not None and declared_eligible is not None:
        if int(declared_source_count) < int(declared_eligible):
            errors.append(
                "Universe_Count cannot be lower than Eligible_Count: "
                f"Universe_Count={declared_source_count}, Eligible_Count={declared_eligible}"
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
