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


def build_value_ranking(
    value_screening: pd.DataFrame,
    technical_screening: pd.DataFrame,
    top_n: int = 30,
    etf_slots: int = 6,
    min_timing_gate_score: float = 45.0,
    min_technical_data_quality: float = 60.0,
    min_value_data_quality: float = 50.0,
) -> tuple[pd.DataFrame, dict]:
    """SHADOW ranking: equities are selected by fundamentals (value_score);
    the existing technical screening_score is only a binary entry-timing gate
    for equities, never the ranking key. ETFs/non-equity keep exactly the
    technical-only ranking track build_ranking already uses, in a separate,
    reserved pool of slots so they never compete against equities on value.

    Neither track backfills into the other: if the equity track can't fill
    its slots (too many timing vetoes) or the ETF track can't fill its slots,
    the shortfall is reported, not silently papered over with a weaker name.
    """
    if top_n < 1:
        raise ValueError("top_n must be >= 1")
    if not 0 <= etf_slots <= top_n:
        raise ValueError("etf_slots must be between 0 and top_n")

    required_v = {"cedear_ticker", "value_score", "value_screening_status", "value_data_quality_score", "instrument_class"}
    missing_v = sorted(required_v - set(value_screening.columns))
    if missing_v:
        raise ValueError("value screening frame missing columns: " + ", ".join(missing_v))
    required_t = {"cedear_ticker", "screening_score", "screening_status", "data_quality_score"}
    missing_t = sorted(required_t - set(technical_screening.columns))
    if missing_t:
        raise ValueError("technical screening frame missing columns: " + ", ".join(missing_t))
    if value_screening.empty or value_screening["cedear_ticker"].duplicated().any():
        raise ValueError("value screening must contain unique canonical tickers")
    if technical_screening["cedear_ticker"].duplicated().any():
        raise ValueError("technical screening must contain unique canonical tickers")

    technical = technical_screening[["cedear_ticker", "screening_score", "screening_status", "data_quality_score"]].copy()
    merged = value_screening.merge(technical, on="cedear_ticker", how="left", validate="one_to_one", suffixes=("", "_technical"))
    if merged["screening_score"].isna().any():
        missing = sorted(merged.loc[merged["screening_score"].isna(), "cedear_ticker"])
        raise ValueError("technical screening missing tickers present in value screening: " + ", ".join(missing))

    deployment_ready = _deployment_eligible(merged)
    merged["deployment_eligibility"] = deployment_ready
    merged["technical_timing_ok"] = merged["screening_score"].ge(min_timing_gate_score)
    merged["selected"] = False
    merged["selection_track"] = pd.array([None] * len(merged), dtype="object")

    is_equity = merged["instrument_class"].eq("EQUITY")

    equity = merged[is_equity].sort_values(
        ["value_score", "value_data_quality_score", "cedear_ticker"], ascending=[False, False, True], kind="mergesort"
    )
    equity_eligible = (
        equity["value_screening_status"].eq("SCORE_READY")
        & equity["value_data_quality_score"].ge(min_value_data_quality)
        & equity["technical_timing_ok"]
        & equity["deployment_eligibility"]
    )
    merged.loc[equity.index, "value_rank"] = pd.Series(range(1, len(equity) + 1), index=equity.index, dtype="Int64")
    merged.loc[equity.index, "equity_top_n_eligibility"] = equity_eligible

    other = merged[~is_equity].sort_values(
        ["screening_score", "data_quality_score", "cedear_ticker"], ascending=[False, False, True], kind="mergesort"
    )
    other_eligible = (
        other["screening_status"].eq("SCORE_READY")
        & other["data_quality_score"].ge(min_technical_data_quality)
        & other["deployment_eligibility"]
    )
    merged.loc[other.index, "technical_rank"] = pd.Series(range(1, len(other) + 1), index=other.index, dtype="Int64")
    merged.loc[other.index, "etf_top_n_eligibility"] = other_eligible

    equity_slots = top_n - etf_slots
    equity_selected = equity.index[equity_eligible].tolist()[:equity_slots]
    other_selected = other.index[other_eligible].tolist()[:etf_slots]
    merged.loc[equity_selected, "selected"] = True
    merged.loc[equity_selected, "selection_track"] = "EQUITY_VALUE"
    merged.loc[other_selected, "selected"] = True
    merged.loc[other_selected, "selection_track"] = "ETF_TECHNICAL"

    result = merged.sort_values("cedear_ticker").reset_index(drop=True)
    metrics = {
        "methodology": "RESEARCH_VALUE_FIRST_RANKING_SHADOW",
        "top_n": top_n,
        "etf_slots": etf_slots,
        "equity_slots": equity_slots,
        "equity_candidate_count": int(is_equity.sum()),
        "equity_eligible_count": int(equity_eligible.sum()),
        "equity_selected_count": len(equity_selected),
        "equity_slots_unfilled": max(0, equity_slots - len(equity_selected)),
        "etf_candidate_count": int((~is_equity).sum()),
        "etf_eligible_count": int(other_eligible.sum()),
        "etf_selected_count": len(other_selected),
        "etf_slots_unfilled": max(0, etf_slots - len(other_selected)),
        "total_selected_count": len(equity_selected) + len(other_selected),
        "min_timing_gate_score": min_timing_gate_score,
        "min_technical_data_quality": min_technical_data_quality,
        "min_value_data_quality": min_value_data_quality,
    }
    return result, metrics
