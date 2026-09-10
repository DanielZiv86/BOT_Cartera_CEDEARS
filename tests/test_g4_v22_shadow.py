import pandas as pd
from src.valuation.g4_v22_shadow import build_g4_v22_shadow

POLICY={"risk":{"position_stress_budget_nav":.02,"candidate_test_weight_nav":.05,"max_single_name_weight":.20},"shadow_audit_contract":{"position_stress_budget_sensitivity_nav":[.01,.02,.025]}}

def row(**x):
    r={"cedear_ticker":"TEST","g4_status":"G4_FAIL_DOWNSIDE","g4_reason":"STRESS_DOWNSIDE_EXCEEDS_POLICY","stress_return_net":-.30,"net_benefit_vs_cash":.03,"minimum_margin_over_hurdle":.02};r.update(x);return r

def test_shadow_can_pass_when_return_passes_and_position_stress_budget_passes():
    out,m=build_g4_v22_shadow(pd.DataFrame([row()]),POLICY);r=out.iloc[0]
    assert r.g4_v21_status=="G4_FAIL_DOWNSIDE";assert r.g4_v22_shadow_status=="SHADOW_PASS";assert abs(r.position_stress_contribution_nav-.015)<1e-12;assert m["production_decision_authority"] is False

def test_shadow_does_not_turn_return_failure_into_pass():
    out,_=build_g4_v22_shadow(pd.DataFrame([row(net_benefit_vs_cash=.01)]),POLICY);assert out.iloc[0].g4_v22_shadow_status=="SHADOW_FAIL_RETURN"

def test_stress_budget_controls_position_size_not_expected_return():
    out,_=build_g4_v22_shadow(pd.DataFrame([row(stress_return_net=-.50)]),POLICY);r=out.iloc[0]
    assert r.g4_v22_shadow_status=="SHADOW_FAIL_STRESS_BUDGET";assert abs(r.stress_compatible_max_weight-.04)<1e-12

def test_data_block_remains_fail_closed():
    out,_=build_g4_v22_shadow(pd.DataFrame([row(g4_status="BLOCKED_BY_DATA",g4_reason="VALUATION_NOT_READY",stress_return_net=None)]),POLICY);assert out.iloc[0].g4_v22_shadow_status=="SHADOW_BLOCKED_BY_DATA"
