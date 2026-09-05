from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_UNIVERSE_FIELDS = (
    "cedear_ticker",
    "underlying_ticker",
    "issuer_name",
    "instrument_type",
    "ratio",
    "underlying_market",
    "comafi_status",
    "caja_byma_status",
    "eligible",
    "exclusion_reason",
    "mandate_exception",
    "first_seen",
    "last_verified",
    "source_refs",
    "source_dates",
    "universe_version",
    "row_status",
)


@dataclass(frozen=True)
class UniverseValidationResult:
    total_rows: int
    eligible_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_tickers: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return self.invalid_rows == 0 and not self.duplicate_tickers


def validate_row(row: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    missing = [field for field in REQUIRED_UNIVERSE_FIELDS if field not in row]
    if missing:
        errors.append(f"row {index}: missing fields {missing}")
        return errors

    ticker = str(row.get("cedear_ticker") or "").strip()
    underlying = str(row.get("underlying_ticker") or "").strip()
    if not ticker:
        errors.append(f"row {index}: cedear_ticker is empty")
    if not underlying:
        errors.append(f"row {index}: underlying_ticker is empty")

    try:
        ratio = float(row.get("ratio"))
        if ratio <= 0:
            errors.append(f"row {index} {ticker}: ratio must be > 0")
    except (TypeError, ValueError):
        errors.append(f"row {index} {ticker}: ratio is not numeric")

    if not isinstance(row.get("eligible"), bool):
        errors.append(f"row {index} {ticker}: eligible must be boolean")
    if not isinstance(row.get("mandate_exception"), bool):
        errors.append(f"row {index} {ticker}: mandate_exception must be boolean")
    if not isinstance(row.get("source_refs"), list) or not row.get("source_refs"):
        errors.append(f"row {index} {ticker}: source_refs must be a non-empty list")
    if not isinstance(row.get("source_dates"), list) or not row.get("source_dates"):
        errors.append(f"row {index} {ticker}: source_dates must be a non-empty list")

    if ticker == "IWDA" and not row.get("mandate_exception"):
        errors.append("IWDA must retain mandate_exception=true")

    return errors
