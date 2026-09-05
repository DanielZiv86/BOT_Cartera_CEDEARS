from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import pandas as pd


def build_local_market_blocker_diagnostics(layer: pd.DataFrame) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    tickers: defaultdict[str, list[str]] = defaultdict(list)

    for _, row in layer.iterrows():
        ticker = str(row.get("cedear_ticker") or "").upper()
        reasons: list[str] = []
        if str(row.get("valuation_g4_local_gate") or "BLOCKED") == "BLOCKED":
            reasons.append("LOCAL_MARKET_GATE_BLOCKED")
        if pd.isna(row.get("analytical_local_ref_ars")) or not row.get("analytical_local_ref_ars"):
            reasons.append("LOCAL_ENTRY_REFERENCE_MISSING")
        if str(row.get("ratio_status") or "") not in {"VALIDATED_COMAFI", "VALIDATED", "PASS"}:
            reasons.append(f"RATIO_STATUS:{row.get('ratio_status') or 'MISSING'}")
        if str(row.get("market_ccl_crosscheck_status") or "") == "BLOCKED":
            reasons.append("CCL_CROSSCHECK_BLOCKED")
        if str(row.get("book_sanity_status") or "") == "BLOCKED":
            reasons.append("BOOK_SANITY_BLOCKED")
        if not row.get("provider"):
            reasons.append("LOCAL_PRICE_PROVIDER_MISSING")

        for reason in sorted(set(reasons)):
            counts[reason] += 1
            if ticker:
                tickers[reason].append(ticker)

    blocked = layer[layer.get("valuation_g4_local_gate", pd.Series(index=layer.index, dtype=object)).astype(str) == "BLOCKED"]
    return {
        "blocked_count": int(len(blocked)),
        "blocker_counts": dict(counts),
        "blocker_tickers": {k: sorted(v) for k, v in tickers.items()},
    }
