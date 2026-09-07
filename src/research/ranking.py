from __future__ import annotations

import pandas as pd


def build_ranking(screening: pd.DataFrame, top_n: int = 30, min_top_data_quality: float = 60.0) -> pd.DataFrame:
    """Rank every canonical ticker and select evidence-qualified Top-N names."""
    if top_n < 1:
        raise ValueError("top_n must be >= 1")
    required = {"cedear_ticker", "screening_score", "screening_status", "data_quality_score"}
    missing = sorted(required - set(screening.columns))
    if missing:
        raise ValueError("screening frame missing columns: " + ", ".join(missing))
    if screening.empty or screening["cedear_ticker"].duplicated().any():
        raise ValueError("screening must contain unique canonical tickers")
    if screening["screening_score"].isna().any():
        raise ValueError("complete ranking requires a score for every canonical ticker")

    result = screening.copy().sort_values(
        ["screening_score", "data_quality_score", "cedear_ticker"],
        ascending=[False, False, True], kind="mergesort"
    ).reset_index(drop=True)
    result["rank"] = pd.Series(range(1, len(result) + 1), dtype="Int64")
    result["percentile"] = ((len(result) - result["rank"] + 1) / len(result) * 100.0).astype(float).round(2)
    eligible = result["screening_status"].eq("SCORE_READY") & result["data_quality_score"].ge(min_top_data_quality)
    result["top_n_eligibility"] = eligible
    result["selected"] = False
    eligible_positions = result.index[eligible].tolist()[:top_n]
    result.loc[eligible_positions, "selected"] = True
    return result
