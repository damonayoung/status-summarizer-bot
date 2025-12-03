#!/usr/bin/env python3
"""
Stage 1: Fortune-500-Grade Cyber Context Builder
Pure data transformation pipeline - no LLM calls, just pandas + Python.
"""

import pandas as pd
from typing import Dict, Any, List
from datetime import datetime, timedelta


def build_cyber_context(config: Dict[str, Any], scenario: str) -> Dict[str, Any]:
    """
    Build structured cyber context from CSV data sources.

    This is a pure data transformation function:
    - Loads CSVs into pandas DataFrames
    - Computes KPIs and aggregates
    - Returns structured dict ready for LLM processing
    - NO LLM calls - just pandas + standard Python

    Args:
        config: Application configuration with scenario data sources
        scenario: Scenario name (e.g., 'sentient_cyber_pmo')

    Returns:
        Dict containing:
        - Raw DataFrames (risks, incidents, vulnerabilities, controls, compliance, tasks)
        - Computed KPIs (incidents, MTTR, vulnerabilities, controls, exposure)
        - Domain scores (CISSP-aligned 1-5 ratings)
        - Compliance gaps (highest-risk failures)
        - Security debt metrics
        - Program health metrics
        - Financial aggregates
    """
    print(f"\n🔬 [Stage 1] Building Fortune-500-grade cyber context for: {scenario}")

    # Get scenario configuration
    scenario_config = config.get("scenarios", {}).get(scenario, {})
    if not scenario_config:
        raise ValueError(f"Scenario '{scenario}' not found in config")

    data_sources = scenario_config.get("data_sources", {})

    # Initialize context structure
    context = {
        "scenario": scenario,
        "scenario_title": scenario_config.get("title", scenario),
        # Raw DataFrames
        "risks": pd.DataFrame(),
        "incidents": pd.DataFrame(),
        "vulnerabilities": pd.DataFrame(),
        "controls": pd.DataFrame(),
        "compliance": pd.DataFrame(),
        "tasks": pd.DataFrame(),
        # Computed aggregates (will be populated below)
        "kpis": {},
        "domain_scores": {},
        "compliance_gaps": [],
        "security_debt": {},
        "program_health": {},
        "financials": {}
    }

    # === Load CSV Data ===
    print("\n  📋 Loading CSV data sources...")

    # 1. Risk Financials
    risk_path = data_sources.get("security_risk_register", {}).get("path")
    if risk_path:
        try:
            context["risks"] = pd.read_csv(risk_path)
            print(f"    ✓ Loaded risks: {len(context['risks'])} records")
        except Exception as e:
            print(f"    ✗ Error loading risks: {e}")

    # 2. Security Incidents
    incidents_path = data_sources.get("security_incidents", {}).get("path")
    if incidents_path:
        try:
            context["incidents"] = pd.read_csv(incidents_path)
            # Convert date columns if they exist
            for col in ["DetectedDate", "ResolvedDate"]:
                if col in context["incidents"].columns:
                    context["incidents"][col] = pd.to_datetime(context["incidents"][col], errors='coerce')
            print(f"    ✓ Loaded incidents: {len(context['incidents'])} records")
        except Exception as e:
            print(f"    ✗ Error loading incidents: {e}")

    # 3. Vulnerability Findings
    vuln_path = data_sources.get("vulnerability_findings", {}).get("path")
    if vuln_path:
        try:
            context["vulnerabilities"] = pd.read_csv(vuln_path)
            print(f"    ✓ Loaded vulnerabilities: {len(context['vulnerabilities'])} records")
        except Exception as e:
            print(f"    ✗ Error loading vulnerabilities: {e}")

    # 4. Security Controls
    controls_path = data_sources.get("security_controls", {}).get("path")
    if controls_path:
        try:
            context["controls"] = pd.read_csv(controls_path)
            print(f"    ✓ Loaded controls: {len(context['controls'])} records")
        except Exception as e:
            print(f"    ✗ Error loading controls: {e}")

    # 5. Compliance Status
    compliance_path = data_sources.get("compliance_status", {}).get("path")
    if compliance_path:
        try:
            context["compliance"] = pd.read_csv(compliance_path)
            print(f"    ✓ Loaded compliance: {len(context['compliance'])} records")
        except Exception as e:
            print(f"    ✗ Error loading compliance: {e}")

    # 6. Security Program Tasks
    tasks_path = data_sources.get("security_program_tasks", {}).get("path")
    if tasks_path:
        try:
            context["tasks"] = pd.read_csv(tasks_path)
            print(f"    ✓ Loaded tasks: {len(context['tasks'])} records")
        except Exception as e:
            print(f"    ✗ Error loading tasks: {e}")

    # === Compute KPIs ===
    print("\n  📊 Computing KPIs...")
    context["kpis"] = _compute_kpis(context)

    # === Compute Domain Scores ===
    print("  🎯 Computing CISSP domain scores...")
    context["domain_scores"] = _compute_domain_scores(context)

    # === Identify Compliance Gaps ===
    print("  ⚠️  Identifying compliance gaps...")
    context["compliance_gaps"] = _compute_compliance_gaps(context)

    # === Compute Security Debt ===
    print("  💳 Computing security debt metrics...")
    context["security_debt"] = _compute_security_debt(context)

    # === Compute Program Health ===
    print("  🏥 Computing program health metrics...")
    context["program_health"] = _compute_program_health(context)

    # === Compute Financial Aggregates ===
    print("  💰 Computing financial aggregates...")
    context["financials"] = _compute_financials(context)

    print("\n✅ [Stage 1] Cyber context built successfully!")
    print(f"   • KPIs: {len(context['kpis'])} metrics")
    print(f"   • Domain scores: {len(context['domain_scores'])} domains")
    print(f"   • Compliance gaps: {len(context['compliance_gaps'])} high-risk items")
    print(f"   • Security debt: {context['security_debt'].get('total_open_vulns', 0)} open vulns")
    print(f"   • Program health: {context['program_health'].get('total_tasks', 0)} total tasks")

    return context


