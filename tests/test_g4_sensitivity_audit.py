import pandas as pd
from src.valuation.g4_sensitivity_audit import audit


def test_robust_hold_when_even_loosest_grid_has_no_pass():
    frame=pd.DataFrame([
        {'cedear_ticker':'SAFE','g4_status':'G4_FAIL_RETURN','bear_return_net':-.05,'expected_return_net':.04,'uncertainty_penalty':.06,'correlation_penalty':0.,'concentration_penalty':0.,'minimum_margin_over_hurdle':.02,'required_margin_over_cash':.02,'valuation_engine_type':'ETF'},
        {'cedear_ticker':'RISKY','g4_status':'G4_FAIL_DOWNSIDE','bear_return_net':-.65,'expected_return_net':.20,'uncertainty_penalty':0.,'correlation_penalty':0.,'concentration_penalty':0.,'minimum_margin_over_hurdle':.02,'required_margin_over_cash':.04,'valuation_engine_type':'EQUITY'},
        {'cedear_ticker':'BLOCK','g4_status':'BLOCKED_BY_DATA','bear_return_net':None,'expected_return_net':None,'uncertainty_penalty':None,'correlation_penalty':None,'concentration_penalty':None,'minimum_margin_over_hurdle':.02,'required_margin_over_cash':.02,'valuation_engine_type':'ETF'},
    ])
    grid,summary=audit(frame)
    assert len(grid)==72
    assert summary['evaluated_count']==2
    assert summary['blocked_count']==1
    assert summary['maximum_pass_count_across_grid']==0
    assert summary['hold_cash_robust_across_grid'] is True
    assert summary['threshold_relaxation_supported_by_audit'] is False


def test_frontier_is_detected_without_mutating_production_policy():
    frame=pd.DataFrame([{'cedear_ticker':'EDGE','g4_status':'G4_FAIL_DOWNSIDE','bear_return_net':-.18,'expected_return_net':.09,'uncertainty_penalty':.01,'correlation_penalty':0.,'concentration_penalty':0.,'minimum_margin_over_hurdle':.02,'required_margin_over_cash':.03,'valuation_engine_type':'EQUITY'}])
    grid,summary=audit(frame)
    assert summary['maximum_pass_count_across_grid']>0
    assert summary['hold_cash_robust_across_grid'] is False
    assert summary['threshold_relaxation_supported_by_audit'] is None
    assert ((grid['bear_limit']==-.25)&(grid['cash_hurdle']==.05)&(grid['uncertainty_scale']==0)&(~grid['dynamic_equity_margin'])&(grid['pass_count']==1)).any()
