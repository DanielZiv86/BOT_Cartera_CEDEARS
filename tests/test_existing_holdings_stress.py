import pandas as pd
import pytest
import yaml

from src.orchestration.build_investment_committee import _compute_existing_holdings_stress
from src.valuation.deep_scenario_engine import validate_scenarios

POLICY = {
 'methodology_version': 'SCENARIO-2.2',
 'identity': {'eps_pe_to_price_ratio_min': .55, 'eps_pe_to_price_ratio_max': 1.80, 'verified_adr_ratios': {}, 'verified_direct_foreign_listings': {}},
 'sector_overrides': {},
 'sector_classification': {'corporate_keywords': ['TECHNOLOGY', 'SOFTWARE', 'SEMICONDUCTOR', 'HEALTH', 'PHARMA', 'CONSUMER', 'INDUSTRIAL', 'MATERIAL', 'COMMUNICATION', 'TELECOM', 'UTILITY', 'REAL ESTATE', 'AEROSPACE', 'TRANSPORT', 'RETAIL', 'FOOD', 'BEVERAGE']},
 'corporate': {'consensus_base_blend': .20, 'consensus_bear_blend': .20, 'bear_eps_compression': .18, 'bear_multiple_factor': .78, 'base_pe_floor': 6, 'pe_cap_base': 15, 'pe_cap_growth_sensitivity': 1.5, 'pe_cap_ceiling': 55, 'bull_multiple_factor': 1.12, 'base_growth_floor': -.10, 'base_growth_cap': .20, 'bull_growth_floor': .08, 'bull_growth_increment': .08, 'bull_growth_cap': .30},
 'financials': {'roe_floor': .04, 'roe_cap': .22, 'cost_of_equity_anchor': .10, 'base_pb_anchor': 1, 'roe_pb_sensitivity': 3, 'base_pb_floor': .45, 'base_pb_cap': 4.0, 'observed_pb_weight': .65, 'fair_pb_weight': .35, 'consensus_base_blend': .2, 'bear_pb_factor': .72, 'bear_pb_floor': .35, 'bull_pb_factor': 1.2, 'bull_pb_cap': 5.0, 'minimum_bull_premium_to_base': .10, 'consensus_bear_blend': .20},
 'energy': {'base_pe_floor': 5, 'base_pe_cap': 14, 'earnings_weight': .65, 'normalized_fcf_yield': .08, 'consensus_base_blend': .15, 'bear_cycle_factor': .72, 'bull_cycle_factor': 1.28, 'dividend_credit': .5, 'minimum_bull_premium_to_base': .10, 'consensus_bear_blend': .20},
 'consensus': {'dispersion_review_threshold': .75, 'high_distance_from_median_cap': .50, 'low_distance_from_median_floor': .50},
 'plausibility': {'max_standard_bull_upside': .60, 'max_standard_bear_downside': .40},
 'probabilities': {'base_probability': .50, 'bull_min': .12, 'bull_max': .32, 'bull_floor': .08, 'bull_ceiling': .35, 'dispersion_penalty_start': .50, 'dispersion_bull_penalty_max': .07},
}


def _row(ticker, current, high, median, low, eps, pe, growth, confidence=.60, de=.8, sector='Technology', **extra):
    r = {
        'cedear_ticker': ticker, 'underlying_ticker': ticker, 'valuation_engine_type': 'EQUITY',
        'valuation_method': 'FINNHUB_ANALYST_CONSENSUS_SCREENING_V4', 'valuation_status': 'VALUATION_READY',
        'current_price': current, 'bull_target_price': high, 'base_target_price': median, 'bear_target_price': low,
        'consensus_target_high': high, 'consensus_target_median': median, 'consensus_target_low': low,
        'fundamental_eps_normalized': eps, 'fundamental_pe_normalized': pe, 'fundamental_eps_growth_3y': growth,
        'fundamental_debt_to_equity': de, 'valuation_confidence': confidence, 'eps_unit': 'UNDERLYING_SECURITY',
        'target_price_unit': 'UNDERLYING_SECURITY', 'industry_sector_official': sector,
        'issuer_country_normalized': 'US', 'underlying_market_official': 'NASDAQ GS',
    }
    r.update(extra)
    return r