def _compute_kpis(context: Dict[str, Any]) -> Dict[str, Any]:
    """Compute aggregate KPIs from loaded data."""
    kpis = {}

    incidents_df = context.get("incidents", pd.DataFrame())
    vulnerabilities_df = context.get("vulnerabilities", pd.DataFrame())
    controls_df = context.get("controls", pd.DataFrame())
    risks_df = context.get("risks", pd.DataFrame())

    # Incident KPIs
    if not incidents_df.empty:
        # Total incidents (last 30 days if dates available)
        if "DetectedDate" in incidents_df.columns:
            recent_incidents = incidents_df[
                incidents_df["DetectedDate"] >= (datetime.now() - timedelta(days=30))
            ]
            kpis["total_incidents"] = len(recent_incidents)
        else:
            kpis["total_incidents"] = len(incidents_df)

        # Critical incidents
        if "Severity" in incidents_df.columns:
            kpis["critical_incidents_count"] = len(
                incidents_df[incidents_df["Severity"].isin(["Critical", "High"])]
            )

        # MTTD and MTTR
        if "MTTD_Hours" in incidents_df.columns:
            kpis["avg_mttd_hours"] = incidents_df["MTTD_Hours"].mean()
        if "MTTR_Hours" in incidents_df.columns:
            kpis["avg_mttr_hours"] = incidents_df["MTTR_Hours"].mean()

    # Vulnerability KPIs
    if not vulnerabilities_df.empty:
        # Open critical vulnerabilities
        if "Severity" in vulnerabilities_df.columns and "Status" in vulnerabilities_df.columns:
            kpis["open_critical_vulns"] = len(
                vulnerabilities_df[
                    (vulnerabilities_df["Severity"] == "Critical") &
                    (vulnerabilities_df["Status"] == "Open")
                ]
            )

        # Overdue vulnerabilities (Age_Days > SLA_Days)
        if "Age_Days" in vulnerabilities_df.columns and "SLA_Days" in vulnerabilities_df.columns:
            kpis["overdue_vulns_count"] = len(
                vulnerabilities_df[vulnerabilities_df["Age_Days"] > vulnerabilities_df["SLA_Days"]]
            )

    # Control KPIs
    if not controls_df.empty:
        if "Status" in controls_df.columns:
            kpis["failing_controls_count"] = len(
                controls_df[controls_df["Status"] == "Fail"]
            )
            kpis["at_risk_controls_count"] = len(
                controls_df[controls_df["Status"] == "At Risk"]
            )

    # Risk Exposure KPIs
    if not risks_df.empty:
        # High-risk exposure (Likelihood in High/Medium-High)
        if "ExposureAmount" in risks_df.columns and "Likelihood" in risks_df.columns:
            high_risk = risks_df[risks_df["Likelihood"].isin(["High", "Medium-High"])]
            kpis["high_risk_exposure_total"] = high_risk["ExposureAmount"].sum()

        # Total EBITDA impact
        if "EBITDA_Impact" in risks_df.columns:
            kpis["total_ebitda_impact"] = risks_df["EBITDA_Impact"].sum()

    return kpis


