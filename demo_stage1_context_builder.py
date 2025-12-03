#!/usr/bin/env python3
"""
Demonstration: Stage 1 Fortune-500-Grade Cyber Context Builder

This script demonstrates the new simplified context builder vs the existing comprehensive builder.
"""

import json
import yaml
from pathlib import Path
from src.cyber_context_builder import build_cyber_context

def load_config(config_path: str = "config.yaml"):
    """Load configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main():
    print("=" * 80)
    print("STAGE 1 CONTEXT BUILDER DEMONSTRATION")
    print("=" * 80)

    # Load configuration
    config = load_config()
    scenario = "sentient_cyber_pmo"

    print("\n📋 Scenario: sentient_cyber_pmo")
    print("📂 Data Sources:")
    data_sources = config.get("scenarios", {}).get(scenario, {}).get("data_sources", {})
    for key, path in data_sources.items():
        print(f"   • {key}: {path}")

    # === STAGE 1: Build Cyber Context ===
    print("\n" + "=" * 80)
    print("STAGE 1: Building Cyber Context (Pure Data Transformation)")
    print("=" * 80)

    cyber_context = build_cyber_context(config, scenario)

    # === Display Results ===
    print("\n" + "=" * 80)
    print("STAGE 1 OUTPUT STRUCTURE")
    print("=" * 80)

    print("\n📊 Raw DataFrames Loaded:")
    for df_name in ["risks", "incidents", "vulnerabilities", "controls", "compliance", "tasks"]:
        df = cyber_context.get(df_name)
        if df is not None and not df.empty:
            print(f"   ✓ {df_name}: {len(df)} rows × {len(df.columns)} columns")
        else:
            print(f"   ✗ {df_name}: No data")

    print("\n📈 Computed KPIs:")
    kpis = cyber_context.get("kpis", {})
    for key, value in kpis.items():
        if isinstance(value, float):
            print(f"   • {key}: {value:.2f}")
        else:
            print(f"   • {key}: {value}")

    print("\n🎯 CISSP Domain Scores:")
    domain_scores = cyber_context.get("domain_scores", {})
    for domain, score in sorted(domain_scores.items(), key=lambda x: x[1]):
        status = "✅" if score >= 4 else "⚠️" if score >= 3 else "❌"
        print(f"   {status} {domain}: {score:.1f}/5.0")

    print("\n⚠️  Top Compliance Gaps:")
    compliance_gaps = cyber_context.get("compliance_gaps", [])
    for i, gap in enumerate(compliance_gaps[:5], 1):
        framework = gap.get("Framework", "Unknown")
        req_id = gap.get("RequirementID", "Unknown")
        status = gap.get("Status", "Unknown")
        risk_rating = gap.get("RiskRating", "Unknown")
        print(f"   {i}. {framework} {req_id} - {status} ({risk_rating} risk)")

    print("\n💳 Security Debt Metrics:")
    security_debt = cyber_context.get("security_debt", {})
    for key, value in security_debt.items():
        if isinstance(value, float):
            print(f"   • {key}: {value:.1f}")
        else:
            print(f"   • {key}: {value}")

    print("\n🏥 Program Health Metrics:")
    program_health = cyber_context.get("program_health", {})
    for key, value in program_health.items():
        if isinstance(value, float):
            print(f"   • {key}: {value:.1f}%")
        else:
            print(f"   • {key}: {value}")

    print("\n💰 Financial Aggregates:")
    financials = cyber_context.get("financials", {})
    total_exposure = financials.get("total_exposure", 0)
    total_ebitda = financials.get("total_ebitda_impact", 0)
    print(f"   • Total Exposure: ${total_exposure / 1_000_000:.1f}M")
    print(f"   • Total EBITDA Impact: ${total_ebitda / 1_000_000:.1f}M")

    print("\n   Exposure by Domain:")
    exposure_by_domain = financials.get("exposure_by_domain", {})
    for domain, amount in sorted(exposure_by_domain.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"      • {domain}: ${amount / 1_000_000:.1f}M")

    print("\n   EBITDA by Driver:")
    ebitda_by_driver = financials.get("ebitda_by_driver", {})
    for driver, amount in sorted(ebitda_by_driver.items(), key=lambda x: x[1], reverse=True):
        print(f"      • {driver}: ${amount / 1_000_000:.1f}M")

    # === COMPARISON ===
    print("\n" + "=" * 80)
    print("COMPARISON: Stage 1 vs Existing Comprehensive Builder")
    print("=" * 80)

    comparison = f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│ Feature                          │ Stage 1 Builder    │ Comprehensive      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Lines of Code                    │ ~400 lines         │ ~827 lines         │
│ Pure Data Transformation         │ ✅ Yes             │ ⚠️  Mixed           │
│ LLM Calls                        │ ❌ None            │ ❌ None             │
│ CSV Loading                      │ ✅ 6 files         │ ✅ 11 files         │
│ KPI Computation                  │ ✅ Yes             │ ✅ Yes              │
│ CISSP Domain Scores              │ ✅ Yes (1-5)       │ ⚠️  Via controls    │
│ Compliance Gap Analysis          │ ✅ Yes             │ ✅ Yes              │
│ Security Debt Metrics            │ ✅ Yes             │ ✅ Yes              │
│ Program Health Metrics           │ ✅ Yes             │ ✅ Yes              │
│ Financial Aggregates             │ ✅ Yes             │ ✅ Yes              │
│ Chart Generation                 │ ❌ No (Stage 2)    │ ✅ Yes (embedded)   │
│ Risk Matrix                      │ ❌ No (Stage 2)    │ ✅ Yes              │
│ Stakeholder Quadrants            │ ❌ No (Stage 2)    │ ✅ Yes              │
│ EBITDA Waterfall                 │ ❌ No (Stage 2)    │ ✅ Yes              │
│ Type Annotations                 │ ✅ Full            │ ⚠️  Partial         │
│ Error Handling                   │ ✅ Try-except      │ ✅ Try-except       │
│ Separation of Concerns           │ ✅ Stage 1 only    │ ⚠️  All-in-one      │
└─────────────────────────────────────────────────────────────────────────────┘

RECOMMENDED USE CASES:

Stage 1 Builder (build_cyber_context):
• New scenarios requiring clean separation of data vs LLM processing
• Pipeline architectures with distinct stages
• Testing and validation of data transformation logic
• Scenarios where chart generation happens later in pipeline

Comprehensive Builder (build_cyber_risk_program_context):
• Existing production scenarios (sentient_cyber_pmo)
• All-in-one processing with immediate chart generation
• Scenarios requiring risk matrices and stakeholder quadrants
• When you want everything computed in one function call

MIGRATION PATH:
1. Keep existing comprehensive builder for current production scenarios
2. Use Stage 1 builder for new scenarios going forward
3. Gradually refactor comprehensive builder to call Stage 1 internally
4. Eventually deprecate comprehensive builder in favor of multi-stage pipeline
"""

    print(comparison)

    print("\n" + "=" * 80)
    print("INTEGRATION EXAMPLE")
    print("=" * 80)

    integration_example = '''
# In main_v2.py, line ~4417:

elif scenario == "sentient_cyber_pmo":
    # === STAGE 1: Fortune-500-Grade Context Builder ===
    # Option A: New simplified approach (recommended for future)
    # cyber_context = build_cyber_context(config, scenario)

    # Option B: Existing comprehensive approach (current production)
    cyber_context = build_cyber_risk_program_context(config, scenario)

    # === STAGE 2: Chart Generation (if using Stage 1) ===
    # if using Option A above:
    # from src.cyber_charts import generate_all_cyber_charts
    # chart_paths = generate_all_cyber_charts(cyber_context)
    # cyber_context["chart_paths"] = chart_paths

    # === STAGE 3: LLM Processing ===
    summary = summarize_cyber_program_with_ai(cyber_context, config, scenario)

    # === STAGE 4: Output Generation ===
    html_path = write_html_output(summary, config, scenario, cyber_context=cyber_context)
'''

    print(integration_example)

    print("\n✅ Demonstration complete!")
    print("\nNext Steps:")
    print("  1. ✅ Stage 1 context builder created: src/cyber_context_builder.py")
    print("  2. ✅ Import added to main_v2.py (line 28)")
    print("  3. ✅ Integration point marked in main_v2.py (line 4426)")
    print("  4. 🔄 Future: Migrate new scenarios to use Stage 1 builder")
    print("  5. 🔄 Future: Refactor comprehensive builder to call Stage 1 internally")

if __name__ == "__main__":
    main()
