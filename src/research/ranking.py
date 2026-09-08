from __future__ import annotations

import pandas as pd


def _deployment_eligible(result: pd.DataFrame) -> pd.Series:
    """Return deployment eligibility without removing names from universal ranking.

    Research must score/rank the whole canonical universe.  Selection for the
    downstream deployable Top-N is stricter: an explicit false tradability flag
    makes a name ineligible, while missing flags remain backward compatible.
    """
    eligible = pd.Series(True, index=result.index, dtype=bool)
    for column in ("byma_tradable", "deployment_eligible"):
        if column not in result.columns:
            continue
        values = result[column]
        explicit_false = values.map(
            lambda value: value is False
            or str(value).strip().lower() in {"false", "0", "no", "blocked", "not_tradable"}
        )
        eligible &= ~explicit_false
    return eligible


def build_ranking(screening: pd.DataFrame, top_n: int = 30, min_top_data_quality: float = 60.0) -> pd.DataFrame:
    """Rank every canonical ticker and select evidence-qualified deployable Top-N names."""
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
    evidence_ready = result["screening_status"].eq("SCORE_READY") & result["data_quality_score"].ge(min_top_data_quality)
    deployment_ready = _deployment_eligible(result)
    result["deployment_eligibility"] = deployment_ready
    result["top_n_eligibility"] = evidence_ready & deployment_ready
    result["selected"] = False
    eligible_positions = result.index[result["top_n_eligibility"]].tolist()[:top_n]
    result.loc[eligible_positions, "selected"] = True
    return result
