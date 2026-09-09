from src.orchestration.build_decisional_risk import g4_ranking_is_risk_acceptable


def _manifest(**overrides):
    base = {
        "ticker_count": 30,
        "evaluated_count": 30,
        "blocked_count": 0,
        "ranking_status": "COMPLETE_ACTIONABLE",
    }
    base.update(overrides)
    return base


def test_complete_actionable_is_accepted():
    assert g4_ranking_is_risk_acceptable(_manifest())


def test_complete_with_review_flags_is_accepted_when_30_of_30_and_zero_blocked():
    assert g4_ranking_is_risk_acceptable(
        _manifest(ranking_status="COMPLETE_WITH_REVIEW_FLAGS")
    )


def test_explicit_data_gap_is_accounted_but_not_silently_actionable():
    # One candidate can be fail-closed for missing material scenario evidence
    # without turning a complete 30-name accounting into broken lineage.
    assert g4_ranking_is_risk_acceptable(
        _manifest(
            ranking_status="COMPLETE_WITH_DATA_GAPS",
            evaluated_count=29,
            blocked_count=1,
        )
    )


def test_review_required_ranking_is_accounted_for_risk():
    # Review-required is a governance hold, not an incomplete lineage condition.
    assert g4_ranking_is_risk_acceptable(
        _manifest(ranking_status="COMPLETE_REVIEW_REQUIRED")
    )


def test_unaccounted_candidate_remains_fail_closed():
    assert not g4_ranking_is_risk_acceptable(
        _manifest(
            ranking_status="COMPLETE_WITH_DATA_GAPS",
            evaluated_count=28,
            blocked_count=1,
        )
    )


def test_partial_ranking_remains_fail_closed():
    assert not g4_ranking_is_risk_acceptable(
        _manifest(ranking_status="PARTIAL_NOT_ACTIONABLE")
    )
