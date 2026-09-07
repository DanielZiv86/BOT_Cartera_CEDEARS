from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import pandas as pd


PASSABLE_RATIO_STATUSES = {"RATIO_VALIDATED_COMAFI", "RATIO_VALIDATED_CANONICAL_CCL"}
PASSABLE_LOCAL_GATES = {"PASS", "PASS_WITH_WARNING"}


def build_local_market_blocker_diagnostics(layer: pd.DataFrame) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    tickers: defaultdict[str, list[str]] = defaultdict(list)

    for _, row in layer.iterrows():
        ticker = str(row.get("cedear_ticker") or "").upper()
        reasons: list[str] = []
        local_gate = str(row.get("valuation_g4_local_gate") or "BLOCKED")
        if local_gate not in PASSABLE_LOCAL_GATES:
            reasons.append("LOCAL_MARKET_GATE_BLOCKED")
        if pd.isna(row.get("analytical_local_ref_ars")) or not row.get("analytical_local_ref_ars"):
            reasons.append("LOCAL_ENTRY_REFERENCE_MISSING")
        ratio_status = str(row.get("ratio_status") or "")
        if ratio_status not in PASSABLE_RATIO_STATUSES:
            reasons.append(f"RATIO_STATUS:{ratio_status or 'MISSING'}")
        if str(row.get("market_ccl_crosscheck_status") or "") == "MARKET_CCL_CROSSCHECK_BLOCKED":
            reasons.append("CCL_CROSSCHECK_BLOCKED")
        if str(row.get("book_sanity_status") or "") == "BOOK_INVALID_SANITY":
            reasons.append("BOOK_SANITY_BLOCKED")
        if not row.get("provider"):
            reasons.append("LOCAL_PRICE_PROVIDER_MISSING")
        if bool(row.get("analytical_recovery_applied")):
            reasons.append("ANALYTICAL_RECOVERY_APPLIED_NOT_EXECUTION_READY")

        for reason in sorted(set(reasons)):
            counts[reason] += 1
            if ticker:
                tickers[reason].append(ticker)

    blocked = layer[~layer.get("valuation_g4_local_gate", pd.Series(index=layer.index, dtype=object)).astype(str).isin(PASSABLE_LOCAL_GATES)]
    return {
        "blocked_count": int(len(blocked)),
        "blocker_counts": dict(counts),
        "blocker_tickers": {k: sorted(v) for k, v in tickers.items()},
    }
