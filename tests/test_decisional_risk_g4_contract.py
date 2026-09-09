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


def test_review_flags_do_not_override_incomplete_contract():
    assert not g4_ranking_is_risk_acceptable(
        _manifest(
            ranking_status="COMPLETE_WITH_REVIEW_FLAGS",
            evaluated_count=29,
            blocked_count=1,
        )
    )


def test_review_required_ranking_is_not_accepted_as_actionable():
    assert not g4_ranking_is_risk_acceptable(
        _manifest(ranking_status="COMPLETE_REVIEW_REQUIRED")
    )


def test_partial_ranking_remains_fail_closed():
    assert not g4_ranking_is_risk_acceptable(
        _manifest(ranking_status="PARTIAL_NOT_ACTIONABLE")
    )
