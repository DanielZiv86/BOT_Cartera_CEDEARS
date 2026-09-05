from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

import requests


RATIO_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*:\s*(\d+(?:[.,]\d+)?)\s*$")


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_tr = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self.in_tr = True
            self.current_row = []
        elif self.in_tr and tag.lower() in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.in_tr and tag in {"td", "th"} and self.in_cell:
            text = " ".join(" ".join(self.current_cell).split())
            self.current_row.append(text)
            self.current_cell = []
            self.in_cell = False
        elif tag == "tr" and self.in_tr:
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
            self.in_tr = False


class ComafiRatioConnector:
    name = "comafi"
    provider_tier = "PRIMARY_OFFICIAL_PROGRAM_REGISTRY"
    url = "https://www.comafi.com.ar/Programas-CEDEARs-2483.note.aspx"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def get_ratios(self) -> dict[str, dict[str, Any]]:
        response = requests.get(
            self.url,
            timeout=self.timeout,
            headers={"User-Agent": "CEDEAR-Data-Engine/1.0"},
        )
        response.raise_for_status()
        parser = _TableParser()
        parser.feed(response.text)

        results: dict[str, dict[str, Any]] = {}
        for cells in parser.rows:
            # Current Comafi CEDEAR Shares table layout:
            # name, investor scope, ratio, CEDEAR ISIN, Caja code,
            # BYMA symbol, origin ticker, ...
            if len(cells) < 7:
                continue
            ratio_text = cells[2].strip()
            match = RATIO_RE.match(ratio_text)
            if not match:
                continue
            byma_symbol = cells[5].strip().upper()
            if not byma_symbol or " " in byma_symbol:
                continue
            numerator = float(match.group(1).replace(",", "."))
            denominator = float(match.group(2).replace(",", "."))
            if numerator <= 0 or denominator <= 0:
                continue
            multiplier = numerator / denominator
            record = {
                "cedear_ticker": byma_symbol,
                "comafi_ratio_text": ratio_text,
                "comafi_ratio_multiplier": multiplier,
                "comafi_program_name": cells[0],
                "comafi_underlying_ticker": cells[6].strip().upper(),
                "comafi_caja_code": cells[4].strip(),
                "comafi_source_ref": self.url,
                "ratio_provider": self.name,
                "ratio_provider_tier": self.provider_tier,
            }
            existing = results.get(byma_symbol)
            if existing and abs(float(existing["comafi_ratio_multiplier"]) - multiplier) > 1e-12:
                # Conflicting duplicate rows must not be silently accepted.
                existing["ratio_conflict"] = True
                existing.setdefault("conflicting_ratio_texts", []).append(ratio_text)
                continue
            record["ratio_conflict"] = False
            results[byma_symbol] = record
        return results
