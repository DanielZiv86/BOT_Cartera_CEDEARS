import pandas as pd
from src.valuation.g4_v22_portfolio_stress import build_portfolio_stress_shadow

P={"risk":{"position_stress_budget_nav":.02,"portfolio_stress_budget_nav":.10,"portfolio_target_invested_weight":.10,"portfolio_max_positions":2,"portfolio_min_position_weight":.02,"portfolio_max_candidate_weight":.05,"max_single_name_weight":.20,"correlation_floor":0},"shadow_audit_contract":{"portfolio_stress_budget_sensitivity_nav":[.02,.10]}}

def frame():
 return pd.DataFrame([{"cedear_ticker":"A","g4_v22_shadow_status":"SHADOW_FAIL_RETURN","stress_return_net":-.30,"risk_adjusted_er":.08},{"cedear_ticker":"B","g4_v22_shadow_status":"SHADOW_FAIL_RETURN","stress_return_net":-.40,"risk_adjusted_er":.07}])
def corr(v=.5):
 return pd.DataFrame([{"ticker_a":"A","ticker_b":"A","correlation":1},{"ticker_a":"B","ticker_b":"B","correlation":1},{"ticker_a":"A","ticker_b":"B","correlation":v},{"ticker_a":"B","ticker_b":"A","correlation":v}])

def test_gross_stress_is_sum_and_binding_budget():
 out,m=build_portfolio_stress_shadow(frame(),corr(),P); assert abs(m["actual_invested_weight"]-.10)<1e-12; assert abs(m["portfolio_gross_stress_nav"]-.035)<1e-12; assert m["portfolio_gross_stress_budget_ok"] is True

def test_correlation_is_diagnostic_and_does_not_reduce_gross_gate():
 _,low=build_portfolio_stress_shadow(frame(),corr(0),P); _,high=build_portfolio_stress_shadow(frame(),corr(.9),P); assert high["correlation_aware_stress_nav"]>low["correlation_aware_stress_nav"]; assert high["portfolio_gross_stress_nav"]==low["portfolio_gross_stress_nav"]

def test_position_budget_caps_weight():
 f=frame(); f.loc[0,"stress_return_net"]=-.80; out,_=build_portfolio_stress_shadow(f,corr(),P); a=out[out.cedear_ticker=="A"].iloc[0]; assert a.shadow_portfolio_weight<=.025+1e-12

def test_missing_pairwise_correlation_fails_closed():
 try: build_portfolio_stress_shadow(frame(),corr().query("not (ticker_a=='A' and ticker_b=='B') and not (ticker_a=='B' and ticker_b=='A')"),P)
 except ValueError as e: assert "missing correlation" in str(e)
 else: raise AssertionError("must fail closed")