def _write_policy(path):
    path.write_text(yaml.safe_dump(POLICY), encoding='utf-8')


def test_existing_holdings_stress_sums_weight_times_bear_move_for_assessed_tickers(tmp_path):
    rows = [
        _row('PBI', 17.17, 23.1, 19.63, 12, .8362, 16.2674, .12, .60, .8, sector='Technology'),
        _row('AAA', 50.0, 65.0, 52.0, 35.0, 3.0, 15.0, .10, .65, .9, sector='Technology'),
    ]
    broad = pd.DataFrame(rows)
    reviewed, _ = validate_scenarios(broad, POLICY)
    assert reviewed['scenario_validated'].all(), reviewed['scenario_review_blockers'].tolist()
    expected = {
        r['cedear_ticker']: abs(float(r['bear_target_price']) / float(r['current_price']) - 1.0)
        for _, r in reviewed.iterrows()
    }

    broad_path = tmp_path / 'broad_valuation.parquet'
    broad.to_parquet(broad_path, index=False)
    policy_path = tmp_path / 'scenario_review_policy.yml'
    _write_policy(policy_path)

    positions = pd.DataFrame([
        {'cedear_ticker': 'PBI', 'weight': 0.15},
        {'cedear_ticker': 'AAA', 'weight': 0.10},
    ])
    positions_path = tmp_path / 'portfolio_positions.parquet'
    positions.to_parquet(positions_path, index=False)

    total, metrics = _compute_existing_holdings_stress(str(positions_path), str(broad_path), str(policy_path))
    expected_total = 0.15 * expected['PBI'] + 0.10 * expected['AAA']
    assert total == pytest.approx(expected_total)
    assert metrics['existing_holdings_assessed_weight'] == pytest.approx(0.25)
    assert metrics['existing_holdings_unassessed_weight'] == pytest.approx(0.0)
    assert metrics['existing_holdings_unassessed_tickers'] == []


def test_existing_holdings_stress_excludes_unassessed_tickers_from_sum_but_reports_weight(tmp_path):
    rows = [_row('PBI', 17.17, 23.1, 19.63, 12, .8362, 16.2674, .12, .60, .8, sector='Technology')]
    broad = pd.DataFrame(rows)
    broad_path = tmp_path / 'broad_valuation.parquet'
    broad.to_parquet(broad_path, index=False)
    policy_path = tmp_path / 'scenario_review_policy.yml'
    _write_policy(policy_path)

    positions = pd.DataFrame([
        {'cedear_ticker': 'PBI', 'weight': 0.20},
        {'cedear_ticker': 'MISSING', 'weight': 0.05},
    ])
    positions_path = tmp_path / 'portfolio_positions.parquet'
    positions.to_parquet(positions_path, index=False)

    total, metrics = _compute_existing_holdings_stress(str(positions_path), str(broad_path), str(policy_path))
    assert metrics['existing_holdings_unassessed_tickers'] == ['MISSING']
    assert metrics['existing_holdings_unassessed_weight'] == pytest.approx(0.05)
    assert metrics['existing_holdings_assessed_weight'] == pytest.approx(0.20)
    # MISSING's own risk is never guessed -- it's excluded from the sum, not zeroed.
    assert total > 0.0


def test_existing_holdings_stress_ignores_zero_weight_positions(tmp_path):
    rows = [_row('PBI', 17.17, 23.1, 19.63, 12, .8362, 16.2674, .12, .60, .8, sector='Technology')]
    broad = pd.DataFrame(rows)
    broad_path = tmp_path / 'broad_valuation.parquet'
    broad.to_parquet(broad_path, index=False)
    policy_path = tmp_path / 'scenario_review_policy.yml'
    _write_policy(policy_path)

    positions = pd.DataFrame([{'cedear_ticker': 'PBI', 'weight': 0.0}])
    positions_path = tmp_path / 'portfolio_positions.parquet'
    positions.to_parquet(positions_path, index=False)

    total, metrics = _compute_existing_holdings_stress(str(positions_path), str(broad_path), str(policy_path))
    assert total == 0.0
    assert metrics['existing_holdings_assessed_weight'] == 0.0
    assert metrics['existing_holdings_unassessed_weight'] == 0.0
