#!/usr/bin/env python3
"""
Demonstration: Stage 2 Prioritization/Compression Layer

This script demonstrates how Stage 2 compresses rich cyber_context into LLM-ready summary.
"""

import json
import yaml
import pandas as pd
from pathlib import Path
from src.cyber_context_builder import build_cyber_context
from src.main_v2 import prioritize_cyber_context

def load_config(config_path: str = "config.yaml"):
    """Load configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main():
    print("=" * 80)
    print("STAGE 2 PRIORITIZATION/COMPRESSION LAYER DEMONSTRATION")
    print("=" * 80)

    # Load configuration
    config = load_config()
    scenario = "sentient_cyber_pmo"

    print(f"\n📋 Scenario: {scenario}")

    # === STAGE 1: Build Cyber Context ===
    print("\n" + "=" * 80)
    print("STAGE 1: Building Full Cyber Context")
    print("=" * 80)

    cyber_context = build_cyber_context(config, scenario)

    # Show Stage 1 output size
    print("\n📊 Stage 1 Output Size:")
    risks_count = len(cyber_context.get("risks", pd.DataFrame()))
    incidents_count = len(cyber_context.get("incidents", pd.DataFrame()))
    vulns_count = len(cyber_context.get("vulnerabilities", pd.DataFrame()))
    controls_count = len(cyber_context.get("controls", pd.DataFrame()))
    compliance_count = len(cyber_context.get("compliance", pd.DataFrame()))
    tasks_count = len(cyber_context.get("tasks", pd.DataFrame()))
    kpis_count = len(cyber_context.get("kpis", {}))
    domains_count = len(cyber_context.get("domain_scores", {}))

    total_rows = risks_count + incidents_count + vulns_count + controls_count + compliance_count + tasks_count

    print(f"   • Risks: {risks_count} rows")
    print(f"   • Incidents: {incidents_count} rows")
    print(f"   • Vulnerabilities: {vulns_count} rows")
    print(f"   • Controls: {controls_count} rows")
    print(f"   • Compliance: {compliance_count} rows")
    print(f"   • Tasks: {tasks_count} rows")
    print(f"   • KPIs: {kpis_count} metrics")
    print(f"   • Domain Scores: {domains_count} domains")
    print(f"\n   📈 TOTAL: {total_rows} rows + {kpis_count + domains_count} aggregates")

    # === STAGE 2: Prioritize Cyber Context ===
    print("\n" + "=" * 80)
    print("STAGE 2: Prioritizing for LLM Processing")
    print("=" * 80)

    prioritized = prioritize_cyber_context(cyber_context)

    # Show Stage 2 output size
    print("\n📊 Stage 2 Output Size:")
    top_risks_count = len(prioritized.get("top_risks", []))
    weakest_domains_count = len(prioritized.get("weakest_domains", []))
    exec_kpis_count = len(prioritized.get("kpis", {}))
    compliance_gaps_count = len(prioritized.get("top_compliance_gaps", []))
    debt_metrics_count = len(prioritized.get("security_debt", {}))
    health_metrics_count = len(prioritized.get("program_health", {}))
    financial_keys_count = len(prioritized.get("financials", {}))

    total_data_points = (
        top_risks_count +
        weakest_domains_count +
        exec_kpis_count +
        compliance_gaps_count +
        debt_metrics_count +
        health_metrics_count +
        financial_keys_count
    )

    print(f"   • Top Risks: {top_risks_count} risks")
    print(f"   • Weakest Domains: {weakest_domains_count} domains")
    print(f"   • Executive KPIs: {exec_kpis_count} metrics")
    print(f"   • Compliance Gaps: {compliance_gaps_count} gaps")
    print(f"   • Security Debt: {debt_metrics_count} metrics")
    print(f"   • Program Health: {health_metrics_count} metrics")
    print(f"   • Financial Aggregates: {financial_keys_count} keys")
    print(f"\n   📉 TOTAL: {total_data_points} data points")

    # Calculate compression ratio
    if total_rows + kpis_count + domains_count > 0:
        compression_ratio = (total_rows + kpis_count + domains_count) / total_data_points
        print(f"\n   🎯 COMPRESSION RATIO: {compression_ratio:.1f}:1")
    else:
        print("\n   ⚠️  No data available for compression ratio calculation")

    # === Display Prioritized Content ===
    print("\n" + "=" * 80)
    print("STAGE 2 PRIORITIZED OUTPUT")
    print("=" * 80)

    # Top Risks
    print("\n🔴 Top 5 Risks by EBITDA Impact:")
    for i, risk in enumerate(prioritized.get("top_risks", []), 1):
        risk_id = risk.get("RiskID", "Unknown")
        domain = risk.get("Domain", "Unknown")
        ebitda = risk.get("EBITDA_Impact", 0)
        likelihood = risk.get("Likelihood", "Unknown")
        desc = risk.get("Description", "")[:60] + "..." if len(risk.get("Description", "")) > 60 else risk.get("Description", "")
        print(f"   {i}. {risk_id} ({domain}) - ${ebitda / 1_000_000:.1f}M | {likelihood}")
        print(f"      {desc}")

    # Weakest Domains
    print("\n⚠️  3 Weakest CISSP Domains:")
    for i, domain_data in enumerate(prioritized.get("weakest_domains", []), 1):
        domain = domain_data.get("domain", "Unknown")
        score = domain_data.get("score", 0)
        status = "🔴 Critical" if score < 2 else "⚠️ At Risk" if score < 3 else "⚡ Needs Improvement"
        print(f"   {i}. {domain}: {score:.1f}/5.0 - {status}")

    # Executive KPIs
    print("\n📊 Executive KPIs:")
    kpis = prioritized.get("kpis", {})
    print(f"   • Total Incidents: {kpis.get('total_incidents', 0)}")
    print(f"   • Critical Incidents: {kpis.get('critical_incidents_count', 0)}")
    print(f"   • Avg MTTD: {kpis.get('avg_mttd_hours', 0):.1f} hours")
    print(f"   • Avg MTTR: {kpis.get('avg_mttr_hours', 0):.1f} hours")
    print(f"   • Open Critical Vulns: {kpis.get('open_critical_vulns', 0)}")
    print(f"   • Overdue Vulns: {kpis.get('overdue_vulns_count', 0)}")
    print(f"   • Failing Controls: {kpis.get('failing_controls_count', 0)}")
    print(f"   • Total EBITDA Impact: ${kpis.get('total_ebitda_impact', 0) / 1_000_000:.1f}M")

    # Top Compliance Gaps
    print("\n📋 Top 3 Compliance Gaps:")
    for i, gap in enumerate(prioritized.get("top_compliance_gaps", []), 1):
        framework = gap.get("Framework", "Unknown")
        req_id = gap.get("RequirementID", "Unknown")
        status = gap.get("Status", "Unknown")
        risk_rating = gap.get("RiskRating", "Unknown")
        desc = gap.get("GapDescription", "")[:60] + "..." if len(gap.get("GapDescription", "")) > 60 else gap.get("GapDescription", "")
        print(f"   {i}. {framework} {req_id} - {status} ({risk_rating} risk)")
        print(f"      {desc}")

    # Security Debt
    print("\n💳 Security Debt:")
    debt = prioritized.get("security_debt", {})
    print(f"   • Total Open Vulns: {debt.get('total_open_vulns', 0)}")
    print(f"   • Critical Vulns Open: {debt.get('critical_vulns_open', 0)}")
    print(f"   • Overdue Vulns: {debt.get('count_overdue_vulns', 0)}")
    print(f"   • Oldest Vuln Age: {debt.get('oldest_vuln_age_days', 0)} days")

    # Program Health
    print("\n🏥 Program Health:")
    health = prioritized.get("program_health", {})
    print(f"   • Total Tasks: {health.get('total_tasks', 0)}")
    print(f"   • In Progress: {health.get('percent_in_progress', 0):.1f}%")
    print(f"   • Not Started: {health.get('percent_not_started', 0):.1f}%")
    print(f"   • Blocked Tasks: {health.get('tasks_blocked_count', 0)}")
    print(f"   • High-Risk Tasks Open: {health.get('high_risk_tasks_open', 0)}")

    # Financial Aggregates
    print("\n💰 Financial Aggregates:")
    financials = prioritized.get("financials", {})
    total_exposure = financials.get("total_exposure", 0)
    total_ebitda = financials.get("total_ebitda_impact", 0)
    print(f"   • Total Exposure: ${total_exposure / 1_000_000:.1f}M")
    print(f"   • Total EBITDA Impact: ${total_ebitda / 1_000_000:.1f}M")

    print("\n   Top 5 Domains by Exposure:")
    exposure_by_domain = financials.get("exposure_by_domain", {})
    for i, (domain, amount) in enumerate(sorted(exposure_by_domain.items(), key=lambda x: x[1], reverse=True)[:5], 1):
        print(f"      {i}. {domain}: ${amount / 1_000_000:.1f}M")

    print("\n   EBITDA by Driver:")
    ebitda_by_driver = financials.get("ebitda_by_driver", {})
    for driver, amount in sorted(ebitda_by_driver.items(), key=lambda x: x[1], reverse=True):
        print(f"      • {driver.capitalize()}: ${amount / 1_000_000:.1f}M")

    # === JSON Output ===
    print("\n" + "=" * 80)
    print("JSON OUTPUT (LLM-Ready)")
    print("=" * 80)

    # Convert to JSON (exclude DataFrames)
    prioritized_for_json = {
        "top_risks": prioritized.get("top_risks", []),
        "weakest_domains": prioritized.get("weakest_domains", []),
        "kpis": prioritized.get("kpis", {}),
        "top_compliance_gaps": prioritized.get("top_compliance_gaps", []),
        "security_debt": prioritized.get("security_debt", {}),
        "program_health": prioritized.get("program_health", {}),
        "financials": prioritized.get("financials", {})
    }

    json_output = json.dumps(prioritized_for_json, indent=2)
    print(f"\n{json_output[:1000]}...")  # Show first 1000 chars
    print(f"\n... ({len(json_output)} total characters)")

    # === Summary ===
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(f"""
✅ Stage 2 Prioritization Complete!

📊 Compression Results:
   • Input:  {total_rows} rows + {kpis_count + domains_count} aggregates
   • Output: {total_data_points} data points
   • Ratio:  {compression_ratio:.1f}:1 compression

🎯 Key Selections:
   • Top {top_risks_count} risks (from {risks_count} total)
   • {weakest_domains_count} weakest domains (from {domains_count} total)
   • {exec_kpis_count} executive KPIs (from {kpis_count} total)
   • {compliance_gaps_count} compliance gaps (from {compliance_count} total)

💡 Next Steps:
   1. Pass `prioritized` dict to Stage 3 (LLM processing)
   2. LLM receives compressed, executive-focused data
   3. Generate board-ready 1,200-word summary
   4. Estimated token reduction: 60-80% vs. full context

🔗 Integration:
   # In main_v2.py:
   prioritized = prioritize_cyber_context(cyber_context)
   summary = summarize_cyber_program_with_ai(prioritized, config, scenario)
""")

if __name__ == "__main__":
    main()
