"""
EBITDA Context Builder for Sentient CX Risk Scenario

Builds a deterministic EBITDA waterfall view from risk exposure data.
Does NOT call LLMs - uses straightforward calculations based on risk context.
"""

from typing import Dict, Any


def build_ebitda_context(risk_context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a simple, deterministic EBITDA view for the Sentient CX risk scenario.
    This does NOT call any LLMs.

    Uses risk exposure data to estimate:
      - baseline_ebitda: Starting EBITDA before CX risk impacts
      - revenue_leakage: Lost revenue from poor CX (churn, reduced sales)
      - compliance_penalties: Regulatory fines and legal costs
      - opex_inefficiency: Increased operational costs from manual interventions
      - automation_gains: Savings from AI-driven automation (positive impact)
      - final_ebitda: Net EBITDA after all impacts

    Args:
        risk_context: Dict containing risk data from build_risk_context()
        config: Application configuration dict

    Returns:
        Dict with EBITDA waterfall components (all values in millions)
    """

    # Default EBITDA context for non-Day2 scenarios
    ebitda_ctx = {
        "baseline_ebitda": 0.0,
        "revenue_leakage": 0.0,
        "compliance_penalties": 0.0,
        "opex_inefficiency": 0.0,
        "automation_gains": 0.0,
        "final_ebitda": 0.0,
        "total_impact": 0.0,
        "impact_pct": 0.0,
    }

    # Only process for Day 2 scenarios with risk data
    if not risk_context or "risks" not in risk_context:
        return ebitda_ctx

    risks = risk_context.get("risks", [])
    if not risks:
        return ebitda_ctx

    # === BASELINE EBITDA ===
    # Assumption: For a Platinum banking client (Aurora National Bank),
    # we estimate baseline annual EBITDA at ~$50M
    # (This could be pulled from config in production)
    scenario_config = config.get("scenarios", {}).get("sentient_cx_risk_radar", {})
    baseline_ebitda = scenario_config.get("ebitda", {}).get("baseline_millions", 50.0)

    # === CALCULATE IMPACTS FROM RISK EXPOSURE ===

    # 1. Revenue Leakage
    # Assumption: CX sentiment decline drives customer churn
    # For every 10% drop in sentiment, estimate 2% revenue impact
    # Use CX sentiment data if available
    cx_sentiment_data = risk_context.get("cx_sentiment_trend", [])
    sentiment_impact_pct = 0.0

    if cx_sentiment_data:
        # Get baseline and current sentiment from first and last records
        baseline_sentiment = cx_sentiment_data[0].get("avg_sentiment_score", 82) if cx_sentiment_data else 82
        current_sentiment = cx_sentiment_data[-1].get("avg_sentiment_score", 61) if cx_sentiment_data else 61

        try:
            baseline_sentiment = float(baseline_sentiment)
            current_sentiment = float(current_sentiment)
            sentiment_drop_pct = ((baseline_sentiment - current_sentiment) / baseline_sentiment) * 100
            # 2% revenue impact per 10% sentiment drop
            sentiment_impact_pct = (sentiment_drop_pct / 10.0) * 2.0
        except (ValueError, TypeError, ZeroDivisionError):
            sentiment_impact_pct = 0.0

    # Revenue leakage = baseline EBITDA * sentiment impact %
    revenue_leakage = baseline_ebitda * (sentiment_impact_pct / 100.0)

    # 2. Compliance Penalties
    # Assumption: Extract compliance-related risks and use their exposure
    # Multiply by risk factor (e.g., 0.3 = 30% likelihood of full penalty)
    compliance_risk_ids = ["R1"]  # GDPR/CCPA non-compliance
    compliance_penalties = 0.0

    for risk in risks:
        risk_id = risk.get("id", "")
        if risk_id in compliance_risk_ids:
            exposure_millions = risk.get("exposure_millions", 0.0)
            # Assume 30% likelihood of incurring the penalty
            penalty_risk_factor = 0.3
            try:
                compliance_penalties += float(exposure_millions) * penalty_risk_factor
            except (ValueError, TypeError):
                pass

    # 3. OpEx Inefficiency
    # Assumption: Manual interventions due to bot failures increase operational costs
    # Estimate based on operational risk exposures (latency, misrouting, escalation gaps)
    operational_risk_ids = ["R2", "R3", "R4"]  # Latency, misrouting, escalation gaps
    opex_inefficiency = 0.0

    for risk in risks:
        risk_id = risk.get("id", "")
        if risk_id in operational_risk_ids:
            exposure_millions = risk.get("exposure_millions", 0.0)
            # Assume 20% of exposure translates to increased OpEx
            opex_factor = 0.2
            try:
                opex_inefficiency += float(exposure_millions) * opex_factor
            except (ValueError, TypeError):
                pass

    # 4. Automation Gains (POSITIVE impact)
    # Assumption: Despite risks, AI automation still provides cost savings
    # Estimate ~15% of baseline EBITDA as gross automation benefit
    # Reduce this by impact of operational risks
    gross_automation_benefit = baseline_ebitda * 0.15

    # Reduce automation gains proportionally to operational risk exposure
    total_operational_exposure = sum(
        float(risk.get("exposure_millions", 0.0))
        for risk in risks
        if risk.get("id", "") in operational_risk_ids
    )

    # If operational risks are high, automation gains are reduced
    # Cap reduction at 50% of gross benefit
    automation_reduction_factor = min(0.5, total_operational_exposure / (baseline_ebitda * 0.5))
    automation_gains = gross_automation_benefit * (1.0 - automation_reduction_factor)

    # === FINAL EBITDA CALCULATION ===
    total_negative_impact = revenue_leakage + compliance_penalties + opex_inefficiency
    total_impact = automation_gains - total_negative_impact  # Net impact (can be negative)
    final_ebitda = baseline_ebitda + total_impact

    # Impact as percentage of baseline
    impact_pct = (total_impact / baseline_ebitda * 100.0) if baseline_ebitda > 0 else 0.0

    # === BUILD RETURN CONTEXT ===
    ebitda_ctx = {
        # Core waterfall components (all in millions)
        "baseline_ebitda": round(baseline_ebitda, 2),
        "revenue_leakage": round(revenue_leakage, 2),
        "compliance_penalties": round(compliance_penalties, 2),
        "opex_inefficiency": round(opex_inefficiency, 2),
        "automation_gains": round(automation_gains, 2),
        "final_ebitda": round(final_ebitda, 2),

        # Summary metrics
        "total_impact": round(total_impact, 2),
        "impact_pct": round(impact_pct, 1),
        "total_negative_impact": round(total_negative_impact, 2),

        # Additional context for visualization
        "sentiment_drop_pct": round(sentiment_impact_pct, 1) if sentiment_impact_pct else 0.0,
        "automation_reduction_factor": round(automation_reduction_factor * 100, 1),

        # Waterfall data array for charts
        # Format: [label, value, is_positive]
        "waterfall_components": [
            {"label": "Baseline EBITDA", "value": round(baseline_ebitda, 2), "type": "base"},
            {"label": "Revenue Leakage", "value": -round(revenue_leakage, 2), "type": "negative"},
            {"label": "Compliance Penalties", "value": -round(compliance_penalties, 2), "type": "negative"},
            {"label": "OpEx Inefficiency", "value": -round(opex_inefficiency, 2), "type": "negative"},
            {"label": "Automation Gains", "value": round(automation_gains, 2), "type": "positive"},
            {"label": "Final EBITDA", "value": round(final_ebitda, 2), "type": "final"},
        ]
    }

    return ebitda_ctx