def _compute_domain_scores(context: Dict[str, Any]) -> Dict[str, float]:
    """
    Compute CISSP-aligned domain scores (1-5 scale) based on control health.

    Scoring logic:
    - Base score: 3
    - +1 if majority of controls in domain are Healthy
    - -1 if majority are At Risk
    - -2 if any control is Failing in that domain
    - Clamp to [1, 5] range
    """
    controls_df = context.get("controls", pd.DataFrame())

    if controls_df.empty or "Domain" not in controls_df.columns or "Status" not in controls_df.columns:
        return {}

    domain_scores = {}

    for domain in controls_df["Domain"].unique():
        domain_controls = controls_df[controls_df["Domain"] == domain]

        # Start with base score
        score = 3.0

        # Count statuses
        healthy_count = len(domain_controls[domain_controls["Status"] == "Healthy"])
        at_risk_count = len(domain_controls[domain_controls["Status"] == "At Risk"])
        failing_count = len(domain_controls[domain_controls["Status"] == "Fail"])
        total = len(domain_controls)

        # Adjust score
        if healthy_count > (total / 2):
            score += 1
        if at_risk_count > (total / 2):
            score -= 1
        if failing_count > 0:
            score -= 2

        # Clamp to [1, 5]
        score = max(1.0, min(5.0, score))

        domain_scores[domain] = score

    return domain_scores


