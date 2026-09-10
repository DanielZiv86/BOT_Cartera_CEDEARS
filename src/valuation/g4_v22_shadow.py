from __future__ import annotations

import numpy as np
import pandas as pd


def build_g4_v22_shadow(g4_v21: pd.DataFrame, policy: dict) -> tuple[pd.DataFrame, dict]:
    """Compare G4-2.2 stress sizing against certified G4-2.1 results.

    This module never changes expected return, hurdle, penalties or production
    decisions. It only replaces the legacy individual Stress veto in a shadow
    classification and calculates stress-compatible position sizing.
    """
    df = g4_v21.copy()
    risk = policy.get("risk", {})
    budget = float(risk.get("position_stress_budget_nav", 0.02))
    test_weight = float(risk.get("candidate_test_weight_nav", 0.05))
    max_weight = float(risk.get("max_single_name_weight", 0.20))

    stress = pd.to_numeric(df.get("stress_return_net"), errors="coerce")
    df["g4_v22_methodology_version"] = "G4-2.2-SHADOW"
    df["g4_v22_shadow_only"] = True
    df["position_stress_budget_nav"] = budget
    df["position_stress_contribution_nav"] = test_weight * stress.abs()
    df["stress_compatible_max_weight"] = np.where(
        stress.abs() > 0,
        np.minimum(budget / stress.abs(), max_weight),
        max_weight,
    )
    df["stress_budget_ok_at_test_weight"] = df["position_stress_contribution_nav"] <= budget + 1e-12

    # Preserve the certified G4-2.1 result verbatim for auditability.
    df["g4_v21_status"] = df["g4_status"]
    df["g4_v21_reason"] = df["g4_reason"]

    def classify(row):
        status = str(row.get("g4_v21_status"))
        reason = str(row.get("g4_v21_reason"))
        if status == "BLOCKED_BY_DATA":
            return "SHADOW_BLOCKED_BY_DATA", reason
        if status == "G4_FAIL_CONCENTRATION":
            return "SHADOW_FAIL_CONCENTRATION", reason
        # G4-2.2 changes only the preservation rule. All return economics remain
        # certified G4-2.1 values.
        return_ok = float(row.get("net_benefit_vs_cash")) >= float(row.get("minimum_margin_over_hurdle"))
        stress_ok = bool(row.get("stress_budget_ok_at_test_weight"))
        if not stress_ok:
            return "SHADOW_FAIL_STRESS_BUDGET", "POSITION_STRESS_CONTRIBUTION_EXCEEDS_BUDGET"
        if not return_ok:
            return "SHADOW_FAIL_RETURN", "INSUFFICIENT_RISK_ADJUSTED_MARGIN_VS_CASH"
        return "SHADOW_PASS", "RETURN_AND_POSITION_STRESS_BUDGET_PASS"

    classified = df.apply(classify, axis=1, result_type="expand")
    df["g4_v22_shadow_status"] = classified[0]
    df["g4_v22_shadow_reason"] = classified[1]
    df["classification_changed_vs_v21"] = df["g4_v22_shadow_status"].map({
        "SHADOW_PASS": "PASS",
        "SHADOW_FAIL_RETURN": "FAIL_RETURN",
        "SHADOW_FAIL_STRESS_BUDGET": "FAIL_DOWNSIDE",
        "SHADOW_FAIL_CONCENTRATION": "FAIL_CONCENTRATION",
        "SHADOW_BLOCKED_BY_DATA": "BLOCKED_BY_DATA",
    }) != df["g4_v21_status"].replace({
        "G4_PASS": "PASS", "G4_FAIL_RETURN": "FAIL_RETURN",
        "G4_FAIL_DOWNSIDE": "FAIL_DOWNSIDE", "G4_FAIL_CONCENTRATION": "FAIL_CONCENTRATION"
    })

    sensitivity = {}
    for b in policy.get("shadow_audit_contract", {}).get("position_stress_budget_sensitivity_nav", []):
        b = float(b)
        sensitivity[f"{b:.4f}"] = int(((test_weight * stress.abs()) <= b + 1e-12).fillna(False).sum())

    metrics = {
        "methodology_version": "G4-2.2-SHADOW",
        "shadow_only": True,
        "production_decision_authority": False,
        "compare_against": "G4-2.1",
        "scenario_methodology_version": "SCENARIO-2.3",
        "ticker_count": int(len(df)),
        "shadow_pass_count": int((df["g4_v22_shadow_status"] == "SHADOW_PASS").sum()),
        "shadow_fail_return_count": int((df["g4_v22_shadow_status"] == "SHADOW_FAIL_RETURN").sum()),
        "shadow_fail_stress_budget_count": int((df["g4_v22_shadow_status"] == "SHADOW_FAIL_STRESS_BUDGET").sum()),
        "shadow_blocked_count": int((df["g4_v22_shadow_status"] == "SHADOW_BLOCKED_BY_DATA").sum()),
        "classification_changed_count": int(df["classification_changed_vs_v21"].sum()),
        "position_stress_budget_nav": budget,
        "candidate_test_weight_nav": test_weight,
        "stress_budget_sensitivity_survivors": sensitivity,
        "production_chain_unchanged": True,
    }
    return df, metrics
