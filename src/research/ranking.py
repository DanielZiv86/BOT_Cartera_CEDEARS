from __future__ import annotations

import pandas as pd


def build_ranking(screening: pd.DataFrame, top_n: int = 30) -> pd.DataFrame:
    """Rank score-ready tickers deterministically and flag the Top-N.

    Blocked tickers remain in the output for full-universe auditability but receive
    neither rank nor selection status.
    """
    if top_n < 1:
        raise ValueError("top_n must be >= 1")
    required = {"cedear_ticker", "screening_score", "screening_status"}
    missing = sorted(required - set(screening.columns))
    if missing:
        raise ValueError("screening frame missing columns: " + ", ".join(missing))

    result = screening.copy()
    result["rank"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result["selected"] = False

    ready_mask = result["screening_status"].eq("SCORE_READY") & result["screening_score"].notna()
    ready = result.loc[ready_mask, ["cedear_ticker", "screening_score"]].copy()
    ready = ready.sort_values(
        ["screening_score", "cedear_ticker"],
        ascending=[False, True],
        kind="mergesort",
    )
    ready["rank"] = range(1, len(ready) + 1)

    rank_map = ready.set_index("cedear_ticker")["rank"]
    result.loc[ready_mask, "rank"] = result.loc[ready_mask, "cedear_ticker"].map(rank_map).astype("Int64")
    result.loc[ready_mask, "selected"] = result.loc[ready_mask, "rank"].le(top_n).fillna(False)

    return result.sort_values(
        ["rank", "cedear_ticker"],
        ascending=[True, True],
        na_position="last",
    ).reset_index(drop=True)