def _compute_compliance_gaps(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Identify highest-risk compliance gaps."""
    compliance_df = context.get("compliance", pd.DataFrame())

    if compliance_df.empty:
        return []

    # Filter for Fail or At Risk status
    if "Status" in compliance_df.columns:
        gaps = compliance_df[compliance_df["Status"].isin(["Fail", "At Risk"])]
    else:
        gaps = compliance_df

    # Sort by risk rating if available
    if "RiskRating" in gaps.columns:
        gaps = gaps.sort_values("RiskRating", ascending=False)

    # Return top 10 as list of dicts
    return gaps.head(10).to_dict('records')


def _compute_security_debt(context: Dict[str, Any]) -> Dict[str, Any]:
    """Compute security debt metrics from vulnerabilities."""
    vulnerabilities_df = context.get("vulnerabilities", pd.DataFrame())

    debt = {
        "total_open_vulns": 0,
        "critical_vulns_open": 0,
        "avg_vuln_age_days": 0.0,
        "count_overdue_vulns": 0,
        "oldest_vuln_age_days": 0
    }

    if vulnerabilities_df.empty:
        return debt

    # Total open vulnerabilities
    if "Status" in vulnerabilities_df.columns:
        open_vulns = vulnerabilities_df[vulnerabilities_df["Status"] == "Open"]
        debt["total_open_vulns"] = len(open_vulns)

        # Critical vulns open
        if "Severity" in open_vulns.columns:
            debt["critical_vulns_open"] = len(
                open_vulns[open_vulns["Severity"] == "Critical"]
            )

        # Age metrics
        if "Age_Days" in open_vulns.columns:
            debt["avg_vuln_age_days"] = open_vulns["Age_Days"].mean()
            debt["oldest_vuln_age_days"] = open_vulns["Age_Days"].max()

            # Overdue count
            if "SLA_Days" in open_vulns.columns:
                debt["count_overdue_vulns"] = len(
                    open_vulns[open_vulns["Age_Days"] > open_vulns["SLA_Days"]]
                )

    return debt


def _compute_program_health(context: Dict[str, Any]) -> Dict[str, Any]:
    """Compute program health metrics from tasks."""
    tasks_df = context.get("tasks", pd.DataFrame())

    health = {
        "total_tasks": 0,
        "percent_in_progress": 0.0,
        "percent_not_started": 0.0,
        "tasks_blocked_count": 0,
        "high_risk_tasks_open": 0
    }

    if tasks_df.empty:
        return health

    health["total_tasks"] = len(tasks_df)

    # Status distribution
    if "Status" in tasks_df.columns:
        in_progress = len(tasks_df[tasks_df["Status"] == "In Progress"])
        not_started = len(tasks_df[tasks_df["Status"] == "Not Started"])

        health["percent_in_progress"] = (in_progress / len(tasks_df)) * 100
        health["percent_not_started"] = (not_started / len(tasks_df)) * 100

    # Blocked tasks
    if "BlockerFlag" in tasks_df.columns:
        health["tasks_blocked_count"] = len(tasks_df[tasks_df["BlockerFlag"] == True])

    # High-risk tasks (linked to High/Medium-High risks)
    if "RelatedRiskID" in tasks_df.columns:
        risks_df = context.get("risks", pd.DataFrame())
        if not risks_df.empty and "Likelihood" in risks_df.columns:
            high_risk_ids = risks_df[
                risks_df["Likelihood"].isin(["High", "Medium-High"])
            ]["RiskID"].tolist()

            health["high_risk_tasks_open"] = len(
                tasks_df[tasks_df["RelatedRiskID"].isin(high_risk_ids)]
            )

    return health


def _compute_financials(context: Dict[str, Any]) -> Dict[str, Any]:
    """Compute financial aggregates from risk data."""
    risks_df = context.get("risks", pd.DataFrame())

    financials = {
        "total_exposure": 0.0,
        "total_ebitda_impact": 0.0,
        "exposure_by_domain": {},
        "ebitda_by_driver": {}
    }

    if risks_df.empty:
        return financials

    # Total exposure
    if "ExposureAmount" in risks_df.columns:
        financials["total_exposure"] = risks_df["ExposureAmount"].sum()

    # Total EBITDA impact
    if "EBITDA_Impact" in risks_df.columns:
        financials["total_ebitda_impact"] = risks_df["EBITDA_Impact"].sum()

    # Exposure by domain
    if "Domain" in risks_df.columns and "ExposureAmount" in risks_df.columns:
        financials["exposure_by_domain"] = risks_df.groupby("Domain")["ExposureAmount"].sum().to_dict()

    # EBITDA by driver category (inferred from Description keywords)
    if "EBITDA_Impact" in risks_df.columns and "Description" in risks_df.columns:
        # Simple keyword-based categorization
        risks_df["Driver"] = risks_df["Description"].apply(_categorize_ebitda_driver)
        financials["ebitda_by_driver"] = risks_df.groupby("Driver")["EBITDA_Impact"].sum().to_dict()

    return financials


def _categorize_ebitda_driver(description: str) -> str:
    """Categorize EBITDA impact by driver type based on description keywords."""
    if pd.isna(description):
        return "other"

    desc_lower = description.lower()

    if any(word in desc_lower for word in ["revenue", "sales", "customer"]):
        return "revenue"
    elif any(word in desc_lower for word in ["opex", "operational", "cost", "expense"]):
        return "opex"
    elif any(word in desc_lower for word in ["penalty", "fine", "regulatory", "compliance"]):
        return "penalties"
    elif any(word in desc_lower for word in ["downtime", "outage", "availability"]):
        return "downtime"
    else:
        return "other"
