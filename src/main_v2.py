"""
Status Summarizer Bot v2
AI-powered TPM status report generator that ingests from multiple sources.
"""

import os
import sys
import csv
import datetime
import yaml
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from openai import OpenAI

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from ingestors.jira_ingestor import JiraIngestor
from ingestors.slack_ingestor import SlackIngestor
from ingestors.notes_ingestor import NotesIngestor
from ingestors.csv_ingestor import CSVIngestor
from charts import generate_risk_charts, generate_ebitda_waterfall_chart
from context import build_ebitda_context
from cyber_charts import generate_all_cyber_charts
from cyber_prompt_builder import build_data_driven_cyber_prompt
from cyber_context_builder import build_cyber_context  # Stage 1: Fortune-500-grade context builder



# Load environment variables
load_dotenv()

# Configuration
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
API_KEY = os.getenv("OPENAI_API_KEY")

if not API_KEY:
    raise EnvironmentError("❌ Missing OPENAI_API_KEY — set it in your .env file.")

client = OpenAI(api_key=API_KEY)


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_dashboard_context(config: Dict[str, Any], scenario: str) -> Dict[str, Any]:
    """
    Build a structured dashboard context for the HTML template, driven by Day 2 CSVs.
    This is focused on the 'sentient_cx_risk_radar' scenario.
    """

    ctx: Dict[str, Any] = {}

    if scenario != "sentient_cx_risk_radar":
        return ctx  # For non-Day 2 scenarios, we fall back to defaults in the template.

    # --- 1) Pull scenario-specific configuration ---
    scenario_cfg = config.get("scenarios", {}).get(scenario, {})
    data_sources = scenario_cfg.get("data_sources", {})

    # Expected keys in data_sources (adjust if needed based on config.yaml):
    # - "risk_register": path to CX risk register CSV
    # - "risk_financials": path to financial exposure CSV or same as risk_register
    # - "cx_sentiment": path to weekly sentiment / escalations CSV
    # - "stakeholders": path to stakeholder map CSV
    # - "timeline": path to 7-day action plan CSV

    # Helper function to load CSV safely
    def _safe_read_csv(path_key: str) -> pd.DataFrame:
        source_cfg = data_sources.get(path_key, {})
        if isinstance(source_cfg, dict):
            path = source_cfg.get("path")
        else:
            path = None
        if not path:
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()

    risk_df = _safe_read_csv("risk_register")
    fin_df = _safe_read_csv("risk_financials")
    sentiment_df = _safe_read_csv("cx_sentiment")
    stakeholders_df = _safe_read_csv("stakeholders")
    timeline_df = _safe_read_csv("timeline")

    # --- 2) CX KPIs (status, sentiment, escalations, top exposure) ---

    # Sentiment current and baseline
    sentiment_index_current = None
    sentiment_index_baseline = None
    sentiment_index_previous = None
    sentiment_drop_pct = None
    sentiment_delta_text = None
    escalations_current = None
    escalations_delta_text = None

    if not sentiment_df.empty:
        # Actual columns: week_start, avg_sentiment_score, complaints, escalations, latency_ms, blocked_tickets, trust_index, notes
        sentiment_df = sentiment_df.sort_values("week_start")

        # Baseline: first week in the data
        baseline = sentiment_df.iloc[0]
        sentiment_index_baseline = float(baseline.get("avg_sentiment_score", 0.0))

        # Current: most recent week
        latest = sentiment_df.iloc[-1]
        sentiment_index_current = float(latest.get("avg_sentiment_score", 0.0))

        if len(sentiment_df) >= 2:
            # Previous: second-to-last week for WoW comparison
            prev = sentiment_df.iloc[-2]
            sentiment_index_previous = float(prev.get("avg_sentiment_score", sentiment_index_current))

            # Calculate drop from baseline
            if sentiment_index_baseline and sentiment_index_baseline > 0:
                sentiment_drop_pct = round(((sentiment_index_current - sentiment_index_baseline) / sentiment_index_baseline) * 100.0, 1)

            # WoW delta text
            if sentiment_index_previous:
                pct_change = (sentiment_index_current - sentiment_index_previous) / sentiment_index_previous * 100.0
                arrow = "▲" if pct_change > 0 else "▼" if pct_change < 0 else "■"
                sentiment_delta_text = f"{arrow} {pct_change:.1f}% vs prior period"
        else:
            sentiment_delta_text = "No prior period for comparison"

        escalations_current = int(latest.get("escalations", 0))
        if len(sentiment_df) >= 2:
            prev_esc = float(prev.get("escalations", escalations_current))
            if prev_esc:
                esc_change = (escalations_current - prev_esc) / prev_esc * 100.0
                arrow = "▲" if esc_change > 0 else "▼" if esc_change < 0 else "■"
                escalations_delta_text = f"{arrow} {esc_change:.1f}% vs prior period"
        else:
            escalations_delta_text = "No prior period for comparison"

    # CX status label: simple rule of thumb based on sentiment and escalations
    cx_status_label = "Stable"
    cx_status_subtitle = "Within normal CX risk envelope"

    if sentiment_index_current is not None:
        if sentiment_index_current < 65:
            cx_status_label = "Elevated"
            cx_status_subtitle = "Sentiment below comfort band; monitor closely."
        if sentiment_index_current < 60 or (escalations_current and escalations_current > 10):
            cx_status_label = "Critical"
            cx_status_subtitle = "High escalation volume and deteriorating sentiment."

    # --- 3) Merge risk_register with risk_financials ---

    # Actual risk_register columns: RiskID, Title, Severity, Strategy, Plan, Owner, TargetDate, ImpactLevel, LikelihoodLevel
    # Actual risk_financials columns: RiskID, ExposureMillions

    merged_df = pd.DataFrame()
    if not risk_df.empty and not fin_df.empty:
        # Join on RiskID column present in both CSVs
        merged_df = risk_df.merge(
            fin_df,
            on="RiskID",
            how="left",
            suffixes=("", "_fin"),
        )
    elif not risk_df.empty:
        merged_df = risk_df.copy()

    # Determine exposure column and compute total
    exposure_col = None
    if not merged_df.empty:
        if "ExposureMillions" in merged_df.columns:
            exposure_col = "ExposureMillions"

    total_exposure_millions = 0.0
    if exposure_col:
        total_exposure_millions = float(merged_df[exposure_col].sum() or 0.0)

    # Top exposure label for KPI card
    top_exposure_label = None
    top_exposure_comment = None
    if exposure_col and not merged_df.empty:
        top_row = merged_df.sort_values(exposure_col, ascending=False).iloc[0]
        top_exposure_label = str(top_row.get("RiskID", "Top exposure"))
        top_exposure_comment = str(top_row.get("Title", "Largest single driver of CX financial exposure."))

    # --- 4) Risk heatmap using ImpactLevel × LikelihoodLevel ---

    # Initialize all buckets to $0M
    heatmap = {
        "low_low": "$0M", "low_med": "$0M", "low_high": "$0M", "low_crit": "$0M",
        "med_low": "$0M", "med_med": "$0M", "med_high": "$0M", "med_crit": "$0M",
        "high_low": "$0M", "high_med": "$0M", "high_high": "$0M", "high_crit": "$0M",
        "crit_low": "$0M", "crit_med": "$0M", "crit_high": "$0M", "crit_crit": "$0M",
    }

    impact_col = "ImpactLevel"
    like_col = "LikelihoodLevel"

    if (
        exposure_col is not None
        and impact_col in merged_df.columns
        and like_col in merged_df.columns
    ):
        for _, row in merged_df.iterrows():
            impact = str(row[impact_col]).strip().lower()       # e.g. "high"
            like = str(row[like_col]).strip().lower()           # e.g. "high"

            try:
                exposure_val = float(row[exposure_col] or 0.0)
            except Exception:
                exposure_val = 0.0

            # Map impact/likelihood values to heatmap keys
            # CSV values: "Low", "Medium", "High", "Critical"
            # Heatmap keys: "low", "med", "high", "crit"
            if impact == "critical":
                impact_key = "crit"
            elif impact == "medium":
                impact_key = "med"
            elif impact in ["low", "high"]:
                impact_key = impact
            else:
                impact_key = impact[:3] if len(impact) >= 3 else impact

            if like == "critical":
                like_key = "crit"
            elif like == "medium":
                like_key = "med"
            elif like in ["low", "high"]:
                like_key = like
            else:
                like_key = like[:3] if len(like) >= 3 else like

            key = f"{impact_key}_{like_key}"   # "high_high", "med_low", etc.
            if key in heatmap:
                current_str = heatmap[key]
                try:
                    current_val = float(
                        current_str.replace("$", "").replace("M", "") or 0.0
                    )
                except Exception:
                    current_val = 0.0
                heatmap[key] = f"${current_val + exposure_val:.1f}M"

    # --- 5) Top 3 Risks from merged_df ---

    top_risks: List[Dict[str, Any]] = []

    if exposure_col and not merged_df.empty:
        df_sorted = merged_df.sort_values(exposure_col, ascending=False).head(3)

        for _, r in df_sorted.iterrows():
            try:
                exp_val = float(r[exposure_col] or 0.0)
            except Exception:
                exp_val = 0.0

            share = (
                (exp_val / total_exposure_millions * 100.0)
                if total_exposure_millions
                else None
            )

            top_risks.append({
                "id": r.get("RiskID", "R?"),
                "title": r.get("Title", "Untitled risk"),
                "severity": r.get("Severity", "High"),
                "exposure_millions": round(exp_val, 1),
                "exposure_share": round(share, 1) if share is not None else None,
                "owner": r.get("Owner", "Unassigned"),
                "target_date": r.get("TargetDate", "TBD"),
                "status": r.get("Status", "At Risk") if "Status" in r else "At Risk",
                "plan_summary": r.get("Plan", "Stabilize CX flows and implement controls."),
            })

    # Compute heatmap exposure shares for the sidebar
    high_crit_share = "~0%"
    med_share = "~0%"
    low_share = "~0%"

    if total_exposure_millions:
        def _sum_keys(keys):
            total = 0.0
            for k in keys:
                val = heatmap.get(k, "$0M")
                try:
                    total += float(val.replace("$", "").replace("M", "")) if val else 0.0
                except Exception:
                    continue
            return total

        # High & Critical impact buckets (all High and Critical rows)
        high_crit_total = _sum_keys([
            "high_low", "high_med", "high_high", "high_crit",
            "crit_low", "crit_med", "crit_high", "crit_crit"
        ])
        # Medium impact buckets (entire Medium row)
        med_total = _sum_keys(["med_low", "med_med", "med_high", "med_crit"])
        # Low impact buckets (entire Low row)
        low_total = _sum_keys(["low_low", "low_med", "low_high", "low_crit"])

        high_crit_share = f"{(high_crit_total / total_exposure_millions * 100):.0f}%"
        med_share = f"{(med_total / total_exposure_millions * 100):.0f}%"
        low_share = f"{(low_total / total_exposure_millions * 100):.0f}%"

    # --- 4) Stakeholder quadrants ---

    stakeholders_champions: List[Dict[str, Any]] = []
    stakeholders_blockers: List[Dict[str, Any]] = []
    stakeholders_advocates: List[Dict[str, Any]] = []
    stakeholders_observers: List[Dict[str, Any]] = []

    if not stakeholders_df.empty:
        # Expect columns: Name, Role, Influence (High/Medium/Low), Type or support column
        for (_, row) in stakeholders_df.iterrows():
            item = {
                "name": row.get("Name", row.get("name", "Unknown")),
                "role": row.get("Role", row.get("role", "")),
            }
            influence = str(row.get("Influence", row.get("influence", ""))).lower()

            # Check if there's a support column, otherwise use Type field for classification
            if "support" in row or "Support" in row:
                support = str(row.get("Support", row.get("support", ""))).lower()
            else:
                # Use Type and Role to infer support level
                stype = str(row.get("Type", row.get("type", ""))).lower()
                role_str = str(row.get("Role", row.get("role", ""))).lower()
                name_str = str(row.get("Name", row.get("name", ""))).lower()

                # Classify as blocker if Risk/Compliance related
                if "risk" in role_str or "compliance" in role_str or "renée park" in name_str:
                    support = "low"
                elif stype in ["sponsor", "driver"]:
                    support = "high"
                elif stype in ["deliver", "adopt"]:
                    support = "high"
                else:
                    support = "medium"

            if influence == "high" and support == "high":
                stakeholders_champions.append(item)
            elif influence == "high" and support == "low":
                stakeholders_blockers.append(item)
            elif support == "high":  # Low/Medium influence + high support
                stakeholders_advocates.append(item)
            else:
                stakeholders_observers.append(item)

    # --- 5) 7-day timeline ---
    # Generate timeline phases from risk register data
    timeline_phases: List[Dict[str, Any]] = []

    if not timeline_df.empty and "phase_label" in timeline_df.columns:
        # If timeline CSV exists, use it
        grouped = timeline_df.groupby("phase_label")
        for phase_label, group in grouped:
            actions = [str(a) for a in group["action"].tolist()]
            status_vals = group["status"].dropna().unique().tolist()
            phase_status = status_vals[0] if status_vals else "Planned"
            timeline_phases.append({
                "label": phase_label,
                "status": phase_status,
                "actions": actions,
            })
    else:
        # Generate timeline from risk register based on urgency and target dates
        from datetime import datetime, timedelta

        # Get today's date
        today = datetime.now()

        # Categorize risks by urgency
        immediate_risks = []  # Due within 7 days
        near_term_risks = []  # Due within 30 days

        if not risk_df.empty:
            for _, risk_row in risk_df.iterrows():
                target_date_str = risk_row.get("TargetDate", "")
                severity = risk_row.get("Severity", "")
                title = risk_row.get("Title", "")
                plan = risk_row.get("Plan", "")

                if target_date_str:
                    try:
                        # Parse date (assuming MM/DD/YY format)
                        target_date = datetime.strptime(str(target_date_str), "%m/%d/%y")
                        days_until = (target_date - today).days

                        if days_until <= 7:
                            immediate_risks.append({"title": title, "plan": plan, "severity": severity, "days": days_until})
                        elif days_until <= 30:
                            near_term_risks.append({"title": title, "plan": plan, "severity": severity, "days": days_until})
                    except:
                        pass

        # Build timeline phases
        if immediate_risks or near_term_risks:
            # Phase 1: Days 1-2 (Immediate stabilization)
            phase1_actions = []
            critical_immediate = [r for r in immediate_risks if r["severity"] == "Critical"]
            if critical_immediate:
                for risk in critical_immediate[:2]:  # Top 2 critical
                    phase1_actions.append(f"Emergency mitigation for: {risk['title']}")
            else:
                phase1_actions.append("Triage and assess all critical risks")
                phase1_actions.append("Establish daily stand-ups with key stakeholders")

            timeline_phases.append({
                "label": "Days 1–2",
                "status": "In Progress",
                "actions": phase1_actions
            })

            # Phase 2: Days 3-4 (Core mitigation)
            phase2_actions = []
            high_priority = [r for r in immediate_risks if r["severity"] in ["Critical", "High"]]
            if high_priority:
                for risk in high_priority[:3]:  # Top 3
                    # Extract first sentence of plan
                    plan_summary = risk['plan'].split('.')[0] if risk['plan'] else f"Mitigate {risk['title']}"
                    phase2_actions.append(plan_summary[:100])
            else:
                phase2_actions.append("Deploy primary risk controls and guardrails")
                phase2_actions.append("Review and update escalation procedures")

            timeline_phases.append({
                "label": "Days 3–4",
                "status": "Planned",
                "actions": phase2_actions
            })

            # Phase 3: Days 5-7 (Validation and scale)
            phase3_actions = [
                "Run end-to-end validation of CX flows and risk controls",
                "Scale mitigations across all customer touchpoints",
                "Prepare executive readout and next-phase roadmap"
            ]

            timeline_phases.append({
                "label": "Days 5–7",
                "status": "Planned",
                "actions": phase3_actions
            })
        else:
            # Fallback timeline if no date data
            timeline_phases = [
                {
                    "label": "Days 1–2",
                    "status": "In Progress",
                    "actions": [
                        "Assess all critical and high-severity risks",
                        "Establish emergency response protocols",
                        "Schedule stakeholder alignment meetings"
                    ]
                },
                {
                    "label": "Days 3–4",
                    "status": "Planned",
                    "actions": [
                        "Deploy primary risk mitigations and controls",
                        "Begin stakeholder engagement and communication plan",
                        "Set up monitoring and early warning systems"
                    ]
                },
                {
                    "label": "Days 5–7",
                    "status": "Planned",
                    "actions": [
                        "Validate mitigation effectiveness across CX flows",
                        "Scale successful interventions",
                        "Prepare comprehensive status report for leadership"
                    ]
                }
            ]

    # --- 6) Assemble context dict ---

    ctx.update({
        "cx_status_label": cx_status_label,
        "cx_status_subtitle": cx_status_subtitle,
        "sentiment_index_current": sentiment_index_current,
        "sentiment_index_baseline": sentiment_index_baseline,
        "sentiment_index_previous": sentiment_index_previous,
        "sentiment_drop_pct": sentiment_drop_pct,
        "sentiment_delta_text": sentiment_delta_text,
        "escalations_current": escalations_current,
        "escalations_delta_text": escalations_delta_text,
        "top_exposure_label": top_exposure_label,
        "top_exposure_comment": top_exposure_comment,
        "total_exposure_millions": round(total_exposure_millions, 1) if total_exposure_millions else 0.0,
        "total_mapped_exposure_millions": round(total_exposure_millions, 1) if total_exposure_millions else 0.0,  # Same source of truth
        "risk_heatmap": heatmap,
        "high_crit_share": high_crit_share,
        "med_share": med_share,
        "low_share": low_share,
        "top_risks": top_risks,
        "stakeholders_champions": stakeholders_champions,
        "stakeholders_blockers": stakeholders_blockers,
        "stakeholders_advocates": stakeholders_advocates,
        "stakeholders_observers": stakeholders_observers,
        "timeline_phases": timeline_phases,
    })

    return ctx


def ingest_all_sources(config: Dict[str, Any], scenario: str = None) -> str:
    """
    Ingest data from all enabled sources and combine into one text.

    Args:
        config: Application configuration
        scenario: Optional scenario name to use scenario-specific data sources

    Returns:
        Combined text from all data sources
    """
    # Get data sources from scenario config or default config
    if scenario and scenario in config.get("scenarios", {}):
        data_sources = config["scenarios"][scenario].get("data_sources", {})
        print(f"\n📥 Ingesting data for scenario: {scenario}...")
    else:
        data_sources = config.get("data_sources", {})
        print("\n📥 Ingesting data from sources...")

    combined_text = []

    # Define display names for each source
    display_names = {
        "meeting_notes": "Meeting Notes",
        "jira": "Jira",
        "slack": "Slack",
        "wrike": "Wrike",
        "gmail": "Gmail",
        "hubspot": "HubSpot",
        "confluence": "Confluence",
        "calendar": "Calendar",
        "risk_register": "Risk Register",
        "stakeholders": "Stakeholders",
    }

    # Process each enabled source
    for source_key in data_sources.keys():
        source_config = data_sources.get(source_key, {})
        if not source_config.get("enabled", False):
            continue

        display_name = display_names.get(source_key, source_key.replace("_", " ").title())

        try:
            # Determine file type from path extension
            file_path = source_config.get("path", "")
            is_csv = file_path.endswith(".csv")
            is_json = file_path.endswith(".json")
            is_text = file_path.endswith(".txt")

            # Select appropriate ingestor based on file type and source
            if is_csv:
                ingestor = CSVIngestor(source_config, source_name=display_name)
                source_type = "csv"
            elif source_key == "jira" and is_json:
                ingestor = JiraIngestor(source_config)
                source_type = "jira"
            elif source_key == "slack" and is_json:
                ingestor = SlackIngestor(source_config)
                source_type = "slack"
            elif source_key == "meeting_notes" or is_text:
                ingestor = NotesIngestor(source_config)
                source_type = "text"
            else:
                # Default to CSV for unknown types
                ingestor = CSVIngestor(source_config, source_name=display_name)
                source_type = "csv"

            # Ingest and format data
            data = ingestor.ingest()
            formatted = ingestor.format_for_prompt(data)
            combined_text.append(formatted)

            # Display success message with record count
            if source_type == "csv":
                record_count = data.get("row_count", 0)
                print(f"  ✓ {display_name}: {record_count} records")
            elif source_type == "jira":
                issue_count = len(data.get("issues", []))
                print(f"  ✓ {display_name}: {issue_count} issues")
            elif source_type == "slack":
                thread_count = sum(len(ch.get("threads", [])) for ch in data.get("channels", []))
                print(f"  ✓ {display_name}: {thread_count} threads")
            else:
                print(f"  ✓ {display_name}")

        except Exception as e:
            print(f"  ✗ {display_name} failed: {e}")

    if not combined_text:
        raise ValueError("No data sources were successfully ingested!")

    return "\n\n" + "="*80 + "\n\n".join(combined_text)


def build_risk_context(config: Dict[str, Any], scenario: str) -> Dict[str, Any]:
    """
    Build structured context for consulting-grade CX Risk Radar scenario.

    Transforms raw CSV data into analyzed, structured context with:
    - Merged risks (risk_register + risk_financials)
    - CX sentiment trend analysis
    - Raw data from all sources
    - Empty shells for future analytics

    Args:
        config: Application configuration
        scenario: Scenario name (e.g., 'sentient_cx_risk_radar')

    Returns:
        Structured context dict ready for advanced analytics
    """
    print(f"\n🔬 Building structured context for scenario: {scenario}...")

    # Load scenario configuration
    scenario_config = config.get("scenarios", {}).get(scenario)
    if not scenario_config:
        raise ValueError(f"Scenario '{scenario}' not found in config")

    data_sources = scenario_config.get("data_sources", {})
    scenario_title = scenario_config.get("title", scenario)

    # Initialize context structure
    context = {
        "scenario": scenario,
        "scenario_title": scenario_title,
        "risks": [],
        "cx_sentiment_trend": [],
        "stakeholders_raw": [],
        "jira_raw": [],
        "wrike_raw": [],
        "slack_raw": [],
        "gmail_raw": [],
        "hubspot_raw": [],
        "confluence_raw": [],
        "calendar_raw": [],
        # Empty shells for future analytics
        "exec_summary_inputs": {},
        "heatmap": {},
        "risk_trajectory": [],
        "stakeholder_map": {},
        "next_actions_seed": {}
    }

    # Helper function to load CSV data
    def load_csv_data(source_key: str) -> List[Dict[str, Any]]:
        """Load CSV data using CSVIngestor."""
        source_config = data_sources.get(source_key, {})
        if not source_config.get("enabled", False):
            return []

        try:
            ingestor = CSVIngestor(source_config, source_name=source_key)
            data = ingestor.ingest()
            rows = data.get("rows", [])
            print(f"  ✓ Loaded {source_key}: {len(rows)} records")
            return rows
        except Exception as e:
            print(f"  ✗ Failed to load {source_key}: {e}")
            return []

    # Load risk register
    risk_register_rows = load_csv_data("risk_register")

    # Load risk financials
    risk_financials_rows = load_csv_data("risk_financials")

    # Create lookup dict for financials
    # New CSV structure: RiskID, ExposureMillions
    financials_by_risk_id = {
        row.get("RiskID"): row for row in risk_financials_rows
    }

    # Join risks with financials
    for risk_row in risk_register_rows:
        risk_id = risk_row.get("RiskID", "")
        financial_data = financials_by_risk_id.get(risk_id, {})

        # Parse financial values (default to 0 if missing/invalid)
        def safe_float(value, default=0.0):
            try:
                return float(value) if value else default
            except (ValueError, TypeError):
                return default

        # New CSV structure uses ExposureMillions directly (already in millions)
        exposure_millions = safe_float(financial_data.get("ExposureMillions"))

        # Convert to dollars for total_exposure (charts expect dollars, not millions)
        total_exposure = exposure_millions * 1_000_000

        # Build merged risk dict
        merged_risk = {
            "id": risk_id,
            "title": risk_row.get("Title", ""),
            "severity": risk_row.get("Severity", ""),
            "likelihood": risk_row.get("LikelihoodLevel", ""),  # Use new column name
            "strategy": risk_row.get("Strategy", ""),
            "plan": risk_row.get("Plan", ""),
            "owner": risk_row.get("Owner", ""),
            "target_date": risk_row.get("TargetDate", ""),
            "exposure_millions": exposure_millions,
            "total_exposure": total_exposure,
            "financial_notes": financial_data.get("notes", "")
        }

        context["risks"].append(merged_risk)

    print(f"  ✓ Merged risks with financials: {len(context['risks'])} risks")

    # Load CX sentiment trend
    context["cx_sentiment_trend"] = load_csv_data("cx_sentiment")

    # Load stakeholders
    context["stakeholders_raw"] = load_csv_data("stakeholders")

    # Load other data sources
    context["jira_raw"] = load_csv_data("jira")
    context["wrike_raw"] = load_csv_data("wrike")
    context["slack_raw"] = load_csv_data("slack")
    context["gmail_raw"] = load_csv_data("gmail")
    context["hubspot_raw"] = load_csv_data("hubspot")
    context["confluence_raw"] = load_csv_data("confluence")
    context["calendar_raw"] = load_csv_data("calendar")

    print(f"✓ Context built successfully: {len(context['risks'])} risks, {len(context['cx_sentiment_trend'])} sentiment records, {len(context['stakeholders_raw'])} stakeholders\n")

    return context


def generate_cyber_charts(context: Dict[str, Any], output_dir: str = "output") -> Dict[str, str]:
    """
    Generate cybersecurity-specific charts using matplotlib.

    Returns dict of chart_name -> file_path for template injection.
    """
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import numpy as np
    from datetime import datetime

    # Create charts directory
    charts_dir = Path(output_dir) / "charts" / "cyber"
    charts_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chart_paths = {}

    print("\n  📊 Generating cybersecurity visualization charts...")

    # === EBITDA WATERFALL CHART ===

    # 0. EBITDA Impact Waterfall (Executive Financial View)
    try:
        ebitda_components = context.get("ebitda_impact_components", {})
        waterfall_data = ebitda_components.get("waterfall_components", [])

        if waterfall_data:
            fig, ax = plt.subplots(figsize=(14, 8))

            # Extract labels and values
            labels = [c["label"] for c in waterfall_data]
            values = [c["value"] for c in waterfall_data]
            types = [c["type"] for c in waterfall_data]

            # Calculate cumulative values for waterfall positioning
            cumulative = [0]
            for i in range(len(values) - 1):
                if types[i] == "baseline":
                    cumulative.append(values[i])
                elif types[i+1] == "final":
                    cumulative.append(0)  # Final bar starts from 0
                else:
                    cumulative.append(cumulative[-1] + values[i])

            # Plot bars with color coding
            colors = []
            for t in types:
                if t == "baseline":
                    colors.append('#3b82f6')  # Blue for baseline
                elif t == "negative":
                    colors.append('#dc2626')  # Red for negative impacts
                elif t == "investment":
                    colors.append('#f59e0b')  # Amber for remediation spend
                elif t == "final":
                    colors.append('#10b981')  # Green for final adjusted EBITDA
                else:
                    colors.append('#6b7280')  # Gray default

            # Create waterfall bars
            for i, (label, value, cum, color) in enumerate(zip(labels, values, cumulative, colors)):
                if types[i] == "baseline" or types[i] == "final":
                    # Full height bars for baseline and final
                    ax.bar(i, abs(value), bottom=0, color=color, edgecolor='white',
                          linewidth=2, alpha=0.9, width=0.8)
                else:
                    # Floating bars for changes
                    ax.bar(i, abs(value), bottom=cum, color=color, edgecolor='white',
                          linewidth=2, alpha=0.9, width=0.8)

                # Add value labels on bars
                if types[i] == "baseline" or types[i] == "final":
                    y_pos = abs(value) / 2
                else:
                    y_pos = cum + abs(value) / 2

                # Format label text
                if value >= 0:
                    label_text = f"${abs(value):.1f}M"
                else:
                    label_text = f"-${abs(value):.1f}M"

                ax.text(i, y_pos, label_text, ha='center', va='center',
                       fontsize=11, fontweight='700', color='white' if types[i] != 'baseline' else 'white')

            # Add connecting lines between bars (optional)
            for i in range(len(values) - 1):
                if types[i] != "final" and types[i+1] != "final":
                    next_y = cumulative[i+1]
                    current_y = cumulative[i] + values[i] if types[i] != "baseline" else values[i]
                    ax.plot([i + 0.4, i + 1.4], [current_y, next_y], 'k--', linewidth=1, alpha=0.3)

            # Styling
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=25, ha='right', fontsize=11, fontweight='600')
            ax.set_ylabel('EBITDA Impact ($M)', fontsize=13, fontweight='700')
            ax.set_title('Security EBITDA Impact Waterfall: Baseline → Risk-Adjusted',
                        fontsize=15, fontweight='700', pad=20)
            ax.grid(axis='y', alpha=0.25, linestyle='--')
            ax.axhline(y=0, color='black', linewidth=1.5, alpha=0.7)

            # Add legend
            from matplotlib.patches import Patch
            legend_elements = [
                Patch(facecolor='#3b82f6', label='Baseline EBITDA'),
                Patch(facecolor='#dc2626', label='Cyber Risk Exposure'),
                Patch(facecolor='#f59e0b', label='Remediation Investment'),
                Patch(facecolor='#10b981', label='Risk-Adjusted EBITDA')
            ]
            ax.legend(handles=legend_elements, loc='upper right', frameon=True,
                     shadow=True, fontsize=10)

            plt.tight_layout()

            # Save
            chart_path = charts_dir / f"ebitda_waterfall_{timestamp}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()

            chart_paths["ebitda_waterfall_chart"] = f"charts/cyber/ebitda_waterfall_{timestamp}.png"
            print(f"    ✓ EBITDA waterfall chart generated")
    except Exception as e:
        print(f"    ⚠ Skipping EBITDA waterfall chart: {e}")

    # === CORE OVERVIEW CHARTS (High-Impact) ===

    # 1. Incident Trend Over Time
    try:
        security_metrics = context.get("security_metrics", [])
        if security_metrics:
            fig, ax = plt.subplots(figsize=(10, 6))

            # Extract weekly data
            weeks = [m.get("week_start", f"Week {i+1}") for i, m in enumerate(security_metrics)]
            incidents_detected = [int(m.get("incidents_detected", 0)) for m in security_metrics]
            incidents_resolved = [int(m.get("incidents_resolved", 0)) for m in security_metrics]

            # Plot lines
            ax.plot(weeks, incidents_detected, marker='o', linewidth=2.5,
                   color='#dc2626', label='Incidents Detected', markersize=8)
            ax.plot(weeks, incidents_resolved, marker='s', linewidth=2.5,
                   color='#10b981', label='Incidents Resolved', markersize=8)

            # Styling
            ax.set_xlabel('Week Starting', fontsize=12, fontweight='600')
            ax.set_ylabel('Incident Count', fontsize=12, fontweight='600')
            ax.set_title('Incident Trend: Detection vs. Resolution', fontsize=14, fontweight='700', pad=20)
            ax.legend(loc='upper left', frameon=True, shadow=True)
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()

            # Save
            chart_path = charts_dir / f"cyber_incident_trend_{timestamp}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()

            chart_paths["cyber_incident_trend"] = f"charts/cyber/cyber_incident_trend_{timestamp}.png"
            print(f"    ✓ Incident trend chart generated")
    except Exception as e:
        print(f"    ⚠ Skipping incident trend chart: {e}")

    # 2. Vulnerability Severity Distribution (Bar Chart)
    try:
        vulnerabilities = context.get("vulnerabilities", [])
        if vulnerabilities:
            fig, ax = plt.subplots(figsize=(10, 6))

            # Count by severity
            severity_counts = {
                'Critical': len([v for v in vulnerabilities if v.get("Severity") == "Critical"]),
                'High': len([v for v in vulnerabilities if v.get("Severity") == "High"]),
                'Medium': len([v for v in vulnerabilities if v.get("Severity") == "Medium"]),
                'Low': len([v for v in vulnerabilities if v.get("Severity") == "Low"])
            }

            severities = list(severity_counts.keys())
            counts = list(severity_counts.values())
            colors = ['#dc2626', '#f59e0b', '#6b7280', '#10b981']

            # Create bar chart
            bars = ax.bar(severities, counts, color=colors, alpha=0.8, edgecolor='white', linewidth=2)

            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{int(height)}',
                       ha='center', va='bottom', fontsize=12, fontweight='700')

            ax.set_xlabel('Severity Level', fontsize=12, fontweight='600')
            ax.set_ylabel('Vulnerability Count', fontsize=12, fontweight='600')
            ax.set_title('Vulnerability Distribution by Severity', fontsize=14, fontweight='700', pad=20)
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            plt.tight_layout()

            # Save
            chart_path = charts_dir / f"cyber_vuln_severity_{timestamp}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()

            chart_paths["cyber_vuln_severity"] = f"charts/cyber/cyber_vuln_severity_{timestamp}.png"
            print(f"    ✓ Vulnerability severity chart generated")
    except Exception as e:
        print(f"    ⚠ Skipping vulnerability severity chart: {e}")

    # 3. Control/Compliance Coverage vs. Gaps
    try:
        controls = context.get("controls", [])
        if controls:
            fig, ax = plt.subplots(figsize=(10, 6))

            # Categorize controls by maturity
            mature_controls = len([c for c in controls if float(c.get("MaturityScore", 0)) >= 85])
            developing_controls = len([c for c in controls if 60 <= float(c.get("MaturityScore", 0)) < 85])
            baseline_controls = len([c for c in controls if 40 <= float(c.get("MaturityScore", 0)) < 60])
            immature_controls = len([c for c in controls if float(c.get("MaturityScore", 0)) < 40])

            # Count controls with gaps
            controls_with_gaps = len([c for c in controls if c.get("HasGap") == "Yes"])
            controls_no_gaps = len(controls) - controls_with_gaps

            # Create stacked bar chart
            categories = ['Maturity Levels', 'Gap Status']

            # Maturity breakdown
            maturity_data = [mature_controls, developing_controls, baseline_controls, immature_controls]
            gap_data = [controls_no_gaps, controls_with_gaps]

            x = np.arange(len(categories))
            width = 0.6

            # Plot maturity levels
            ax.bar(0, mature_controls, width, label='Mature (≥85%)', color='#10b981', alpha=0.9)
            ax.bar(0, developing_controls, width, bottom=mature_controls, label='Developing (60-84%)', color='#3b82f6', alpha=0.9)
            ax.bar(0, baseline_controls, width, bottom=mature_controls+developing_controls, label='Baseline (40-59%)', color='#f59e0b', alpha=0.9)
            ax.bar(0, immature_controls, width, bottom=mature_controls+developing_controls+baseline_controls, label='Immature (<40%)', color='#dc2626', alpha=0.9)

            # Plot gap status
            ax.bar(1, controls_no_gaps, width, label='No Gaps', color='#10b981', alpha=0.9)
            ax.bar(1, controls_with_gaps, width, bottom=controls_no_gaps, label='Has Gaps', color='#dc2626', alpha=0.9)

            ax.set_ylabel('Control Count', fontsize=12, fontweight='600')
            ax.set_title('Security Controls: Maturity & Gap Analysis', fontsize=14, fontweight='700', pad=20)
            ax.set_xticks(x)
            ax.set_xticklabels(categories)
            ax.legend(loc='upper right', frameon=True, shadow=True, fontsize=9)
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            plt.tight_layout()

            # Save
            chart_path = charts_dir / f"cyber_controls_coverage_{timestamp}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()

            chart_paths["cyber_controls_coverage"] = f"charts/cyber/cyber_controls_coverage_{timestamp}.png"
            print(f"    ✓ Control coverage chart generated")
    except Exception as e:
        print(f"    ⚠ Skipping control coverage chart: {e}")

    # === DETAILED CHARTS (Existing) ===

    # 4. Vulnerability Aging Histogram
    try:
        vulnerabilities = context.get("vulnerabilities", [])
        if vulnerabilities:
            fig, ax = plt.subplots(figsize=(10, 6))

            # Extract days open by severity
            critical_days = [int(v.get("DaysOpen", 0)) for v in vulnerabilities if v.get("Severity") == "Critical"]
            high_days = [int(v.get("DaysOpen", 0)) for v in vulnerabilities if v.get("Severity") == "High"]
            medium_days = [int(v.get("DaysOpen", 0)) for v in vulnerabilities if v.get("Severity") == "Medium"]

            # Create histogram bins
            bins = [0, 7, 30, 90, 180, 365]
            bin_labels = ['0-7d', '7-30d', '30-90d', '90-180d', '180d+']

            ax.hist([critical_days, high_days, medium_days], bins=bins,
                   label=['Critical', 'High', 'Medium'],
                   color=['#dc2626', '#f59e0b', '#6b7280'],
                   alpha=0.8, edgecolor='white', linewidth=1.5)

            ax.set_xlabel('Days Open', fontsize=12, fontweight='600')
            ax.set_ylabel('Vulnerability Count', fontsize=12, fontweight='600')
            ax.set_title('Vulnerability Aging Distribution by Severity', fontsize=14, fontweight='700', pad=20)
            ax.legend(loc='upper right', frameon=True, shadow=True)
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            ax.axvline(x=7, color='#dc2626', linestyle='--', alpha=0.5, label='Critical SLA (7d)')
            ax.axvline(x=30, color='#f59e0b', linestyle='--', alpha=0.5, label='High SLA (30d)')

            plt.tight_layout()
            chart_path = charts_dir / f"vuln_aging_{timestamp}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()
            chart_paths["vuln_aging_chart"] = f"charts/cyber/vuln_aging_{timestamp}.png"
            print(f"    ✓ Vulnerability aging histogram generated")
    except Exception as e:
        print(f"    ⚠ Skipping vuln aging chart: {e}")

    # 2. Incident Velocity Trendline
    try:
        metrics = context.get("security_metrics", [])
        if metrics:
            fig, ax = plt.subplots(figsize=(10, 6))

            weeks = [m.get("week_start", "") for m in metrics]
            incidents_detected = [int(m.get("incidents_detected", 0)) for m in metrics]

            ax.plot(range(len(weeks)), incidents_detected, marker='o', linewidth=2.5,
                   markersize=8, color='#0ea5e9', label='Incidents Detected')

            # 4-week moving average
            if len(incidents_detected) >= 4:
                moving_avg = np.convolve(incidents_detected, np.ones(4)/4, mode='valid')
                ax.plot(range(len(moving_avg)), moving_avg, linestyle='--', linewidth=2,
                       color='#f59e0b', label='4-Week Moving Average', alpha=0.7)

            ax.set_xlabel('Week', fontsize=12, fontweight='600')
            ax.set_ylabel('Incidents Detected', fontsize=12, fontweight='600')
            ax.set_title('Incident Velocity: Weekly Detection Rate', fontsize=14, fontweight='700', pad=20)
            ax.set_xticks(range(len(weeks)))
            ax.set_xticklabels([w.split('/')[0] if '/' in w else w for w in weeks], rotation=45, ha='right')
            ax.legend(loc='upper left', frameon=True, shadow=True)
            ax.grid(axis='both', alpha=0.3, linestyle='--')

            plt.tight_layout()
            chart_path = charts_dir / f"incident_velocity_{timestamp}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()
            chart_paths["incident_velocity_chart"] = f"charts/cyber/incident_velocity_{timestamp}.png"
            print(f"    ✓ Incident velocity trendline generated")
    except Exception as e:
        print(f"    ⚠ Skipping incident velocity chart: {e}")

    # 3. Top Threat Categories Bar Chart
    try:
        threat_intel = context.get("threat_intel", [])
        if threat_intel:
            fig, ax = plt.subplots(figsize=(10, 6))

            # Count threat categories (TTPs)
            ttp_counts = {}
            for threat in threat_intel:
                ttp = threat.get("TTP", "Unknown")
                ttp_label = ttp.split(' - ')[1] if ' - ' in ttp else ttp
                ttp_counts[ttp_label] = ttp_counts.get(ttp_label, 0) + 1

            # Sort by count and take top 8
            sorted_ttps = sorted(ttp_counts.items(), key=lambda x: x[1], reverse=True)[:8]
            labels = [t[0][:30] for t in sorted_ttps]  # Truncate long labels
            counts = [t[1] for t in sorted_ttps]

            colors = ['#dc2626' if c >= 2 else '#f59e0b' if c > 0 else '#6b7280' for c in counts]
            bars = ax.barh(labels, counts, color=colors, edgecolor='white', linewidth=1.5)

            ax.set_xlabel('Threat Actor Count', fontsize=12, fontweight='600')
            ax.set_ylabel('MITRE ATT&CK Technique', fontsize=12, fontweight='600')
            ax.set_title('Top Threat Categories (MITRE ATT&CK)', fontsize=14, fontweight='700', pad=20)
            ax.grid(axis='x', alpha=0.3, linestyle='--')

            # Add value labels on bars
            for bar in bars:
                width = bar.get_width()
                ax.text(width + 0.1, bar.get_y() + bar.get_height()/2,
                       f'{int(width)}', ha='left', va='center', fontsize=10, fontweight='600')

            plt.tight_layout()
            chart_path = charts_dir / f"threat_categories_{timestamp}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()
            chart_paths["threat_categories_chart"] = f"charts/cyber/threat_categories_{timestamp}.png"
            print(f"    ✓ Threat categories bar chart generated")
    except Exception as e:
        print(f"    ⚠ Skipping threat categories chart: {e}")

    # 4. Alert Triage Funnel
    try:
        metrics = context.get("security_metrics", [])
        if metrics:
            fig, ax = plt.subplots(figsize=(10, 6))

            # Use latest week metrics
            latest = metrics[-1] if metrics else {}

            # Funnel data (Detection → Analysis → Containment → Closure)
            stages = ['Detection', 'Analysis', 'Containment', 'Closure']
            # Model: 100% detected, 85% analyzed, 70% contained, 60% closed
            incidents_detected = int(latest.get("incidents_detected", 8))
            values = [
                incidents_detected,
                int(incidents_detected * 0.85),
                int(incidents_detected * 0.70),
                int(incidents_detected * 0.60)
            ]

            colors_funnel = ['#0ea5e9', '#10b981', '#f59e0b', '#6b7280']

            # Create funnel (inverted pyramid)
            y_pos = np.arange(len(stages))
            bars = ax.barh(y_pos, values, color=colors_funnel, edgecolor='white', linewidth=2)

            ax.set_yticks(y_pos)
            ax.set_yticklabels(stages, fontsize=12, fontweight='600')
            ax.set_xlabel('Alert Count', fontsize=12, fontweight='600')
            ax.set_title('Alert Triage Funnel: Detection → Closure', fontsize=14, fontweight='700', pad=20)
            ax.grid(axis='x', alpha=0.3, linestyle='--')

            # Add percentage labels
            for i, (bar, val) in enumerate(zip(bars, values)):
                pct = (val / incidents_detected * 100) if incidents_detected > 0 else 0
                ax.text(val + 0.2, bar.get_y() + bar.get_height()/2,
                       f'{val} ({pct:.0f}%)', ha='left', va='center',
                       fontsize=11, fontweight='600')

            plt.tight_layout()
            chart_path = charts_dir / f"alert_triage_funnel_{timestamp}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close()
            chart_paths["alert_triage_funnel"] = f"charts/cyber/alert_triage_funnel_{timestamp}.png"

            # Calculate closure rate for template
            closure_rate = (values[-1] / incidents_detected * 100) if incidents_detected > 0 else 0
            chart_paths["alert_closure_rate"] = int(closure_rate)

            print(f"    ✓ Alert triage funnel generated")
    except Exception as e:
        print(f"    ⚠ Skipping alert triage funnel: {e}")

    # 5. MITRE ATT&CK Heatmap (simplified)
    try:
        fig, ax = plt.subplots(figsize=(14, 8))

        # MITRE ATT&CK tactics (simplified 14 tactics)
        tactics = [
            'Initial Access', 'Execution', 'Persistence', 'Privilege Escalation',
            'Defense Evasion', 'Credential Access', 'Discovery', 'Lateral Movement',
            'Collection', 'Command & Control', 'Exfiltration', 'Impact',
            'Resource Development', 'Reconnaissance'
        ]

        # Mock detection coverage (0-100%)
        coverage = np.random.randint(30, 95, size=len(tactics))

        # Create heatmap
        colors_map = ['#dc2626' if c < 50 else '#f59e0b' if c < 75 else '#10b981' for c in coverage]
        bars = ax.barh(tactics, coverage, color=colors_map, edgecolor='white', linewidth=2)

        ax.set_xlabel('Detection Coverage (%)', fontsize=12, fontweight='600')
        ax.set_ylabel('MITRE ATT&CK Tactic', fontsize=12, fontweight='600')
        ax.set_title('MITRE ATT&CK Detection Coverage by Tactic', fontsize=14, fontweight='700', pad=20)
        ax.set_xlim(0, 100)
        ax.grid(axis='x', alpha=0.3, linestyle='--')

        # Add coverage % labels
        for bar, cov in zip(bars, coverage):
            ax.text(cov + 2, bar.get_y() + bar.get_height()/2,
                   f'{cov}%', ha='left', va='center', fontsize=10, fontweight='600')

        plt.tight_layout()
        chart_path = charts_dir / f"mitre_attack_heatmap_{timestamp}.png"
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        chart_paths["mitre_attack_heatmap"] = f"charts/cyber/mitre_attack_heatmap_{timestamp}.png"
        print(f"    ✓ MITRE ATT&CK heatmap generated")
    except Exception as e:
        print(f"    ⚠ Skipping MITRE ATT&CK heatmap: {e}")

    # 6. Attack Surface Tree Diagram (placeholder network graph)
    try:
        fig, ax = plt.subplots(figsize=(10, 8))

        # Simple tree visualization
        # Root: Internet → DMZ → Internal
        layers = {
            'Internet': (0, ['Web Server', 'API Gateway']),
            'DMZ': (1, ['Web Server', 'API Gateway', 'Load Balancer']),
            'Internal': (2, ['App Servers', 'Databases', 'File Shares'])
        }

        ax.text(0.5, 0.9, 'Internet', ha='center', fontsize=14, fontweight='700',
               bbox=dict(boxstyle='round,pad=0.5', facecolor='#dc2626', edgecolor='white', alpha=0.8))
        ax.text(0.3, 0.6, 'Web Server\n(High Risk)', ha='center', fontsize=11,
               bbox=dict(boxstyle='round,pad=0.4', facecolor='#f59e0b', edgecolor='white'))
        ax.text(0.7, 0.6, 'API Gateway\n(High Risk)', ha='center', fontsize=11,
               bbox=dict(boxstyle='round,pad=0.4', facecolor='#f59e0b', edgecolor='white'))
        ax.text(0.2, 0.3, 'App Servers\n(Medium)', ha='center', fontsize=10,
               bbox=dict(boxstyle='round,pad=0.3', facecolor='#6b7280', edgecolor='white'))
        ax.text(0.5, 0.3, 'Databases\n(Critical)', ha='center', fontsize=10,
               bbox=dict(boxstyle='round,pad=0.3', facecolor='#dc2626', edgecolor='white'))
        ax.text(0.8, 0.3, 'File Shares\n(Low)', ha='center', fontsize=10,
               bbox=dict(boxstyle='round,pad=0.3', facecolor='#10b981', edgecolor='white'))

        # Draw connection lines
        ax.plot([0.5, 0.3], [0.88, 0.62], 'k-', linewidth=2, alpha=0.3)
        ax.plot([0.5, 0.7], [0.88, 0.62], 'k-', linewidth=2, alpha=0.3)
        ax.plot([0.3, 0.2], [0.58, 0.32], 'k-', linewidth=1.5, alpha=0.3)
        ax.plot([0.3, 0.5], [0.58, 0.32], 'k-', linewidth=1.5, alpha=0.3)
        ax.plot([0.7, 0.5], [0.58, 0.32], 'k-', linewidth=1.5, alpha=0.3)
        ax.plot([0.7, 0.8], [0.58, 0.32], 'k-', linewidth=1.5, alpha=0.3)

        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        ax.set_title('Attack Surface Topology: External → Internal Zones',
                    fontsize=14, fontweight='700', pad=20)

        plt.tight_layout()
        chart_path = charts_dir / f"attack_surface_tree_{timestamp}.png"
        plt.savefig(chart_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        chart_paths["attack_surface_tree_chart"] = f"charts/cyber/attack_surface_tree_{timestamp}.png"
        print(f"    ✓ Attack surface tree diagram generated")
    except Exception as e:
        print(f"    ⚠ Skipping attack surface tree: {e}")

    print(f"  ✅ Generated {len([k for k in chart_paths if k != 'alert_closure_rate'])} cyber visualization charts\n")

    return chart_paths


def build_cyber_risk_matrix(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build cyber risk heatmap matrix (Impact × Likelihood) from real CSV data.

    Creates a 4×4 grid mapping risks using actual ImpactLevel and LikelihoodLevel
    columns from security_risk_register.csv, with financial exposure from
    security_financials.csv for color intensity.

    Args:
        context: Full cyber context with risks and cyber_data_frames

    Returns:
        Dict with matrix cells containing count, exposure_millions, risk_ids, and risk_details
    """
    # Define matrix dimensions (matching CSV values)
    impact_levels = ["Low", "Medium", "High", "Critical"]
    likelihood_levels = ["Low", "Medium", "High", "Critical"]  # Match CSV

    # Initialize matrix cells
    matrix = {}
    for impact in impact_levels:
        for likelihood in likelihood_levels:
            cell_key = f"{impact}_{likelihood}"
            matrix[cell_key] = {
                "count": 0,
                "exposure_millions": 0.0,
                "risk_ids": [],
                "risk_details": []  # Store risk details for tooltips
            }

    # Use DataFrames for accurate mapping
    if "cyber_data_frames" in context:
        risk_df = context["cyber_data_frames"].get("security_risk_register")
        financials_df = context["cyber_data_frames"].get("security_financials")

        if risk_df is not None and not risk_df.empty:
            # Merge with financials for exposure amounts
            if financials_df is not None and not financials_df.empty:
                merged = risk_df.merge(financials_df, on="RiskID", how="left")
            else:
                merged = risk_df.copy()
                merged["ExposureMillions"] = 0.0

            # Map each risk to matrix cell
            for _, row in merged.iterrows():
                risk_id = row.get("RiskID", "Unknown")
                impact = row.get("ImpactLevel", "Medium")
                likelihood = row.get("LikelihoodLevel", "Medium")
                exposure = row.get("ExposureMillions", 0.0)
                title = row.get("Title", "Unknown Risk")
                severity = row.get("Severity", "Medium")

                # Validate levels exist in our matrix
                if impact not in impact_levels:
                    impact = "Medium"  # Default fallback
                if likelihood not in likelihood_levels:
                    likelihood = "Medium"  # Default fallback

                cell_key = f"{impact}_{likelihood}"
                matrix[cell_key]["count"] += 1
                matrix[cell_key]["exposure_millions"] += exposure
                matrix[cell_key]["risk_ids"].append(risk_id)
                matrix[cell_key]["risk_details"].append({
                    "id": risk_id,
                    "title": title,
                    "severity": severity,
                    "exposure": exposure
                })

    # Fallback: use context["risks"] if DataFrames not available
    else:
        for risk in context.get("risks", []):
            risk_id = risk.get("id", "Unknown")
            exposure = risk.get("exposure_millions", 0.0)

            # Use ImpactLevel and LikelihoodLevel if available
            impact = risk.get("impact_level", risk.get("severity", "Medium"))
            likelihood = risk.get("likelihood_level", "Medium")

            if impact not in impact_levels:
                impact = "Medium"
            if likelihood not in likelihood_levels:
                likelihood = "Medium"

            cell_key = f"{impact}_{likelihood}"
            matrix[cell_key]["count"] += 1
            matrix[cell_key]["exposure_millions"] += exposure
            matrix[cell_key]["risk_ids"].append(risk_id)
            matrix[cell_key]["risk_details"].append({
                "id": risk_id,
                "title": risk.get("title", "Unknown"),
                "severity": risk.get("severity", "Medium"),
                "exposure": exposure
            })

    # Round exposure values
    for cell in matrix.values():
        cell["exposure_millions"] = round(cell["exposure_millions"], 1)

    return {
        "cells": matrix,
        "impact_levels": impact_levels,
        "likelihood_levels": likelihood_levels
    }


def build_stakeholder_quadrants(context: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build stakeholder landscape quadrants (Influence × Attitude) from real CSV data.

    Classifies stakeholders using actual Influence (High/Medium/Low) and Attitude
    (Champion/Advocate/Neutral/Blocker) columns from security_stakeholders.csv.

    Quadrant mapping:
    - High Influence + Champion/Advocate → Champions/Sponsors (top-right)
    - High Influence + Blocker/Neutral → Blockers/Skeptics (top-left)
    - Medium/Low Influence + Champion/Advocate → Advocates/Helpers (bottom-right)
    - Medium/Low Influence + Blocker/Neutral → Observers/Detractors (bottom-left)

    Args:
        context: Full cyber context with stakeholders_raw and cyber_data_frames

    Returns:
        Dict with 4 quadrant keys, each containing list of stakeholder dicts
    """
    quadrants = {
        "high_influence_supportive": [],    # Champions, Sponsors
        "high_influence_resistant": [],     # Blockers, Skeptics
        "low_influence_supportive": [],     # Advocates, Helpers
        "low_influence_resistant": []       # Observers, Detractors
    }

    # Use DataFrame for accurate mapping if available
    if "cyber_data_frames" in context:
        stakeholder_df = context["cyber_data_frames"].get("security_stakeholders")

        if stakeholder_df is not None and not stakeholder_df.empty:
            for _, row in stakeholder_df.iterrows():
                name = row.get("Name", "Unknown")
                role = row.get("Role", "Unknown")
                function = row.get("Function", "")
                influence_raw = str(row.get("Influence", "Medium")).strip()
                attitude_raw = str(row.get("Attitude", "Neutral")).strip()
                notes = row.get("Notes", "")

                # Normalize influence (case-insensitive)
                influence = influence_raw.lower()
                # Normalize attitude (case-insensitive)
                attitude = attitude_raw.lower()

                # Determine quadrant and tag based on CSV values
                is_high_influence = (influence == "high")
                is_supportive = (attitude in ["champion", "advocate"])
                is_resistant = (attitude in ["blocker", "skeptic"])

                if is_high_influence and is_supportive:
                    tag = "Champion" if attitude == "champion" else "Sponsor"
                    quadrant_key = "high_influence_supportive"
                elif is_high_influence and is_resistant:
                    tag = "Blocker"
                    quadrant_key = "high_influence_resistant"
                elif is_high_influence:  # Neutral high influence
                    tag = "Sponsor"
                    quadrant_key = "high_influence_supportive"
                elif is_supportive:  # Medium/Low influence supportive
                    tag = "Advocate"
                    quadrant_key = "low_influence_supportive"
                elif is_resistant:  # Medium/Low influence resistant
                    tag = "Observer"
                    quadrant_key = "low_influence_resistant"
                else:  # Medium/Low influence neutral
                    tag = "Observer"
                    quadrant_key = "low_influence_supportive"

                quadrants[quadrant_key].append({
                    "name": name,
                    "role": role,
                    "function": function,
                    "tag": tag,
                    "influence": influence_raw,
                    "attitude": attitude_raw,
                    "notes": notes
                })

    # Fallback: use context["stakeholders_raw"] if DataFrames not available
    else:
        for stakeholder in context.get("stakeholders_raw", []):
            name = stakeholder.get("name", "Unknown")
            role = stakeholder.get("role", "Unknown")
            influence = stakeholder.get("influence", "low").lower()
            attitude = stakeholder.get("attitude", "neutral").lower()

            # Determine tag based on influence + attitude combo
            if influence == "high" and attitude in ["champion", "advocate"]:
                tag = "Champion"
                quadrant_key = "high_influence_supportive"
            elif influence == "high" and attitude in ["blocker", "skeptic", "resistant"]:
                tag = "Blocker"
                quadrant_key = "high_influence_resistant"
            elif influence in ["medium", "low"] and attitude in ["champion", "advocate"]:
                tag = "Advocate"
                quadrant_key = "low_influence_supportive"
            elif influence in ["medium", "low"] and attitude in ["blocker", "skeptic", "resistant"]:
                tag = "Observer"
                quadrant_key = "low_influence_resistant"
            else:
                # Neutral attitude: classify by influence only
                if influence == "high":
                    tag = "Sponsor"
                    quadrant_key = "high_influence_supportive"
                else:
                    tag = "Observer"
                    quadrant_key = "low_influence_supportive"

            quadrants[quadrant_key].append({
                "name": name,
                "role": role,
                "tag": tag,
                "influence": influence,
                "attitude": attitude
            })

    return quadrants


def calculate_cyber_ebitda_impact(context: Dict[str, Any], sla_breaches: List,
                                   control_gaps: List, overdue_tasks: List) -> Dict[str, Any]:
    """
    Calculate modeled EBITDA impact from cybersecurity risks.

    Estimates financial exposure across multiple categories:
    - Regulatory/compliance penalties (fines, contract penalties, SOC2 suspension)
    - Revenue at risk (downtime, customer churn, API breaches, SSO outages)
    - Operational drag (firefighting incidents, emergency patching, forensics)
    - Remediation investment (short-term capex/opex to close gaps)
    - Residual risk (post-mitigation exposure that remains)

    Args:
        context: Full cyber context with risks, incidents, vulnerabilities, controls
        sla_breaches: List of SLA-breached vulnerabilities
        control_gaps: List of control gaps
        overdue_tasks: List of overdue program tasks

    Returns:
        Dict with EBITDA components and waterfall values for charting
    """

    # === 1. Pull Financial Data from Risks ===
    # security_financials.csv has: revenue_at_risk, regulatory_penalty, operational_cost, reputational_impact
    total_revenue_risk = sum(r.get("revenue_at_risk_millions", 0.0) for r in context["risks"])
    total_regulatory_penalty = sum(r.get("regulatory_penalty_millions", 0.0) for r in context["risks"])
    total_operational_cost = sum(r.get("operational_cost_millions", 0.0) for r in context["risks"])
    total_reputational_impact = sum(r.get("reputational_impact_millions", 0.0) for r in context["risks"])

    # === 2. Calculate Remediation Investment ===
    # Estimate cost to remediate based on backlog, SLA breaches, control gaps, critical incidents

    # Cost per remediation item (industry estimates):
    # - Overdue task: $150K avg (project management + dev time + testing)
    # - SLA-breached CVE: $80K avg (emergency patching + regression testing + deployment)
    # - Control gap: $200K avg (new tooling + process redesign + audit)
    # - Critical incident: $250K avg (forensics + containment + remediation + compliance reporting)

    remediation_overdue_tasks = len(overdue_tasks) * 0.15  # $150K per task
    remediation_sla_breaches = len(sla_breaches) * 0.08   # $80K per CVE
    remediation_control_gaps = len(control_gaps) * 0.20   # $200K per gap
    remediation_critical_incidents = len([i for i in context["incidents"]
                                          if i["severity"] == "Critical" and i["status"] == "Open"]) * 0.25  # $250K per incident

    total_remediation_investment = (
        remediation_overdue_tasks +
        remediation_sla_breaches +
        remediation_control_gaps +
        remediation_critical_incidents
    )

    # === 3. Calculate Gross Exposure ===
    # Sum of all negative impacts before any remediation
    gross_exposure = (
        total_revenue_risk +
        total_regulatory_penalty +
        total_operational_cost +
        total_reputational_impact
    )

    # === 4. Calculate Residual Risk ===
    # Assume remediation investment reduces risk by 70%, leaving 30% residual exposure
    # This accounts for risks that cannot be fully eliminated (e.g., zero-day exploits, APT campaigns)
    residual_risk_pct = 0.30
    residual_risk = gross_exposure * residual_risk_pct

    # === 5. Calculate Total EBITDA Impact ===
    # Total impact = gross exposure + remediation investment - (exposure eliminated by remediation)
    # Simplified: gross exposure + remediation investment, with residual risk as footnote
    total_ebitda_impact = gross_exposure + total_remediation_investment

    # === 6. Attribution by Security Domain ===
    # Break down exposure by control area for CFO drill-down
    risk_attribution = {}
    for risk in context["risks"]:
        domain = risk.get("domain", "Other")
        exposure = risk.get("exposure_millions", 0.0)
        if domain not in risk_attribution:
            risk_attribution[domain] = 0.0
        risk_attribution[domain] += exposure

    # Round all values
    risk_attribution = {k: round(v, 1) for k, v in risk_attribution.items()}

    # === 7. Build Waterfall Components ===
    # Waterfall shows: Baseline → Negative impacts → Positive mitigations → Final

    # Baseline EBITDA (fictional company baseline before cyber risk)
    # For demo purposes, assume a $100M baseline EBITDA
    baseline_ebitda = 100.0

    # Waterfall bars (in order):
    waterfall_components = [
        {"label": "Baseline EBITDA", "value": baseline_ebitda, "type": "baseline"},
        {"label": "Regulatory Penalties", "value": -total_regulatory_penalty, "type": "negative"},
        {"label": "Revenue at Risk", "value": -total_revenue_risk, "type": "negative"},
        {"label": "Operational Drag", "value": -total_operational_cost, "type": "negative"},
        {"label": "Reputational Impact", "value": -total_reputational_impact, "type": "negative"},
        {"label": "Remediation Investment", "value": -total_remediation_investment, "type": "investment"},
        {"label": "Risk-Adjusted EBITDA", "value": baseline_ebitda - total_ebitda_impact, "type": "final"}
    ]

    # === 8. Build Attribution Bullets ===
    # Tie specific risks/domains to each waterfall bar
    attribution_bullets = {
        "regulatory_penalties": [
            f"GDPR/CCPA fines from S3 exposure (SR-003): ${context['risks'][2].get('regulatory_penalty_millions', 0.0)}M" if len(context['risks']) > 2 else "GDPR/CCPA fines",
            f"SOC2 suspension risk (SR-008): ${context['risks'][7].get('regulatory_penalty_millions', 0.0)}M" if len(context['risks']) > 7 else "SOC2 compliance gaps",
            f"PCI-DSS penalties from API breach (SR-006): ${context['risks'][5].get('regulatory_penalty_millions', 0.0)}M" if len(context['risks']) > 5 else "PCI-DSS violations"
        ],
        "revenue_at_risk": [
            f"Okta SSO downtime (SR-001): ${context['risks'][0].get('revenue_at_risk_millions', 0.0)}M/day" if context['risks'] else "SSO outages",
            f"Customer churn from API breach (SR-006): ${context['risks'][5].get('revenue_at_risk_millions', 0.0)}M ARR" if len(context['risks']) > 5 else "API security",
            f"Insider data exfiltration (SR-002): ${context['risks'][1].get('revenue_at_risk_millions', 0.0)}M liability" if len(context['risks']) > 1 else "Data breaches"
        ],
        "operational_drag": [
            f"Emergency patching + forensics: ${total_operational_cost:.1f}M",
            f"Incident response for {len([i for i in context['incidents'] if i['severity'] in ['Critical', 'High']])} high-severity incidents",
            f"Extended MTTR due to SOC staffing gaps"
        ],
        "remediation_investment": [
            f"Close {len(control_gaps)} control gaps: ${remediation_control_gaps:.1f}M",
            f"Patch {len(sla_breaches)} SLA-breached CVEs: ${remediation_sla_breaches:.1f}M",
            f"Complete {len(overdue_tasks)} overdue security tasks: ${remediation_overdue_tasks:.1f}M"
        ]
    }

    return {
        "baseline_ebitda_millions": round(baseline_ebitda, 1),
        "revenue_risk_millions": round(total_revenue_risk, 1),
        "compliance_penalties_millions": round(total_regulatory_penalty, 1),
        "operational_drag_millions": round(total_operational_cost, 1),
        "reputational_impact_millions": round(total_reputational_impact, 1),
        "remediation_investment_millions": round(total_remediation_investment, 1),
        "gross_exposure_millions": round(gross_exposure, 1),
        "residual_risk_millions": round(residual_risk, 1),
        "total_impact_millions": round(total_ebitda_impact, 1),
        "risk_adjusted_ebitda_millions": round(baseline_ebitda - total_ebitda_impact, 1),
        "risk_attribution": risk_attribution,
        "waterfall_components": waterfall_components,
        "attribution_bullets": attribution_bullets
    }


def compute_cyber_ebitda(cyber_data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """
    Compute enterprise-level EBITDA impact from cybersecurity risks using real CSV data.

    This function provides granular financial modeling with 6 components:
    1. Regulatory Penalties - GDPR, SOC2, PCI-DSS fines
    2. Downtime Cost - Revenue loss from system outages
    3. Fraud Risk - Financial loss from data breaches
    4. Operational Drag (OpEx) - Incident response and firefighting costs
    5. Remediation Investment - CapEx/OpEx to close gaps
    6. Residual Risk - Post-mitigation exposure

    Args:
        cyber_data: Dictionary of pandas DataFrames from CSV sources
                   Expected keys: security_risk_register, security_financials,
                   security_incidents, security_controls, security_program_tasks,
                   vulnerability_findings

    Returns:
        Dictionary with EBITDA impact breakdown, waterfall data, top risk drivers,
        and 7-day investment recommendations
    """
    import numpy as np
    from datetime import datetime, timedelta

    # Baseline EBITDA (fictional company baseline before cyber risk)
    # For demo purposes, use $100M baseline
    baseline_ebitda = 100.0

    # Initialize components
    regulatory_penalties = 0.0
    downtime_cost = 0.0
    fraud_risk = 0.0
    opex_drag = 0.0
    remediation_investment = 0.0
    residual_risk = 0.0

    # Risk attribution tracking
    top_risk_drivers = []

    # ========================================================================
    # 1. REGULATORY PENALTIES
    # ========================================================================
    if "security_financials" in cyber_data:
        financials_df = cyber_data["security_financials"]

        if not financials_df.empty and "RegulatoryPenaltyMillions" in financials_df.columns:
            regulatory_penalties = financials_df["RegulatoryPenaltyMillions"].sum()

            # Track top regulatory risks
            if "security_risk_register" in cyber_data:
                risk_df = cyber_data["security_risk_register"]
                merged = risk_df.merge(financials_df, on="RiskID", how="left")

                top_regulatory = merged.nlargest(3, "RegulatoryPenaltyMillions")[
                    ["RiskID", "Title", "RegulatoryPenaltyMillions", "Severity"]
                ]

                for _, row in top_regulatory.iterrows():
                    top_risk_drivers.append({
                        "risk_id": row["RiskID"],
                        "title": row["Title"],
                        "category": "Regulatory Penalty",
                        "impact_millions": round(row["RegulatoryPenaltyMillions"], 1),
                        "severity": row["Severity"]
                    })

    # ========================================================================
    # 2. DOWNTIME COST (Revenue at Risk)
    # ========================================================================
    if "security_financials" in cyber_data:
        financials_df = cyber_data["security_financials"]

        if not financials_df.empty and "RevenueAtRiskMillions" in financials_df.columns:
            downtime_cost = financials_df["RevenueAtRiskMillions"].sum()

            # Track top downtime risks
            if "security_risk_register" in cyber_data:
                risk_df = cyber_data["security_risk_register"]
                merged = risk_df.merge(financials_df, on="RiskID", how="left")

                top_downtime = merged.nlargest(3, "RevenueAtRiskMillions")[
                    ["RiskID", "Title", "RevenueAtRiskMillions", "Severity"]
                ]

                for _, row in top_downtime.iterrows():
                    if {"risk_id": row["RiskID"]} not in [{"risk_id": r["risk_id"]} for r in top_risk_drivers]:
                        top_risk_drivers.append({
                            "risk_id": row["RiskID"],
                            "title": row["Title"],
                            "category": "Downtime Cost",
                            "impact_millions": round(row["RevenueAtRiskMillions"], 1),
                            "severity": row["Severity"]
                        })

    # ========================================================================
    # 3. FRAUD RISK (Data Breach / Reputational Impact)
    # ========================================================================
    if "security_financials" in cyber_data:
        financials_df = cyber_data["security_financials"]

        if not financials_df.empty and "ReputationalImpactMillions" in financials_df.columns:
            fraud_risk = financials_df["ReputationalImpactMillions"].sum()

            # Track top fraud/data breach risks
            if "security_risk_register" in cyber_data:
                risk_df = cyber_data["security_risk_register"]
                merged = risk_df.merge(financials_df, on="RiskID", how="left")

                top_fraud = merged.nlargest(3, "ReputationalImpactMillions")[
                    ["RiskID", "Title", "ReputationalImpactMillions", "Severity"]
                ]

                for _, row in top_fraud.iterrows():
                    if {"risk_id": row["RiskID"]} not in [{"risk_id": r["risk_id"]} for r in top_risk_drivers]:
                        top_risk_drivers.append({
                            "risk_id": row["RiskID"],
                            "title": row["Title"],
                            "category": "Fraud/Data Breach",
                            "impact_millions": round(row["ReputationalImpactMillions"], 1),
                            "severity": row["Severity"]
                        })

    # ========================================================================
    # 4. OPERATIONAL DRAG (Incident Response OpEx)
    # ========================================================================
    if "security_financials" in cyber_data:
        financials_df = cyber_data["security_financials"]

        if not financials_df.empty and "OperationalCostMillions" in financials_df.columns:
            opex_drag = financials_df["OperationalCostMillions"].sum()

    # Add incident-specific operational costs
    if "security_incidents" in cyber_data:
        incident_df = cyber_data["security_incidents"]

        if not incident_df.empty and "Severity" in incident_df.columns:
            # Cost per incident (industry averages):
            # Critical: $250K, High: $100K, Medium: $30K, Low: $10K
            cost_map = {"Critical": 0.25, "High": 0.10, "Medium": 0.03, "Low": 0.01}

            incident_costs = incident_df["Severity"].map(cost_map).sum()
            opex_drag += incident_costs

    # ========================================================================
    # 5. REMEDIATION INVESTMENT (Short-term CapEx/OpEx)
    # ========================================================================
    # Cost to close control gaps, patch CVEs, complete overdue tasks

    # A. Control gaps remediation
    control_gap_cost = 0.0
    if "security_controls" in cyber_data:
        controls_df = cyber_data["security_controls"]

        if not controls_df.empty and "MaturityScore" in controls_df.columns:
            # Controls below 60% maturity considered gaps
            control_gaps = len(controls_df[controls_df["MaturityScore"] < 60])
            control_gap_cost = control_gaps * 0.20  # $200K per control gap

    # B. Vulnerability remediation
    vuln_remediation_cost = 0.0
    if "vulnerability_findings" in cyber_data:
        vuln_df = cyber_data["vulnerability_findings"]

        if not vuln_df.empty and "Severity" in vuln_df.columns:
            # Critical CVEs: $80K each, High: $40K, Medium: $15K
            critical_vulns = len(vuln_df[vuln_df["Severity"] == "Critical"])
            high_vulns = len(vuln_df[vuln_df["Severity"] == "High"])
            medium_vulns = len(vuln_df[vuln_df["Severity"] == "Medium"])

            vuln_remediation_cost = (critical_vulns * 0.08) + (high_vulns * 0.04) + (medium_vulns * 0.015)

    # C. Overdue task completion
    task_completion_cost = 0.0
    if "security_program_tasks" in cyber_data:
        tasks_df = cyber_data["security_program_tasks"]

        if not tasks_df.empty and "Status" in tasks_df.columns:
            # Overdue tasks (status != Completed)
            overdue_tasks = len(tasks_df[tasks_df["Status"] != "Completed"])
            task_completion_cost = overdue_tasks * 0.15  # $150K per task

    remediation_investment = control_gap_cost + vuln_remediation_cost + task_completion_cost

    # ========================================================================
    # 6. RESIDUAL RISK (Post-Mitigation Exposure)
    # ========================================================================
    # Assume remediation eliminates 70% of risk, leaving 30% residual
    gross_exposure = regulatory_penalties + downtime_cost + fraud_risk + opex_drag
    residual_risk = gross_exposure * 0.30  # 30% residual after remediation

    # ========================================================================
    # 7. CALCULATE TOTALS
    # ========================================================================
    total_impact = (regulatory_penalties + downtime_cost + fraud_risk +
                    opex_drag + remediation_investment)
    risk_adjusted_ebitda = baseline_ebitda - total_impact

    # ========================================================================
    # 8. BUILD WATERFALL COMPONENTS
    # ========================================================================
    waterfall_components = [
        {"label": "Baseline EBITDA", "value": baseline_ebitda, "type": "baseline"},
        {"label": "Regulatory Penalties", "value": -regulatory_penalties, "type": "negative"},
        {"label": "Downtime Cost", "value": -downtime_cost, "type": "negative"},
        {"label": "Fraud Risk", "value": -fraud_risk, "type": "negative"},
        {"label": "OpEx Drag", "value": -opex_drag, "type": "negative"},
        {"label": "Remediation Investment", "value": -remediation_investment, "type": "investment"},
        {"label": "Risk-Adjusted EBITDA", "value": risk_adjusted_ebitda, "type": "final"}
    ]

    # ========================================================================
    # 9. TOP 3 FINANCIAL RISK DRIVERS (with RiskIDs)
    # ========================================================================
    # Sort by impact and take top 3
    top_risk_drivers = sorted(top_risk_drivers, key=lambda x: x["impact_millions"], reverse=True)[:3]

    # ========================================================================
    # 10. 7-DAY INVESTMENT RECOMMENDATIONS
    # ========================================================================
    recommendations_7day = []

    # Rec 1: Address highest-impact risk
    if top_risk_drivers:
        highest_risk = top_risk_drivers[0]
        recommendations_7day.append({
            "priority": 1,
            "action": f"Mitigate {highest_risk['risk_id']}: {highest_risk['title']}",
            "rationale": f"Highest financial exposure (${highest_risk['impact_millions']}M)",
            "owner": "CISO",
            "timeline": "Days 1-7"
        })

    # Rec 2: Close critical control gaps
    if control_gap_cost > 0:
        recommendations_7day.append({
            "priority": 2,
            "action": f"Close {int(control_gap_cost / 0.20)} critical control gaps",
            "rationale": f"Reduces remediation investment by ${control_gap_cost:.1f}M",
            "owner": "Security Engineering",
            "timeline": "Days 1-14"
        })

    # Rec 3: Patch critical CVEs
    if vuln_remediation_cost > 0 and "vulnerability_findings" in cyber_data:
        vuln_df = cyber_data["vulnerability_findings"]
        critical_count = len(vuln_df[vuln_df["Severity"] == "Critical"]) if not vuln_df.empty else 0
        if critical_count > 0:
            recommendations_7day.append({
                "priority": 3,
                "action": f"Emergency patch {critical_count} critical CVEs",
                "rationale": "Prevents SLA breaches and reduces attack surface",
                "owner": "Vulnerability Management",
                "timeline": "Days 1-7"
            })

    # ========================================================================
    # 11. RETURN COMPREHENSIVE EBITDA BREAKDOWN
    # ========================================================================
    return {
        # Core components (6 categories)
        "baseline_ebitda_millions": round(baseline_ebitda, 1),
        "regulatory_penalties_millions": round(regulatory_penalties, 1),
        "downtime_cost_millions": round(downtime_cost, 1),
        "fraud_risk_millions": round(fraud_risk, 1),
        "opex_drag_millions": round(opex_drag, 1),
        "remediation_investment_millions": round(remediation_investment, 1),
        "residual_risk_millions": round(residual_risk, 1),

        # Aggregates
        "gross_cyber_exposure_millions": round(gross_exposure, 1),
        "total_impact_millions": round(total_impact, 1),
        "risk_adjusted_ebitda_millions": round(risk_adjusted_ebitda, 1),

        # Waterfall chart data
        "waterfall_components": waterfall_components,

        # Top 3 risk drivers with RiskIDs
        "top_risk_drivers": top_risk_drivers,

        # 7-day recommendations
        "recommendations_7day": recommendations_7day,

        # Breakdown for drill-down
        "remediation_breakdown": {
            "control_gaps_cost_millions": round(control_gap_cost, 1),
            "vuln_remediation_cost_millions": round(vuln_remediation_cost, 1),
            "task_completion_cost_millions": round(task_completion_cost, 1)
        },

        # Metadata
        "computed_at": datetime.now().isoformat(),
        "reduction_from_baseline_pct": round((total_impact / baseline_ebitda) * 100, 1)
    }


def compute_cyber_kpis(cyber_data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """
    Compute comprehensive cybersecurity KPIs from raw DataFrames.

    This function calculates REAL metrics from CSV data rather than using generic text.
    All calculations are DataFrame-based for accuracy and transparency.

    Args:
        cyber_data: Dictionary of pandas DataFrames keyed by source name
                   Expected keys: security_risk_register, security_financials,
                   vulnerability_findings, security_incidents, security_controls,
                   security_program_tasks, security_stakeholders, compliance_status,
                   security_metrics, threat_intel, security_exec_updates

    Returns:
        Dictionary of KPI categories with computed metrics
    """
    import numpy as np
    from datetime import datetime, timedelta

    kpis = {
        "risk_kpis": {},
        "incident_kpis": {},
        "vulnerability_kpis": {},
        "control_compliance_kpis": {},
        "program_governance_kpis": {},
        "computed_at": datetime.now().isoformat()
    }

    today = pd.Timestamp.now()

    # ========================================================================
    # A. RISK KPIs
    # ========================================================================
    if "security_risk_register" in cyber_data and "security_financials" in cyber_data:
        risk_df = cyber_data["security_risk_register"]
        financials_df = cyber_data["security_financials"]

        # Total cyber risks by severity
        if not risk_df.empty and "Severity" in risk_df.columns:
            severity_counts = risk_df["Severity"].value_counts().to_dict()
            kpis["risk_kpis"]["by_severity"] = severity_counts
            kpis["risk_kpis"]["total_risks"] = len(risk_df)

        # Total financial exposure
        if not financials_df.empty and "ExposureMillions" in financials_df.columns:
            total_exposure = financials_df["ExposureMillions"].sum()
            kpis["risk_kpis"]["total_exposure_millions"] = round(total_exposure, 1)

            # Breakdown by category
            if "RevenueAtRiskMillions" in financials_df.columns:
                kpis["risk_kpis"]["revenue_at_risk_millions"] = round(financials_df["RevenueAtRiskMillions"].sum(), 1)
            if "RegulatoryPenaltyMillions" in financials_df.columns:
                kpis["risk_kpis"]["regulatory_penalty_millions"] = round(financials_df["RegulatoryPenaltyMillions"].sum(), 1)
            if "OperationalCostMillions" in financials_df.columns:
                kpis["risk_kpis"]["operational_cost_millions"] = round(financials_df["OperationalCostMillions"].sum(), 1)
            if "ReputationalImpactMillions" in financials_df.columns:
                kpis["risk_kpis"]["reputational_impact_millions"] = round(financials_df["ReputationalImpactMillions"].sum(), 1)

        # Overdue risks (TargetDate < today)
        if not risk_df.empty and "TargetDate" in risk_df.columns:
            risk_df["TargetDate_parsed"] = pd.to_datetime(risk_df["TargetDate"], format="%m/%d/%y", errors='coerce')
            overdue_risks = risk_df[risk_df["TargetDate_parsed"] < today]
            kpis["risk_kpis"]["overdue_count"] = len(overdue_risks)
            if len(overdue_risks) > 0:
                kpis["risk_kpis"]["overdue_risk_ids"] = overdue_risks["RiskID"].tolist()

        # Status distribution
        if not risk_df.empty and "Status" in risk_df.columns:
            status_counts = risk_df["Status"].value_counts().to_dict()
            kpis["risk_kpis"]["by_status"] = status_counts

    # ========================================================================
    # B. INCIDENT KPIs
    # ========================================================================
    if "security_incidents" in cyber_data:
        incident_df = cyber_data["security_incidents"]

        if not incident_df.empty:
            # Incident counts by severity
            if "Severity" in incident_df.columns:
                severity_counts = incident_df["Severity"].value_counts().to_dict()
                kpis["incident_kpis"]["by_severity"] = severity_counts
                kpis["incident_kpis"]["total_incidents"] = len(incident_df)

            # MTTD (Mean Time to Detect) - calculated from DetectedAt - IncidentStart if available
            # For this dataset, we don't have IncidentStart, so we'll use a proxy or skip
            # Let's calculate from available time_to_detect_hours if it exists
            if "MTTR_Hours" in incident_df.columns:
                # MTTR = mean(ResolvedAt - DetectedAt) - this is already in MTTR_Hours column
                avg_mttr = incident_df["MTTR_Hours"].mean()
                kpis["incident_kpis"]["mttr_hours"] = round(avg_mttr, 1)

                # MTTR by severity
                mttr_by_severity = incident_df.groupby("Severity")["MTTR_Hours"].mean().to_dict()
                kpis["incident_kpis"]["mttr_by_severity"] = {k: round(v, 1) for k, v in mttr_by_severity.items()}

            # Count of currently open incidents
            if "Status" in incident_df.columns:
                open_incidents = incident_df[incident_df["Status"].str.lower().isin(["open", "investigating", "in progress"])]
                kpis["incident_kpis"]["open_count"] = len(open_incidents)

                if len(open_incidents) > 0 and "IncidentID" in incident_df.columns:
                    kpis["incident_kpis"]["open_incident_ids"] = open_incidents["IncidentID"].tolist()

            # Data exfiltration incidents
            if "DataExfiltrated" in incident_df.columns:
                exfiltration_count = incident_df[incident_df["DataExfiltrated"].str.lower() != "no"].shape[0]
                kpis["incident_kpis"]["data_exfiltration_count"] = exfiltration_count

    # ========================================================================
    # C. VULNERABILITY KPIs
    # ========================================================================
    if "vulnerability_findings" in cyber_data:
        vuln_df = cyber_data["vulnerability_findings"]

        if not vuln_df.empty:
            # Count of Critical findings with DaysOpen > 30
            if "Severity" in vuln_df.columns and "DaysOpen" in vuln_df.columns:
                critical_old = vuln_df[(vuln_df["Severity"] == "Critical") & (vuln_df["DaysOpen"] > 30)]
                kpis["vulnerability_kpis"]["critical_over_30days"] = len(critical_old)

            # SLA breach rate
            if "SLAStatus" in vuln_df.columns:
                total_vulns = len(vuln_df)
                sla_breaches = vuln_df[vuln_df["SLAStatus"] == "BREACH"]
                breach_count = len(sla_breaches)
                breach_rate = (breach_count / total_vulns * 100) if total_vulns > 0 else 0
                kpis["vulnerability_kpis"]["sla_breach_count"] = breach_count
                kpis["vulnerability_kpis"]["sla_breach_rate_pct"] = round(breach_rate, 1)
                kpis["vulnerability_kpis"]["sla_compliance_rate_pct"] = round(100 - breach_rate, 1)

            # Distribution of vulnerabilities by severity
            if "Severity" in vuln_df.columns:
                severity_counts = vuln_df["Severity"].value_counts().to_dict()
                kpis["vulnerability_kpis"]["by_severity"] = severity_counts
                kpis["vulnerability_kpis"]["total_vulnerabilities"] = len(vuln_df)

            # Open vulnerabilities
            if "Status" in vuln_df.columns:
                open_vulns = vuln_df[vuln_df["Status"] == "Open"]
                kpis["vulnerability_kpis"]["open_count"] = len(open_vulns)

            # Vulnerabilities with active exploits
            if "ExploitInWild" in vuln_df.columns:
                active_exploits = vuln_df[vuln_df["ExploitInWild"].str.lower() == "yes"]
                kpis["vulnerability_kpis"]["active_exploit_count"] = len(active_exploits)

            # Average CVSS score
            if "CVSS" in vuln_df.columns:
                avg_cvss = vuln_df["CVSS"].mean()
                kpis["vulnerability_kpis"]["avg_cvss_score"] = round(avg_cvss, 2)

            # Average days open
            if "DaysOpen" in vuln_df.columns:
                avg_days = vuln_df["DaysOpen"].mean()
                kpis["vulnerability_kpis"]["avg_days_open"] = round(avg_days, 1)

    # ========================================================================
    # D. CONTROL/COMPLIANCE KPIs
    # ========================================================================
    if "security_controls" in cyber_data:
        control_df = cyber_data["security_controls"]

        if not control_df.empty and "MaturityScore" in control_df.columns:
            # Controls categorized as Healthy (>=85%), At Risk (60-84%), Failing (<60%)
            healthy = control_df[control_df["MaturityScore"] >= 85]
            at_risk = control_df[(control_df["MaturityScore"] >= 60) & (control_df["MaturityScore"] < 85)]
            failing = control_df[control_df["MaturityScore"] < 60]

            kpis["control_compliance_kpis"]["healthy_count"] = len(healthy)
            kpis["control_compliance_kpis"]["at_risk_count"] = len(at_risk)
            kpis["control_compliance_kpis"]["failing_count"] = len(failing)
            kpis["control_compliance_kpis"]["total_controls"] = len(control_df)

            # Average maturity score
            avg_maturity = control_df["MaturityScore"].mean()
            kpis["control_compliance_kpis"]["avg_maturity_pct"] = round(avg_maturity, 1)

            # Control gaps
            if "GapFlag" in control_df.columns:
                gaps = control_df[control_df["GapFlag"].str.lower() == "yes"]
                kpis["control_compliance_kpis"]["gap_count"] = len(gaps)

            # Maturity by CISSP domain
            if "CISPDomain" in control_df.columns:
                domain_maturity = control_df.groupby("CISPDomain")["MaturityScore"].agg(["mean", "count"]).to_dict()
                kpis["control_compliance_kpis"]["by_cissp_domain"] = {
                    domain: {
                        "avg_maturity": round(domain_maturity["mean"][domain], 1),
                        "control_count": int(domain_maturity["count"][domain])
                    }
                    for domain in domain_maturity["mean"].keys()
                }

                # Domains with largest gaps (lowest maturity)
                domain_avg = control_df.groupby("CISPDomain")["MaturityScore"].mean().sort_values()
                top_gap_domains = domain_avg.head(3).to_dict()
                kpis["control_compliance_kpis"]["top_gap_domains"] = {
                    k: round(v, 1) for k, v in top_gap_domains.items()
                }

    # Compliance scores from compliance_status
    if "compliance_status" in cyber_data:
        compliance_df = cyber_data["compliance_status"]

        if not compliance_df.empty:
            # Overall compliance score (% of passing controls across all frameworks)
            if "Compliant" in compliance_df.columns and "ControlCount" in compliance_df.columns:
                total_controls = compliance_df["ControlCount"].sum()
                total_compliant = compliance_df["Compliant"].sum()
                compliance_pct = (total_compliant / total_controls * 100) if total_controls > 0 else 0
                kpis["control_compliance_kpis"]["overall_compliance_pct"] = round(compliance_pct, 1)

            # Compliance by framework
            if "Framework" in compliance_df.columns:
                framework_compliance = compliance_df.groupby("Framework").agg({
                    "Compliant": "sum",
                    "NonCompliant": "sum",
                    "ControlCount": "sum",
                    "MaturityScore": "mean"
                }).to_dict()

                framework_summary = {}
                for framework in framework_compliance["Compliant"].keys():
                    total = framework_compliance["ControlCount"][framework]
                    compliant = framework_compliance["Compliant"][framework]
                    compliance_pct = (compliant / total * 100) if total > 0 else 0
                    framework_summary[framework] = {
                        "compliance_pct": round(compliance_pct, 1),
                        "compliant_count": int(compliant),
                        "total_count": int(total),
                        "maturity_score": round(framework_compliance["MaturityScore"][framework], 1)
                    }

                kpis["control_compliance_kpis"]["by_framework"] = framework_summary

    # ========================================================================
    # E. PROGRAM & GOVERNANCE KPIs
    # ========================================================================
    if "security_program_tasks" in cyber_data:
        task_df = cyber_data["security_program_tasks"]

        if not task_df.empty:
            total_tasks = len(task_df)

            # % tasks overdue
            if "Status" in task_df.columns:
                overdue_tasks = task_df[task_df["Status"] == "Overdue"]
                overdue_count = len(overdue_tasks)
                overdue_pct = (overdue_count / total_tasks * 100) if total_tasks > 0 else 0
                kpis["program_governance_kpis"]["overdue_count"] = overdue_count
                kpis["program_governance_kpis"]["overdue_pct"] = round(overdue_pct, 1)

                # Task status distribution
                status_counts = task_df["Status"].value_counts().to_dict()
                kpis["program_governance_kpis"]["by_status"] = status_counts

            kpis["program_governance_kpis"]["total_tasks"] = total_tasks

            # Top 3 blocking tasks (by DaysOverdue or BlockedBy)
            if "BlockedBy" in task_df.columns:
                blocked_tasks = task_df[task_df["BlockedBy"].notna() & (task_df["BlockedBy"] != "None")]
                kpis["program_governance_kpis"]["blocked_count"] = len(blocked_tasks)

                if len(blocked_tasks) > 0 and "Title" in task_df.columns and "DaysOverdue" in task_df.columns:
                    # Sort by DaysOverdue descending
                    top_blocked = blocked_tasks.nlargest(3, "DaysOverdue")[["TaskID", "Title", "BlockedBy", "DaysOverdue"]]
                    kpis["program_governance_kpis"]["top_blocked_tasks"] = top_blocked.to_dict('records')

    # Stakeholder sentiment from security_exec_updates
    if "security_exec_updates" in cyber_data:
        updates_df = cyber_data["security_exec_updates"]

        if not updates_df.empty and "Sentiment" in updates_df.columns:
            sentiment_counts = updates_df["Sentiment"].value_counts().to_dict()
            total_updates = len(updates_df)

            kpis["program_governance_kpis"]["stakeholder_sentiment"] = {
                "positive_count": sentiment_counts.get("Positive", 0),
                "neutral_count": sentiment_counts.get("Neutral", 0),
                "negative_count": sentiment_counts.get("Negative", 0),
                "positive_pct": round((sentiment_counts.get("Positive", 0) / total_updates * 100), 1) if total_updates > 0 else 0,
                "neutral_pct": round((sentiment_counts.get("Neutral", 0) / total_updates * 100), 1) if total_updates > 0 else 0,
                "negative_pct": round((sentiment_counts.get("Negative", 0) / total_updates * 100), 1) if total_updates > 0 else 0
            }

    # Security metrics trends (from security_metrics.csv)
    if "security_metrics" in cyber_data:
        metrics_df = cyber_data["security_metrics"]

        if not metrics_df.empty:
            # Get latest week
            if "week_start" in metrics_df.columns:
                latest_week = metrics_df.iloc[-1]

                # Extract key metrics from latest week
                metric_fields = [
                    "critical_vulns_open", "high_vulns_open", "mean_time_to_patch_days",
                    "sla_breach_count", "incidents_detected", "incidents_resolved",
                    "mean_time_to_resolve_hours", "controls_effective_pct",
                    "compliance_score_pct", "security_debt_count"
                ]

                kpis["program_governance_kpis"]["latest_metrics"] = {}
                for field in metric_fields:
                    if field in metrics_df.columns:
                        kpis["program_governance_kpis"]["latest_metrics"][field] = float(latest_week[field])

                # Trend analysis (last 4 weeks)
                if len(metrics_df) >= 4:
                    recent_4weeks = metrics_df.tail(4)

                    # Calculate trends
                    if "security_debt_count" in metrics_df.columns:
                        debt_trend = recent_4weeks["security_debt_count"].tolist()
                        debt_change = debt_trend[-1] - debt_trend[0]
                        debt_change_pct = (debt_change / debt_trend[0] * 100) if debt_trend[0] > 0 else 0
                        kpis["program_governance_kpis"]["security_debt_trend"] = {
                            "values": [int(x) for x in debt_trend],
                            "change": int(debt_change),
                            "change_pct": round(debt_change_pct, 1)
                        }

                    if "mean_time_to_patch_days" in metrics_df.columns:
                        mttp_trend = recent_4weeks["mean_time_to_patch_days"].tolist()
                        kpis["program_governance_kpis"]["mttp_trend"] = {
                            "values": [round(x, 1) for x in mttp_trend],
                            "current": round(mttp_trend[-1], 1)
                        }

    return kpis


def build_cyber_kpis(context: Dict[str, Any], sla_breaches: List, control_gaps: List, overdue_tasks: List) -> List[Dict[str, Any]]:
    """
    Build executive KPI tiles for Cyber PMO dashboard.

    Generates 6 KPI tiles with label, value, and subtext for display in the KPI strip.

    Args:
        context: Full cyber context with vulnerabilities, incidents, controls, metrics
        sla_breaches: List of SLA-breached vulnerabilities
        control_gaps: List of control gaps
        overdue_tasks: List of overdue program tasks

    Returns:
        List of KPI dicts with keys: label, value, subtext, severity
    """
    kpis = []

    # KPI 1: Critical Vulnerabilities Open
    critical_vulns_open = len([v for v in context["vulnerabilities"] if v["severity"] == "Critical" and v["status"] == "Open"])
    critical_sla_breach = len([v for v in sla_breaches if v["severity"] == "Critical"])
    kpis.append({
        "label": "Critical Vulns Open",
        "value": str(critical_vulns_open),
        "subtext": f"{critical_sla_breach} in SLA breach",
        "severity": "critical" if critical_sla_breach > 0 else "warning"
    })

    # KPI 2: Mean Time to Detect (MTTD) - from most recent metrics
    if context["security_metrics"]:
        latest_metrics = context["security_metrics"][-1]  # Most recent week
        # Calculate average detection time from incidents
        incidents_with_detection = [i for i in context["incidents"] if i.get("time_to_detect_hours", 0) > 0]
        if incidents_with_detection:
            avg_mttd_hours = sum(i["time_to_detect_hours"] for i in incidents_with_detection) / len(incidents_with_detection)
            mttd_value = f"{avg_mttd_hours:.1f}h"
            mttd_subtext = "avg detection time"
        else:
            mttd_value = "N/A"
            mttd_subtext = "no incidents tracked"
    else:
        mttd_value = "N/A"
        mttd_subtext = "no metrics available"

    kpis.append({
        "label": "Mean Time to Detect",
        "value": mttd_value,
        "subtext": mttd_subtext,
        "severity": "info"
    })

    # KPI 3: Mean Time to Respond (MTTR)
    if context["security_metrics"]:
        latest_metrics = context["security_metrics"][-1]
        mttr_hours = float(latest_metrics.get("mean_time_to_resolve_hours", 0))
        mttr_target = 24  # Target: < 24 hours for high severity

        kpis.append({
            "label": "Mean Time to Respond",
            "value": f"{mttr_hours:.1f}h",
            "subtext": f"Target: <{mttr_target}h" if mttr_hours <= mttr_target else f"⚠️ {mttr_hours - mttr_target:.1f}h over target",
            "severity": "ok" if mttr_hours <= mttr_target else "warning"
        })
    else:
        kpis.append({
            "label": "Mean Time to Respond",
            "value": "N/A",
            "subtext": "no metrics available",
            "severity": "info"
        })

    # KPI 4: High-Severity Incidents Open
    high_severity_incidents_open = len([i for i in context["incidents"] if i["severity"] in ["Critical", "High"] and i["status"] == "Open"])
    kpis.append({
        "label": "High-Severity Incidents",
        "value": str(high_severity_incidents_open),
        "subtext": "open (Critical + High)",
        "severity": "critical" if high_severity_incidents_open > 2 else "ok"
    })

    # KPI 5: Patch Aging (> 30 days)
    vulns_over_30_days = len([v for v in context["vulnerabilities"] if int(v.get("DaysOpen", 0)) > 30])
    vulns_over_90_days = len([v for v in context["vulnerabilities"] if int(v.get("DaysOpen", 0)) > 90])
    kpis.append({
        "label": "Patch Aging > 30 Days",
        "value": str(vulns_over_30_days),
        "subtext": f"{vulns_over_90_days} over 90 days",
        "severity": "warning" if vulns_over_30_days > 5 else "ok"
    })

    # KPI 6: Control Health Percentage
    total_controls = len(context["controls"])
    if total_controls > 0:
        # Controls are "healthy" if maturity >= 85% and no gaps
        healthy_controls = len([c for c in context["controls"] if float(c.get("MaturityScore", 0)) >= 85 and c.get("HasGap") == "No"])
        control_health_pct = (healthy_controls / total_controls) * 100

        kpis.append({
            "label": "Control Health",
            "value": f"{control_health_pct:.0f}%",
            "subtext": f"{healthy_controls}/{total_controls} controls healthy",
            "severity": "ok" if control_health_pct >= 70 else "warning"
        })
    else:
        kpis.append({
            "label": "Control Health",
            "value": "N/A",
            "subtext": "no controls tracked",
            "severity": "info"
        })

    return kpis


def build_cyber_risk_program_context(config: Dict[str, Any], scenario: str) -> Dict[str, Any]:
    """
    Build structured context for Day 3 Cyber PMO scenario.

    Transforms raw CSV data into analyzed, structured cybersecurity program context with:
    - Security risks (merged with financials)
    - Vulnerability findings with SLA breach analysis
    - Security incidents with MTTR tracking
    - Control effectiveness gaps
    - Security program task backlog
    - Threat intelligence correlation
    - Stakeholder influence mapping
    - Compliance posture

    Args:
        config: Application configuration
        scenario: Scenario name (e.g., 'sentient_cyber_pmo')

    Returns:
        Structured context dict ready for cybersecurity analytics
    """
    print(f"\n🔬 Building structured cybersecurity context for scenario: {scenario}...")

    # Load scenario configuration
    scenario_config = config.get("scenarios", {}).get(scenario)
    if not scenario_config:
        raise ValueError(f"Scenario '{scenario}' not found in config")

    data_sources = scenario_config.get("data_sources", {})
    scenario_title = scenario_config.get("title", scenario)
    analytics_config = scenario_config.get("analytics", {})

    # Initialize context structure
    context = {
        "scenario": scenario,
        "scenario_title": scenario_title,
        "risks": [],
        "vulnerabilities": [],
        "incidents": [],
        "controls": [],
        "program_tasks": [],
        "stakeholders_raw": [],
        "threat_intel": [],
        "compliance_status": [],
        "security_metrics": [],
        "exec_updates": [],
        # Computed analytics
        "top_risks": [],
        "control_gaps": [],
        "security_debt": {},
        "incident_patterns": [],
        "vuln_hotspots": [],
        "stakeholder_map": {},
        "program_backlog": {},
        "ebitda_impact_components": {},
        # Raw DataFrames for advanced analytics
        "cyber_data_frames": {}
    }

    # Helper function to load CSV data with DataFrame storage and validation
    def load_csv_data_with_df(source_key: str, required_columns: List[str] = None) -> tuple[List[Dict[str, Any]], pd.DataFrame]:
        """
        Load CSV data using pandas, validate structure, and return both dict list and DataFrame.

        Args:
            source_key: Key for data source in config
            required_columns: List of required column names for validation

        Returns:
            Tuple of (list of row dicts, pandas DataFrame)
        """
        source_config = data_sources.get(source_key, {})
        if not source_config.get("enabled", False):
            return [], pd.DataFrame()

        path = source_config.get("path", "")
        if not path:
            print(f"  ✗ No path configured for {source_key}")
            return [], pd.DataFrame()

        try:
            # Load with pandas for better validation
            # Use quotechar and escapechar to handle CSVs with commas in quoted fields
            df = pd.read_csv(path, quotechar='"', escapechar='\\', on_bad_lines='warn')

            # Validate required columns
            if required_columns:
                missing_cols = [col for col in required_columns if col not in df.columns]
                if missing_cols:
                    print(f"  ⚠ Missing columns in {source_key}: {missing_cols}")

            # Convert to list of dicts
            rows = df.to_dict('records')
            print(f"  ✓ Loaded {source_key}: {len(rows)} records")

            # Store DataFrame in context
            context["cyber_data_frames"][source_key] = df

            return rows, df
        except FileNotFoundError:
            print(f"  ✗ File not found for {source_key}: {path}")
            return [], pd.DataFrame()
        except pd.errors.ParserError as e:
            print(f"  ✗ CSV parsing error for {source_key}: {e}")
            print(f"     Try checking for malformed rows or unescaped commas in: {path}")
            return [], pd.DataFrame()
        except Exception as e:
            print(f"  ✗ Failed to load {source_key}: {e}")
            return [], pd.DataFrame()

    # Legacy helper for compatibility with old load pattern
    def load_csv_data(source_key: str) -> List[Dict[str, Any]]:
        """Load CSV data using CSVIngestor (legacy method)."""
        rows, _ = load_csv_data_with_df(source_key)
        return rows

    # Helper for safe numeric conversion
    def safe_float(value, default=0.0):
        try:
            return float(value) if value else default
        except (ValueError, TypeError):
            return default

    def safe_int(value, default=0):
        try:
            return int(value) if value else default
        except (ValueError, TypeError):
            return default

    # === 1. Load Security Risk Register & Financials ===
    print("\n  📋 Loading security risks and financials...")
    risk_register_rows, risk_register_df = load_csv_data_with_df(
        "security_risk_register",
        required_columns=["RiskID", "Title", "Domain", "Severity", "Owner", "Status"]
    )
    risk_financials_rows, risk_financials_df = load_csv_data_with_df(
        "security_financials",
        required_columns=["RiskID", "ExposureMillions"]
    )

    # Validate and convert numeric columns in financials DataFrame
    if not risk_financials_df.empty:
        numeric_cols = ["ExposureMillions", "RevenueAtRiskMillions", "RegulatoryPenaltyMillions",
                       "OperationalCostMillions", "ReputationalImpactMillions"]
        for col in numeric_cols:
            if col in risk_financials_df.columns:
                risk_financials_df[col] = pd.to_numeric(risk_financials_df[col], errors='coerce').fillna(0.0)

    # Create lookup for financials
    financials_by_risk_id = {
        row.get("RiskID"): row for row in risk_financials_rows
    }

    # Merge risks with financials
    for risk_row in risk_register_rows:
        risk_id = risk_row.get("RiskID", "")
        financial_data = financials_by_risk_id.get(risk_id, {})

        exposure_millions = safe_float(financial_data.get("ExposureMillions"))

        merged_risk = {
            "id": risk_id,
            "title": risk_row.get("Title", ""),
            "domain": risk_row.get("Domain", ""),
            "severity": risk_row.get("Severity", ""),
            "impact_level": risk_row.get("ImpactLevel", ""),
            "likelihood_level": risk_row.get("LikelihoodLevel", ""),
            "strategy": risk_row.get("Strategy", ""),
            "plan": risk_row.get("Plan", ""),
            "owner": risk_row.get("Owner", ""),
            "target_date": risk_row.get("TargetDate", ""),
            "control_area": risk_row.get("ControlArea", ""),
            "status": risk_row.get("Status", ""),
            "exposure_millions": exposure_millions,
            "total_exposure": exposure_millions * 1_000_000,
            "revenue_at_risk_millions": safe_float(financial_data.get("RevenueAtRiskMillions")),
            "regulatory_penalty_millions": safe_float(financial_data.get("RegulatoryPenaltyMillions")),
            "operational_cost_millions": safe_float(financial_data.get("OperationalCostMillions")),
            "reputational_impact_millions": safe_float(financial_data.get("ReputationalImpactMillions")),
            "financial_notes": financial_data.get("notes", "")
        }

        context["risks"].append(merged_risk)

    print(f"    ✓ Merged {len(context['risks'])} security risks with financials")

    # === 2. Load Vulnerabilities & Compute SLA Breaches ===
    print("\n  🔍 Loading vulnerabilities and analyzing SLA compliance...")
    vuln_rows, vuln_df = load_csv_data_with_df(
        "vulnerability_findings",
        required_columns=["FindingID", "Asset", "CVE", "CVSS", "Severity", "Status", "DaysOpen"]
    )

    # Validate and convert numeric/date columns in vulnerabilities DataFrame
    if not vuln_df.empty:
        # Convert numeric columns
        if "CVSS" in vuln_df.columns:
            vuln_df["CVSS"] = pd.to_numeric(vuln_df["CVSS"], errors='coerce').fillna(0.0)
        if "DaysOpen" in vuln_df.columns:
            vuln_df["DaysOpen"] = pd.to_numeric(vuln_df["DaysOpen"], errors='coerce').fillna(0).astype(int)

    vuln_config = analytics_config.get("vulnerability", {})
    sla_critical_days = vuln_config.get("sla_critical_days", 7)
    sla_high_days = vuln_config.get("sla_high_days", 30)
    sla_medium_days = vuln_config.get("sla_medium_days", 90)

    sla_breaches = []
    for vuln_row in vuln_rows:
        severity = vuln_row.get("Severity", "")
        days_open = safe_int(vuln_row.get("DaysOpen"))
        sla_status = vuln_row.get("SLAStatus", "")

        # Determine if SLA is breached
        is_breach = False
        if severity == "Critical" and days_open > sla_critical_days:
            is_breach = True
        elif severity == "High" and days_open > sla_high_days:
            is_breach = True
        elif severity == "Medium" and days_open > sla_medium_days:
            is_breach = True

        vuln_dict = {
            "finding_id": vuln_row.get("FindingID", ""),
            "asset": vuln_row.get("Asset", ""),
            "cve": vuln_row.get("CVE", ""),
            "cvss": safe_float(vuln_row.get("CVSS")),
            "severity": severity,
            "status": vuln_row.get("Status", ""),
            "sla_status": sla_status,
            "owner": vuln_row.get("Owner", ""),
            "days_open": days_open,
            "patch_available": vuln_row.get("PatchAvailable", ""),
            "exploit_in_wild": vuln_row.get("ExploitInWild", ""),
            "is_sla_breach": is_breach
        }

        context["vulnerabilities"].append(vuln_dict)

        if is_breach or sla_status == "BREACH":
            sla_breaches.append(vuln_dict)

    print(f"    ✓ Loaded {len(context['vulnerabilities'])} vulnerabilities")
    print(f"    ⚠ Identified {len(sla_breaches)} SLA breaches")

    # === 3. Load Security Incidents & Compute MTTR Stats ===
    print("\n  🚨 Loading security incidents and analyzing MTTR...")
    incident_rows, incident_df = load_csv_data_with_df(
        "security_incidents",
        required_columns=["IncidentID", "Type", "Severity", "Status", "MTTR_Hours"]
    )

    # Validate and convert numeric/date columns in incidents DataFrame
    if not incident_df.empty:
        # Convert numeric columns
        if "MTTR_Hours" in incident_df.columns:
            incident_df["MTTR_Hours"] = pd.to_numeric(incident_df["MTTR_Hours"], errors='coerce').fillna(0.0)
        # Convert date columns
        date_cols = ["DetectedAt", "ResolvedAt"]
        for col in date_cols:
            if col in incident_df.columns:
                incident_df[col] = pd.to_datetime(incident_df[col], errors='coerce')

    incident_config = analytics_config.get("incident", {})
    critical_mttr_target = incident_config.get("critical_mttr_hours", 4)
    high_mttr_target = incident_config.get("high_mttr_hours", 24)

    for incident_row in incident_rows:
        severity = incident_row.get("Severity", "")
        mttr_hours = safe_float(incident_row.get("MTTR_Hours"))

        # Check if MTTR exceeds target
        mttr_exceeded = False
        if severity == "Critical" and mttr_hours > critical_mttr_target:
            mttr_exceeded = True
        elif severity == "High" and mttr_hours > high_mttr_target:
            mttr_exceeded = True

        incident_dict = {
            "incident_id": incident_row.get("IncidentID", ""),
            "type": incident_row.get("Type", ""),
            "severity": severity,
            "system": incident_row.get("System", ""),
            "detected_at": incident_row.get("DetectedAt", ""),
            "resolved_at": incident_row.get("ResolvedAt", ""),
            "mttr_hours": mttr_hours,
            "root_cause": incident_row.get("RootCause", ""),
            "status": incident_row.get("Status", ""),
            "impacted_users": incident_row.get("ImpactedUsers", ""),
            "data_exfiltrated": incident_row.get("DataExfiltrated", ""),
            "mttr_exceeded": mttr_exceeded
        }

        context["incidents"].append(incident_dict)

    print(f"    ✓ Loaded {len(context['incidents'])} security incidents")

    # === 4. Load Security Controls & Identify Gaps ===
    print("\n  🛡️ Loading security controls and identifying gaps...")
    control_rows, control_df = load_csv_data_with_df(
        "security_controls",
        required_columns=["ControlID", "CISPDomain", "ControlName", "MaturityScore", "Status"]
    )

    # Validate and convert numeric columns in controls DataFrame
    if not control_df.empty:
        if "MaturityScore" in control_df.columns:
            control_df["MaturityScore"] = pd.to_numeric(control_df["MaturityScore"], errors='coerce').fillna(0).astype(int)
        # Convert date columns
        if "LastAuditDate" in control_df.columns:
            control_df["LastAuditDate"] = pd.to_datetime(control_df["LastAuditDate"], errors='coerce')

    control_config = analytics_config.get("control_effectiveness", {})
    mature_threshold = control_config.get("mature_threshold", 85)
    developing_threshold = control_config.get("developing_threshold", 60)
    baseline_threshold = control_config.get("baseline_threshold", 40)

    control_gaps = []
    for control_row in control_rows:
        maturity_score = safe_int(control_row.get("MaturityScore"))
        gap_flag = control_row.get("GapFlag", "").lower() == "yes"

        # Classify maturity
        if maturity_score >= mature_threshold:
            maturity_label = "Mature"
        elif maturity_score >= developing_threshold:
            maturity_label = "Developing"
        elif maturity_score >= baseline_threshold:
            maturity_label = "Baseline"
        else:
            maturity_label = "Immature"

        control_dict = {
            "control_id": control_row.get("ControlID", ""),
            "cissp_domain": control_row.get("CISPDomain", ""),
            "control_name": control_row.get("ControlName", ""),
            "maturity_score": maturity_score,
            "maturity_label": maturity_label,
            "status": control_row.get("Status", ""),
            "last_audit_date": control_row.get("LastAuditDate", ""),
            "owner": control_row.get("Owner", ""),
            "gap_flag": gap_flag,
            "remediation_plan": control_row.get("RemediationPlan", "")
        }

        context["controls"].append(control_dict)

        if gap_flag:
            control_gaps.append(control_dict)

    context["control_gaps"] = control_gaps
    print(f"    ✓ Loaded {len(context['controls'])} security controls")
    print(f"    ⚠ Identified {len(control_gaps)} control gaps")

    # === 5. Load Program Tasks & Compute Backlog ===
    print("\n  📊 Loading security program tasks and computing backlog...")
    task_rows, task_df = load_csv_data_with_df(
        "security_program_tasks",
        required_columns=["TaskID", "Title", "Priority", "Owner", "Status"]
    )

    # Validate and convert numeric/date columns in tasks DataFrame
    if not task_df.empty:
        if "DaysOverdue" in task_df.columns:
            task_df["DaysOverdue"] = pd.to_numeric(task_df["DaysOverdue"], errors='coerce').fillna(0).astype(int)
        if "CompletionPct" in task_df.columns:
            task_df["CompletionPct"] = pd.to_numeric(task_df["CompletionPct"], errors='coerce').fillna(0).astype(int)
        if "DueDate" in task_df.columns:
            task_df["DueDate"] = pd.to_datetime(task_df["DueDate"], errors='coerce')

    overdue_tasks = []
    at_risk_tasks = []
    blocked_tasks = []

    for task_row in task_rows:
        status = task_row.get("Status", "")
        days_overdue = safe_int(task_row.get("DaysOverdue"))
        blocked_by = task_row.get("BlockedBy", "")

        task_dict = {
            "task_id": task_row.get("TaskID", ""),
            "workstream": task_row.get("Workstream", ""),
            "title": task_row.get("Title", ""),
            "priority": task_row.get("Priority", ""),
            "owner": task_row.get("Owner", ""),
            "status": status,
            "due_date": task_row.get("DueDate", ""),
            "days_overdue": days_overdue,
            "blocked_by": blocked_by,
            "completion_pct": safe_int(task_row.get("CompletionPct"))
        }

        context["program_tasks"].append(task_dict)

        if status == "Overdue":
            overdue_tasks.append(task_dict)
        elif status == "At Risk":
            at_risk_tasks.append(task_dict)

        if blocked_by and str(blocked_by).lower() not in ["none", "nan", ""]:
            blocked_tasks.append(task_dict)

    context["program_backlog"] = {
        "total_tasks": len(context["program_tasks"]),
        "overdue_count": len(overdue_tasks),
        "at_risk_count": len(at_risk_tasks),
        "blocked_count": len(blocked_tasks),
        "overdue_tasks": overdue_tasks,
        "at_risk_tasks": at_risk_tasks,
        "blocked_tasks": blocked_tasks
    }

    print(f"    ✓ Loaded {len(context['program_tasks'])} program tasks")
    print(f"    ⚠ Backlog: {len(overdue_tasks)} overdue, {len(at_risk_tasks)} at-risk, {len(blocked_tasks)} blocked")

    # === 6. Load Stakeholders & Build Influence Map ===
    print("\n  👥 Loading stakeholders and building influence map...")
    stakeholder_rows, stakeholder_df = load_csv_data_with_df(
        "security_stakeholders",
        required_columns=["StakeholderID", "Name", "Role", "Influence", "Attitude"]
    )

    champions = []
    blockers = []
    advocates = []
    observers = []

    for stakeholder_row in stakeholder_rows:
        influence = stakeholder_row.get("Influence", "").lower()
        attitude = stakeholder_row.get("Attitude", "").lower()

        stakeholder_dict = {
            "id": stakeholder_row.get("StakeholderID", ""),
            "name": stakeholder_row.get("Name", ""),
            "role": stakeholder_row.get("Role", ""),
            "function": stakeholder_row.get("Function", ""),
            "influence": influence,
            "attitude": attitude,
            "engagement_plan": stakeholder_row.get("EngagementPlan", ""),
            "notes": stakeholder_row.get("Notes", "")
        }

        context["stakeholders_raw"].append(stakeholder_dict)

        # Quadrant mapping
        if influence == "high" and attitude == "champion":
            champions.append(stakeholder_dict)
        elif influence == "high" and attitude == "blocker":
            blockers.append(stakeholder_dict)
        elif attitude in ["advocate", "champion"]:
            advocates.append(stakeholder_dict)
        else:
            observers.append(stakeholder_dict)

    context["stakeholder_map"] = {
        "champions": champions,
        "blockers": blockers,
        "advocates": advocates,
        "observers": observers
    }

    print(f"    ✓ Loaded {len(context['stakeholders_raw'])} stakeholders")
    print(f"    └─ Champions: {len(champions)}, Blockers: {len(blockers)}, Advocates: {len(advocates)}, Observers: {len(observers)}")

    # === 7. Load Threat Intelligence ===
    threat_intel_rows, threat_intel_df = load_csv_data_with_df(
        "threat_intel",
        required_columns=["ThreatID", "ThreatActor", "Campaign", "Severity"]
    )
    context["threat_intel"] = threat_intel_rows

    # Validate and convert date columns in threat intel DataFrame
    if not threat_intel_df.empty:
        date_cols = ["FirstSeen", "LastSeen"]
        for col in date_cols:
            if col in threat_intel_df.columns:
                threat_intel_df[col] = pd.to_datetime(threat_intel_df[col], errors='coerce')

    # === 8. Load Compliance Status ===
    compliance_rows, compliance_df = load_csv_data_with_df(
        "compliance_status",
        required_columns=["FrameworkID", "Framework", "Domain"]
    )
    context["compliance_status"] = compliance_rows

    # Validate and convert numeric/date columns in compliance DataFrame
    if not compliance_df.empty:
        numeric_cols = ["ControlCount", "Compliant", "NonCompliant", "InProgress", "MaturityScore"]
        for col in numeric_cols:
            if col in compliance_df.columns:
                compliance_df[col] = pd.to_numeric(compliance_df[col], errors='coerce').fillna(0).astype(int)
        if "LastAuditDate" in compliance_df.columns:
            compliance_df["LastAuditDate"] = pd.to_datetime(compliance_df["LastAuditDate"], errors='coerce')
        if "NextAuditDate" in compliance_df.columns:
            compliance_df["NextAuditDate"] = pd.to_datetime(compliance_df["NextAuditDate"], errors='coerce')

    # === 9. Load Security Metrics (Weekly Trends) ===
    metrics_rows, metrics_df = load_csv_data_with_df(
        "security_metrics",
        required_columns=["week_start"]
    )
    context["security_metrics"] = metrics_rows

    # Validate and convert numeric/date columns in metrics DataFrame
    if not metrics_df.empty:
        if "week_start" in metrics_df.columns:
            metrics_df["week_start"] = pd.to_datetime(metrics_df["week_start"], errors='coerce')
        # Convert all numeric metric columns
        numeric_cols = ["critical_vulns_open", "high_vulns_open", "mean_time_to_patch_days",
                       "sla_breach_count", "incidents_detected", "incidents_resolved",
                       "mean_time_to_resolve_hours", "phishing_simulations_sent",
                       "phishing_click_rate_pct", "controls_effective_pct",
                       "compliance_score_pct", "security_debt_count"]
        for col in numeric_cols:
            if col in metrics_df.columns:
                metrics_df[col] = pd.to_numeric(metrics_df[col], errors='coerce').fillna(0)

    # === 10. Load Executive Updates ===
    exec_updates_rows, exec_updates_df = load_csv_data_with_df(
        "security_exec_updates"
    )
    context["exec_updates"] = exec_updates_rows

    # Validate and convert date columns in exec updates DataFrame
    if not exec_updates_df.empty:
        if "Date" in exec_updates_df.columns:
            exec_updates_df["Date"] = pd.to_datetime(exec_updates_df["Date"], errors='coerce')

    # === 11. Compute Security Debt ===
    print("\n  📈 Computing security debt metrics...")

    debt_config = analytics_config.get("security_debt", {})
    critical_backlog_threshold = debt_config.get("critical_backlog", 50)
    high_backlog_threshold = debt_config.get("high_backlog", 100)

    # Count open critical/high vulnerabilities
    critical_vulns = [v for v in context["vulnerabilities"] if v["severity"] == "Critical" and v["status"] == "Open"]
    high_vulns = [v for v in context["vulnerabilities"] if v["severity"] == "High" and v["status"] == "Open"]

    # Total debt score: critical vulns + high vulns + overdue tasks + control gaps
    debt_score = len(critical_vulns) + len(high_vulns) + len(overdue_tasks) + len(control_gaps)

    if debt_score > high_backlog_threshold:
        debt_level = "High"
    elif debt_score > critical_backlog_threshold:
        debt_level = "Elevated"
    else:
        debt_level = "Moderate"

    context["security_debt"] = {
        "total_score": debt_score,
        "level": debt_level,
        "critical_vulns_open": len(critical_vulns),
        "high_vulns_open": len(high_vulns),
        "overdue_tasks": len(overdue_tasks),
        "control_gaps": len(control_gaps),
        "sla_breaches": len(sla_breaches)
    }

    print(f"    ✓ Security debt score: {debt_score} ({debt_level})")

    # === 12. Identify Incident Patterns ===
    print("\n  🔎 Analyzing incident patterns...")

    incident_types = {}
    for incident in context["incidents"]:
        inc_type = incident["type"]
        if inc_type not in incident_types:
            incident_types[inc_type] = []
        incident_types[inc_type].append(incident)

    # Find recurring patterns (types with 2+ incidents)
    patterns = []
    for inc_type, incidents in incident_types.items():
        if len(incidents) >= 2:
            patterns.append({
                "type": inc_type,
                "count": len(incidents),
                "severity_distribution": {
                    "Critical": len([i for i in incidents if i["severity"] == "Critical"]),
                    "High": len([i for i in incidents if i["severity"] == "High"]),
                    "Medium": len([i for i in incidents if i["severity"] == "Medium"])
                }
            })

    context["incident_patterns"] = sorted(patterns, key=lambda x: x["count"], reverse=True)
    print(f"    ✓ Identified {len(patterns)} recurring incident patterns")

    # === 13. Identify Vulnerability Hotspots ===
    print("\n  🎯 Identifying vulnerability hotspots...")

    asset_vulns = {}
    for vuln in context["vulnerabilities"]:
        asset = vuln["asset"]
        if asset not in asset_vulns:
            asset_vulns[asset] = []
        asset_vulns[asset].append(vuln)

    # Find hotspots (assets with 2+ critical/high vulns)
    hotspots = []
    for asset, vulns in asset_vulns.items():
        critical_high = [v for v in vulns if v["severity"] in ["Critical", "High"]]
        if len(critical_high) >= 1:  # Lower threshold for demo
            hotspots.append({
                "asset": asset,
                "total_vulns": len(vulns),
                "critical_count": len([v for v in vulns if v["severity"] == "Critical"]),
                "high_count": len([v for v in vulns if v["severity"] == "High"]),
                "sla_breaches": len([v for v in vulns if v["is_sla_breach"]])
            })

    context["vuln_hotspots"] = sorted(hotspots, key=lambda x: x["critical_count"], reverse=True)
    print(f"    ✓ Identified {len(hotspots)} vulnerability hotspots")

    # === 14. Compute EBITDA Impact Components ===
    print("\n  💰 Computing EBITDA impact breakdown with waterfall...")

    # Use old function for backward compatibility
    ebitda_impact = calculate_cyber_ebitda_impact(context, sla_breaches, control_gaps, overdue_tasks)
    context["ebitda_impact_components"] = ebitda_impact

    # Use NEW granular EBITDA function with 6 detailed components
    cyber_ebitda_detailed = compute_cyber_ebitda(context["cyber_data_frames"])
    context["cyber_ebitda_detailed"] = cyber_ebitda_detailed

    print(f"    ✓ Baseline EBITDA: ${cyber_ebitda_detailed['baseline_ebitda_millions']}M")
    print(f"    ✓ Regulatory penalties: ${cyber_ebitda_detailed['regulatory_penalties_millions']}M")
    print(f"    ✓ Downtime cost: ${cyber_ebitda_detailed['downtime_cost_millions']}M")
    print(f"    ✓ Fraud risk: ${cyber_ebitda_detailed['fraud_risk_millions']}M")
    print(f"    ✓ OpEx drag: ${cyber_ebitda_detailed['opex_drag_millions']}M")
    print(f"    ✓ Remediation investment: ${cyber_ebitda_detailed['remediation_investment_millions']}M")
    print(f"    ✓ Total EBITDA impact: ${cyber_ebitda_detailed['total_impact_millions']}M")
    print(f"    ✓ Risk-adjusted EBITDA: ${cyber_ebitda_detailed['risk_adjusted_ebitda_millions']}M")
    print(f"    ✓ Top {len(cyber_ebitda_detailed['top_risk_drivers'])} financial risk drivers identified")
    print(f"    ✓ {len(cyber_ebitda_detailed['recommendations_7day'])} high-priority recommendations generated")

    # === 15. Compute Top Risks ===
    context["top_risks"] = sorted(context["risks"], key=lambda x: x["exposure_millions"], reverse=True)[:5]

    # === 16. Generate Premium Component Data ===
    print("\n  🎨 Generating premium UI component data...")

    # Threat Cards: Convert incidents to structured threat card data
    threat_cards = []
    for incident in context["incidents"]:
        # Extract MITRE technique from tags if available
        mitre_id = ""
        tags = incident.get("tags", "")
        if "T1" in tags:  # MITRE ATT&CK techniques start with T1
            parts = tags.split(",")
            for part in parts:
                if "T1" in part:
                    mitre_id = part.strip()
                    break

        threat_cards.append({
            "type": incident["type"],
            "severity": incident["severity"].lower(),
            "mitre_id": mitre_id or "N/A",
            "time_to_detect": incident.get("time_to_detect_hours", 0),
            "time_to_contain": incident.get("time_to_resolve_hours", 0),
            "system_impacted": incident.get("affected_system", "Unknown"),
            "description": incident.get("description", ""),
            "status": incident.get("status", "Open")
        })

    context["threat_cards"] = threat_cards

    # Vulnerability Chips: CVSS severity counts
    vuln_chips = {
        "critical": len([v for v in context["vulnerabilities"] if v["severity"] == "Critical"]),
        "high": len([v for v in context["vulnerabilities"] if v["severity"] == "High"]),
        "medium": len([v for v in context["vulnerabilities"] if v["severity"] == "Medium"]),
        "low": len([v for v in context["vulnerabilities"] if v["severity"] == "Low"]),
        "sla_breach_count": len(sla_breaches)
    }
    context["vuln_chips"] = vuln_chips

    # Asset Impact Cards: Top 3 affected assets
    asset_cards = []
    for hotspot in context["vuln_hotspots"][:3]:  # Top 3
        asset_cards.append({
            "asset_name": hotspot["asset"],
            "total_vulns": hotspot["total_vulns"],
            "critical_count": hotspot["critical_count"],
            "high_count": hotspot["high_count"],
            "sla_breaches": hotspot["sla_breaches"]
        })
    context["asset_cards"] = asset_cards

    # Mitigation Timeline: Convert top risks into timeline items
    mitigation_timeline = []
    for idx, risk in enumerate(context["top_risks"][:5], 1):  # Top 5 risks
        # Parse plan for key phases
        plan = risk.get("plan", "No plan available")

        # Determine status based on target date and current status
        status = "in_progress"
        if risk["status"] == "Mitigated":
            status = "completed"
        elif risk["status"] == "Overdue":
            status = "blocked"

        mitigation_timeline.append({
            "phase": f"Phase {idx}",
            "title": risk["title"],
            "date": risk["target_date"],
            "description": plan[:150] + "..." if len(plan) > 150 else plan,
            "status": status,
            "owner": risk["owner"],
            "impact": f"${risk['exposure_millions']}M exposure"
        })

    context["mitigation_timeline"] = mitigation_timeline

    print(f"    ✓ Generated {len(threat_cards)} threat cards")
    print(f"    ✓ Generated vulnerability chips (Critical: {vuln_chips['critical']}, High: {vuln_chips['high']}, SLA Breaches: {vuln_chips['sla_breach_count']})")
    print(f"    ✓ Generated {len(asset_cards)} asset impact cards")
    print(f"    ✓ Generated {len(mitigation_timeline)} mitigation timeline items")

    # === 17. Compute Comprehensive KPIs from DataFrames ===
    print("\n  📊 Computing comprehensive KPIs from DataFrames...")
    computed_kpis = compute_cyber_kpis(context["cyber_data_frames"])
    context["computed_kpis"] = computed_kpis

    print(f"    ✓ Computed {len(computed_kpis)} KPI categories:")
    print(f"       - Risk KPIs: {len(computed_kpis.get('risk_kpis', {}))} metrics")
    print(f"       - Incident KPIs: {len(computed_kpis.get('incident_kpis', {}))} metrics")
    print(f"       - Vulnerability KPIs: {len(computed_kpis.get('vulnerability_kpis', {}))} metrics")
    print(f"       - Control/Compliance KPIs: {len(computed_kpis.get('control_compliance_kpis', {}))} metrics")
    print(f"       - Program/Governance KPIs: {len(computed_kpis.get('program_governance_kpis', {}))} metrics")

    # === 17b. Extract Domain Scores from Control/Compliance KPIs ===
    print("\n  🎯 Extracting CISSP domain scores for report...")
    domain_scores = []
    if computed_kpis.get("control_compliance_kpis", {}).get("by_cissp_domain"):
        cissp_domains = computed_kpis["control_compliance_kpis"]["by_cissp_domain"]

        for domain, metrics in cissp_domains.items():
            avg_maturity = metrics.get("avg_maturity", 0)

            # Determine status based on maturity
            if avg_maturity >= 85:
                status = "Mature"
                status_icon = "✅"
            elif avg_maturity >= 60:
                status = "Developing"
                status_icon = "⚠️"
            else:
                status = "Immature"
                status_icon = "❌"

            domain_scores.append({
                "domain": domain,
                "score": round(avg_maturity, 1),
                "status": status,
                "status_icon": status_icon,
                "control_count": metrics.get("control_count", 0)
            })

        # Sort by score (ascending) to highlight weakest domains first
        domain_scores.sort(key=lambda x: x["score"])

    context["domain_scores"] = domain_scores
    print(f"    ✓ Extracted {len(domain_scores)} CISSP domain scores")

    # === 18. Build Cyber KPIs for Dashboard Tiles ===
    print("\n  📊 Building executive KPI tiles...")
    cyber_kpis = build_cyber_kpis(context, sla_breaches, control_gaps, overdue_tasks)
    context["cyber_kpis"] = cyber_kpis

    print(f"    ✓ Generated {len(cyber_kpis)} KPI tiles")

    # === 18. Build Cyber Risk Heatmap Matrix ===
    print("\n  🗺️  Building cyber risk heatmap matrix...")
    risk_matrix = build_cyber_risk_matrix(context)
    context["cyber_risk_matrix"] = risk_matrix

    # Count total populated cells
    populated_cells = sum(1 for cell in risk_matrix["cells"].values() if cell["count"] > 0)
    print(f"    ✓ Risk matrix built: {populated_cells} cells populated with {len(context['risks'])} risks")

    # === 19. Build Stakeholder Landscape Quadrants ===
    print("\n  👥 Building stakeholder landscape quadrants...")
    stakeholder_quadrants = build_stakeholder_quadrants(context)
    context["stakeholder_quadrants"] = stakeholder_quadrants

    total_mapped = sum(len(q) for q in stakeholder_quadrants.values())
    print(f"    ✓ Stakeholder landscape: {total_mapped} stakeholders mapped across 4 quadrants")
    print(f"      └─ Champions/Sponsors: {len(stakeholder_quadrants['high_influence_supportive'])}, "
          f"Blockers: {len(stakeholder_quadrants['high_influence_resistant'])}, "
          f"Advocates: {len(stakeholder_quadrants['low_influence_supportive'])}, "
          f"Observers: {len(stakeholder_quadrants['low_influence_resistant'])}")

    # === 20. Generate Cybersecurity Visualization Charts ===
    print("\n  📊 Generating cybersecurity visualization charts...")
    chart_paths = generate_all_cyber_charts(
        context["cyber_data_frames"],
        context.get("cyber_ebitda_detailed", context.get("ebitda_impact_components"))  # Use new detailed EBITDA or fallback
    )
    context["chart_paths"] = chart_paths
    print(f"    ✓ Generated {len(chart_paths)} visualization charts")

    print(f"\n✅ Cybersecurity context built successfully:")
    print(f"   • {len(context['risks'])} security risks")
    print(f"   • {len(context['vulnerabilities'])} vulnerabilities ({len(sla_breaches)} SLA breaches)")
    print(f"   • {len(context['incidents'])} incidents")
    print(f"   • {len(context['controls'])} controls ({len(control_gaps)} gaps)")
    print(f"   • {len(context['program_tasks'])} program tasks")
    print(f"   • {len(context['stakeholders_raw'])} stakeholders")
    print(f"   • Security debt score: {debt_score} ({debt_level})")
    print(f"   • Total EBITDA impact: ${context['ebitda_impact_components']['total_impact_millions']}M\n")

    return context


def build_cyber_context(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build clean, structured CISSP-aligned context model for Cyber PMO dashboard.

    This is a convenience wrapper around build_cyber_risk_program_context() with a simplified
    signature. Use this when you only need the default 'sentient_cyber_pmo' scenario.

    The context model includes:
    - CISSP-aligned security domains (8 domains)
    - Pandas DataFrames for all CSV sources (advanced analytics)
    - Computed KPIs (security debt, EBITDA impact, risk matrix, stakeholder quadrants)
    - Auto-generated charts (10 cybersecurity visualizations)
    - Financial impact model (6-component EBITDA waterfall)

    Args:
        config: Application configuration (must include 'sentient_cyber_pmo' scenario)

    Returns:
        Structured context dict ready for dashboard rendering

    Example:
        >>> config = load_config()
        >>> cyber_context = build_cyber_context(config)
        >>> print(f"Security debt: {cyber_context['security_debt']['total_score']}")
        >>> print(f"EBITDA impact: ${cyber_context['cyber_ebitda_detailed']['total_impact_millions']}M")
    """
    return build_cyber_risk_program_context(config, "sentient_cyber_pmo")


def build_prompt(combined_data: str, config: Dict[str, Any], scenario: str = None) -> str:
    """
    Build the AI prompt based on configuration and scenario.

    Args:
        combined_data: Combined text from all sources
        config: Application configuration
        scenario: Optional scenario name (e.g., 'sentient_cx_risk_radar')

    Returns:
        Formatted prompt for the AI
    """
    # Check if this is a specific scenario
    if scenario and scenario in config.get("scenarios", {}):
        return _build_scenario_prompt(combined_data, config, scenario)

    # Default behavior: use standard report configuration
    report_config = config.get("report", {})
    sections = report_config.get("sections", [])
    stakeholders = report_config.get("stakeholders", [])

    prompt = f"""You are an elite Technical Program Manager AI assistant creating an EXECUTIVE-READY status report.

DATA SOURCES:
{combined_data}

CRITICAL INSTRUCTIONS - EXECUTIVE FORMAT:

Generate a concise, visual, narrative-driven report focused on IMPACT, RISK, and DECISIONS.

## STRUCTURE (EXACT FORMAT REQUIRED):

### 1. AT-A-GLANCE DASHBOARD
Create a markdown table with these columns: Area | Status | Key Metric | Trend
- Use status emojis: 🟢 On Track, 🟠 At Risk, 🔴 Critical
- Use trend symbols: ▲ Up, ▼ Down, ↑ Rising, ↓ Falling, ✅ Complete
- Cover 5-6 key areas (Platform, Features, Costs, People, Customer)
- After table, add one-line summary: "> Overall status summary here"

### 2. EXECUTIVE HIGHLIGHTS (MAX 3 bullets)
- Focus on BUSINESS OUTCOMES, not technical details
- Include customer impact, ROI, or business metrics
- Format: **Bold achievement** → tangible result (numbers/percentages)
- Example: "**API v2.0 migration** boosted performance +40%, cutting page-load times from 1.2s → 0.7s"

### 3. TOP RISKS & MITIGATIONS (Table Format)
Markdown table: Risk | Severity | Owner | Mitigation / ETA
- Severity: 🔴 Critical, 🟠 High, 🟡 Medium
- List 3-5 top risks only
- Mitigations must be action-oriented with dates
- Add "⚠️ Decision Needed" if exec approval required

### 4. KEY WINS (2-4 items)
- Use emoji indicators: 🚀 Launch, 🔒 Security, 📉 Reduction, ⚙️ Performance
- Format: "🚀 **Achievement** → impact (metric)"
- Keep to one line each

### 5. STAKEHOLDER PULSE (Compact Table)
Table: Function | Sentiment | Focus / Ask
- Sentiment emojis: ✅ Positive, ⚙️ Neutral, ⚠️ Concern, 🔥 Urgent
- Cover: {', '.join(stakeholders)}
- One-line focus per stakeholder

### 6. NEXT WEEK / EXECUTIVE ACTIONS
**Top 3 Priorities:**
1. Priority with date
2. Priority with date
3. Priority with date

**Decisions Needed:**
- Decision point with business impact
- Decision point with business impact

### 7. METRICS SNAPSHOT (If applicable)
Brief table or bullets with trending indicators (▲▼)

TONE GUIDELINES:
- Short, verb-first sentences
- Remove filler words ("includes", "showing", "following")
- Lead with business impact, not technical implementation
- Use "→" to show cause-effect
- Add quantitative impact where possible (time saved, cost reduced, deals enabled)
- Maximum 2-3 sentences per bullet point

AVOID:
- Long paragraphs
- Repeated phrasing
- Technical jargon without context
- Operational details that don't affect decisions

This report should enable executives to make decisions in 2 minutes of reading.
"""

    return prompt


def _build_scenario_prompt(combined_data: str, config: Dict[str, Any], scenario: str) -> str:
    """
    Build a scenario-specific prompt.

    Args:
        combined_data: Combined text from all sources
        config: Application configuration
        scenario: Scenario name

    Returns:
        Formatted prompt for the AI
    """
    scenario_config = config["scenarios"][scenario]

    if scenario == "sentient_cx_risk_radar":
        return _build_cx_risk_radar_prompt(combined_data, scenario_config)

    # Default fallback for other scenarios
    return f"""Generate a report based on the following data:\n\n{combined_data}"""


def _build_cx_risk_radar_prompt(combined_data: str, scenario_config: Dict[str, Any]) -> str:
    """
    Build the CX Risk Radar specific prompt.

    Args:
        combined_data: Combined text from all sources
        scenario_config: Scenario-specific configuration

    Returns:
        Formatted prompt for CX Risk Radar
    """
    title = scenario_config.get("title", "CX Risk Radar")
    sections = scenario_config.get("sections", [])
    prompt_focus = scenario_config.get("prompt_focus", [])

    prompt = f"""You are an elite Customer Experience Risk Analyst creating a concise executive narrative for {title}.

DATA SOURCES (Jira, Wrike, Slack, Gmail, HubSpot, Confluence, Calendar, Risk Register, Stakeholders):
{combined_data}

CRITICAL INSTRUCTIONS - CONCISE EXECUTIVE NARRATIVE:

Write a brief, scannable executive summary (under 350 words total) that synthesizes CX risk posture across all data sources.

STRUCTURE:

Opening paragraph (2-3 sentences):
- State overall CX risk posture (Green/Yellow/Red) and why
- Mention highest-severity item driving that posture
- Include dollar exposure if available from risk_financials data

Sentiment & escalations paragraph (2-3 sentences):
- Current CX sentiment trend (from cx_sentiment_metrics: sentiment_index, escalation_count)
- Week-over-week change (improving/stable/declining)
- Any critical alerts from Slack/Gmail/HubSpot

Risks & stakeholders paragraph (2-3 sentences):
- Name 1-2 top risks from Risk Register (title + severity + owner + target date)
- Mention key blocker stakeholder if any (e.g., Renée Park / VP Risk & Compliance)
- Cross-team dependency or coordination issue if present

Optional bullets (maximum 3 total) for next 7 days:
• [Day range] Most urgent action → expected outcome (owner)
• [Day range] Critical decision needed → business impact (stakeholder)
• [Day range] Key milestone or gate → consequence if missed

TONE:
- Direct, executive language
- Quantify when possible (dollars, dates, percentages)
- Risk-first framing (what could go wrong, what's at stake)
- No markdown headings (###), no tables, no long lists
- Plain paragraph text + optional 3 bullets max

FOCUS AREAS (from configuration):
{chr(10).join('- ' + focus for focus in prompt_focus)}

EXAMPLES OF WHAT TO AVOID:
❌ Long bulleted lists (5+ items)
❌ Markdown tables
❌ Section headings like "## Executive Overview"
❌ Verbose explanations or background context
❌ Technical jargon without business translation

WHAT TO INCLUDE:
✅ Specific risk IDs, issue keys, stakeholder names
✅ Dollar amounts, dates, percentages
✅ Clear ownership and timelines
✅ Customer impact in business terms (revenue, churn, SLA breach)

Target length: 250-350 words. Be ruthlessly concise. Every sentence must earn its place.
"""

    return prompt


def _build_platinum_risk_prompt(risk_context: Dict[str, Any], config: Dict[str, Any], scenario: Optional[str] = None) -> str:
    """
    Build consulting-grade AI prompt from structured risk context for Platinum Day 2 CX Risk Radar.

    Generates a detailed prompt instructing the LLM to produce a 7-section executive risk report
    using ONLY plain markdown (no code fences, no HTML tags).

    Args:
        risk_context: Structured context from build_risk_context() containing:
            - scenario_title, risks (merged), cx_sentiment_trend, stakeholders_raw
            - jira_raw, wrike_raw, slack_raw, gmail_raw, hubspot_raw, confluence_raw, calendar_raw
            - exec_summary_inputs, heatmap, risk_trajectory, stakeholder_map, next_actions_seed
        config: Application configuration
        scenario: Scenario name (e.g., 'sentient_cx_risk_radar')

    Returns:
        Formatted prompt string for AI
    """
    import json

    # Safely extract data from risk_context
    scenario_title = risk_context.get("scenario_title", "Sentient CX Risk Radar")
    risks = risk_context.get("risks", [])
    cx_sentiment_trend = risk_context.get("cx_sentiment_trend", [])
    stakeholders_raw = risk_context.get("stakeholders_raw", [])

    # Raw sources
    jira_raw = risk_context.get("jira_raw", [])
    wrike_raw = risk_context.get("wrike_raw", [])
    slack_raw = risk_context.get("slack_raw", [])
    gmail_raw = risk_context.get("gmail_raw", [])
    hubspot_raw = risk_context.get("hubspot_raw", [])
    confluence_raw = risk_context.get("confluence_raw", [])
    calendar_raw = risk_context.get("calendar_raw", [])

    # Get scenario config for analytics thresholds
    scenario_config = config.get("scenarios", {}).get(scenario, {}) if scenario else {}
    analytics = scenario_config.get("analytics", {})
    cx_analytics = analytics.get("cx_sentiment", {})
    financial_analytics = analytics.get("financial", {})
    heatmap_config = analytics.get("heatmap", {})

    # Build context preview for the end of the prompt
    context_preview = {
        "scenario_title": scenario_title,
        "risks": risks,
        "cx_sentiment_trend": cx_sentiment_trend,
        "stakeholders_raw": stakeholders_raw,
        "jira_raw": jira_raw[:5] if len(jira_raw) > 5 else jira_raw,
        "wrike_raw": wrike_raw[:5] if len(wrike_raw) > 5 else wrike_raw,
        "slack_raw": slack_raw[:5] if len(slack_raw) > 5 else slack_raw,
        "gmail_raw": gmail_raw[:5] if len(gmail_raw) > 5 else gmail_raw,
        "hubspot_raw": hubspot_raw[:5] if len(hubspot_raw) > 5 else hubspot_raw,
        "confluence_raw": confluence_raw[:5] if len(confluence_raw) > 5 else confluence_raw,
        "calendar_raw": calendar_raw[:5] if len(calendar_raw) > 5 else calendar_raw,
        "analytics_thresholds": {
            "cx_sentiment_baseline": cx_analytics.get('baseline_index', 75),
            "warning_drop_pct": cx_analytics.get('warning_drop_pct', 5),
            "critical_drop_pct": cx_analytics.get('critical_drop_pct', 10),
            "financial_critical": financial_analytics.get('critical_exposure', 3000000),
            "financial_high": financial_analytics.get('high_exposure', 1000000),
            "financial_medium": financial_analytics.get('medium_exposure', 250000)
        }
    }

    # Build the prompt
    prompt = f"""You are an elite Customer Experience Risk Advisor for Aurora National Bank analyzing the {scenario_title} program.

Your task is to generate a consulting-grade executive risk assessment report from structured data sources.

---

## OUTPUT FORMAT RULES (CRITICAL - READ FIRST)

**DO NOT** wrap your answer in any code fences (no ```markdown or ``` blocks).
**DO NOT** output any raw HTML tags like <div>, <span>, <section>, or any class= attributes.
**ONLY** use plain markdown:
  - Headings: # for level-1, ## for level-2, ### for level-3
  - Paragraphs: Plain text separated by blank lines
  - Bullet lists: - or * for unordered, 1. 2. 3. for ordered
  - Tables: Use standard markdown table syntax with | and -

Your output must start immediately with the first heading and contain only markdown text.

---

## REQUIRED STRUCTURE: 7 LEVEL-1 HEADINGS (EXACT ORDER)

You MUST use these 7 headings as level-1 markdown headings (# Heading Name) in this exact order:

1. # Executive Summary
2. # CX Risk Heat Map
3. # CX Sentiment Index & Trend
4. # Top Financially Exposed Risks
5. # Risk Trajectory
6. # Stakeholder Impact
7. # Next 7-Day Action Plan

---

## SECTION 1: # Executive Summary

Write 3-5 concise bullet points that synthesize the overall CX risk posture:
  - Start with a **Risk Posture** statement (e.g., "🔴 **Elevated** – Immediate action required on 2 critical risks")
  - Highlight the **current CX Sentiment Index** and its change from baseline (use data from cx_sentiment_trend)
  - Call out the **top financial exposure** (highest total_exposure risk from risks list)
  - Summarize the **most urgent deadline** (earliest target_date among high-severity risks)
  - Mention any **critical stakeholder blockers** (from stakeholders_raw where Type=Blocker and Influence=High)

Use emoji indicators: 🔴 Critical/High, 🟡 Medium/Warning, 🟢 Low/Healthy

---

## SECTION 2: # CX Risk Heat Map

- Start with a 1–2 sentence summary of the overall risk distribution.
- Then output a single HTML table with this exact structure and class:

<table class="risk-heatmap">
  <thead>
    <tr>
      <th>Impact \\ Likelihood</th>
      <th>High</th>
      <th>Medium</th>
      <th>Low</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>High</th>
      <td class="risk-cell-critical">…</td>
      <td class="risk-cell-high">…</td>
      <td class="risk-cell-medium">…</td>
    </tr>
    <tr>
      <th>Medium</th>
      <td class="risk-cell-high">…</td>
      <td class="risk-cell-medium">…</td>
      <td class="risk-cell-low">…</td>
    </tr>
    <tr>
      <th>Low</th>
      <td class="risk-cell-medium">…</td>
      <td class="risk-cell-low">…</td>
      <td class="risk-cell-low">…</td>
    </tr>
  </tbody>
</table>

Where each cell describes either:
- the number of risks in that impact/likelihood bucket, and/or
- the approximate total exposure in that bucket (e.g., "2 risks / $3.5M").

Use only this single HTML table for the heat map section, and do not generate additional markdown tables in this section.

---

## SECTION 3: # CX Sentiment Index & Trend

Analyze the cx_sentiment_trend time-series data and report:

1. **Current State** (most recent week):
   - avg_sentiment_score (current value)
   - Baseline score (earliest week_start entry)
   - Calculate **% change** from baseline

2. **Week-over-Week (WoW) Trend**:
   - Calculate WoW % change for: avg_sentiment_score, escalations, trust_index
   - Flag any drops exceeding thresholds:
     - Warning: {cx_analytics.get('warning_drop_pct', 5)}% drop
     - Critical: {cx_analytics.get('critical_drop_pct', 10)}% drop
   - Use 🟡 for warning, 🔴 for critical

3. **Trend Table**:
   - Show last 4-5 weeks of data in a markdown table
   - Columns: Week Start | Sentiment Score | Complaints | Escalations | Trust Index | Notes
   - Include any notable observations from the "notes" field

4. **Final Assessment**:
   - 2-3 sentences summarizing whether CX health is improving, stable, or declining
   - Cite specific metrics to support your conclusion

---

## SECTION 4: # Top Financially Exposed Risks

Present the top 3-5 risks sorted by total_exposure (descending) in a **markdown table**:

| Risk ID | Title | Severity | Total Exposure | Owner | Target Date | Mitigation Plan (Brief) |
|---------|-------|----------|----------------|-------|-------------|-------------------------|
| R-001 | ... | High | $4.7M | John Doe | 2025-11-20 | Escalate to CTO, deploy hotfix |
| ... | ... | ... | ... | ... | ... | ... |

Below the table:
  - Show **Total Exposure** sum across all risks in the table
  - For each risk, write 1-2 sentences summarizing:
    - Why this risk is financially significant (cite annual_revenue_at_risk, regulatory_exposure, operational_cost_impact)
    - Current mitigation status (use "plan" field and cross-reference recent Jira/Wrike/Slack activity if available)

Financial classification thresholds (use for color coding):
  - 🔴 Critical: > ${financial_analytics.get('critical_exposure', 3000000):,.0f}
  - 🟡 High: ${financial_analytics.get('high_exposure', 1000000):,.0f} - ${financial_analytics.get('critical_exposure', 3000000):,.0f}
  - 🟢 Medium: ${financial_analytics.get('medium_exposure', 250000):,.0f} - ${financial_analytics.get('high_exposure', 1000000):,.0f}

---

## SECTION 5: # Risk Trajectory

Classify each risk into one of three trajectory categories and list them:

**🟢 Improving** (mitigation on track, owner engaged, no recent escalations):
  - List risk IDs and titles
  - For each, cite evidence from recent activity (Jira status updates, Calendar meetings scheduled, positive Slack mentions)

**🟡 Holding** (stable but requires monitoring):
  - List risk IDs and titles
  - Note any risks approaching deadlines or awaiting stakeholder decisions

**🔴 Declining** (overdue, blocked, or showing negative signals):
  - List risk IDs and titles
  - Cite specific red flags from recent data:
    - Overdue target_date
    - Jira issues marked "Blocked" or "High Priority"
    - Slack threads mentioning escalations or delays
    - Gmail emails flagging concerns

**Silent Climbers** (watch list):
  - Identify 1-2 risks that are currently Low/Medium severity but show early warning signs of escalation
  - Explain what signals triggered the watch (e.g., increasing complaint trend in CX data, stakeholder shifting from Support to Neutral)

---

## SECTION 6: # Stakeholder Impact

Analyze stakeholders using a **2×2 Influence vs Support matrix** (described in prose, not a literal grid).

Group stakeholders from stakeholders_raw into 4 quadrants:

1. **High Influence, High Support** – Champions:
   - List names, roles, and orgs
   - Recommend: "Leverage for executive sponsorship"

2. **High Influence, Low Support** – Blockers:
   - List names, roles, and orgs
   - For each, cite their EngagementPlan and recommend specific actions for next 7 days
   - Example: "Schedule 1:1 with Sarah Johnson (CFO) to address budget concerns flagged in Gmail thread"

3. **Low Influence, High Support** – Advocates:
   - List names, roles
   - Recommend: "Mobilize for grassroots support and feedback loops"

4. **Low Influence, Low Support** – Observers:
   - List names (if any)
   - Recommend: "Deprioritize unless they escalate"

**Priority Recommendation**:
  - In 2-3 sentences, explain which quadrant to focus on in the next 7 days and why
  - Prioritize based on: risk deadlines, financial exposure, and stakeholder power to unblock

---

## SECTION 7: # Next 7-Day Action Plan

Extract urgent actions from risk mitigation plans where target_date falls within the next 7 days.

Group actions into 3 time buckets:

### Days 1-2 (Immediate):
  - List actions due in next 48 hours
  - For each action:
    - **Risk ID** | **Action** | **Owner** | **Due Date**
    - Example: "R-003 | Deploy API rate limit patch | Jane Smith | 2025-11-16"

### Days 3-4 (Near-term):
  - List actions due in 3-4 days
  - Same format as above

### Days 5-7 (This Week):
  - List actions due later this week
  - Same format as above

**Action Extraction Logic**:
  - Parse the "plan" field from each risk in the risks list
  - Cross-reference with Wrike tasks, Jira issues, and Calendar meetings to identify specific deliverables
  - Prioritize by: (Financial Exposure × Severity × Deadline Proximity)

If no explicit actions are found in the data, infer logical next steps based on:
  - Risks with overdue or near-term target_dates
  - Stakeholder engagement plans flagged as urgent
  - CX sentiment escalations requiring immediate response

---

## DATA SOURCES AVAILABLE

You have access to {len(risks)} risks, {len(cx_sentiment_trend)} weeks of CX sentiment data, {len(stakeholders_raw)} stakeholders, and recent activity from:
  - Jira ({len(jira_raw)} items)
  - Wrike ({len(wrike_raw)} items)
  - Slack ({len(slack_raw)} items)
  - Gmail ({len(gmail_raw)} items)
  - HubSpot ({len(hubspot_raw)} items)
  - Confluence ({len(confluence_raw)} items)
  - Calendar ({len(calendar_raw)} items)

Analytics thresholds:
  - CX Sentiment Baseline: {cx_analytics.get('baseline_index', 75)}
  - Warning Drop: {cx_analytics.get('warning_drop_pct', 5)}% | Critical Drop: {cx_analytics.get('critical_drop_pct', 10)}%
  - Financial Critical: ${financial_analytics.get('critical_exposure', 3000000):,.0f} | High: ${financial_analytics.get('high_exposure', 1000000):,.0f} | Medium: ${financial_analytics.get('medium_exposure', 250000):,.0f}

---

## CONTEXT DATA (for your internal analysis only)

Below is the structured context in JSON format. Use this data to perform your analysis and generate the 7-section markdown report above.

**IMPORTANT: Do not print this raw context in your final answer. Only output the markdown report.**

{json.dumps(context_preview, indent=2, default=str)}

---

**Final Reminder**:
- Output ONLY plain markdown (no code fences, no HTML tags)
- Use the 7 level-1 headings in exact order
- Start immediately with "# Executive Summary"
- This is a Platinum-tier consulting deliverable for C-level executives at Aurora National Bank
- Every statement must be data-driven and cite specific evidence from the context

Generate the markdown report now.
"""

    return prompt


def summarize_with_ai(combined_data: str, config: Dict[str, Any], scenario: str = None) -> str:
    """
    Call OpenAI to generate the summary.

    Args:
        combined_data: Combined text from all sources
        config: Application configuration
        scenario: Optional scenario name

    Returns:
        AI-generated summary
    """
    prompt = build_prompt(combined_data, config, scenario)

    ai_config = config.get("ai", {})
    model = ai_config.get("model", MODEL)
    temperature = ai_config.get("temperature", 0.3)
    max_tokens = ai_config.get("max_tokens", 2000)

    print(f"\n🤖 Generating summary with {model}...")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are an expert Technical Program Manager who creates crisp, actionable executive summaries."
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return response.choices[0].message.content.strip()


def summarize_with_ai_v2(risk_context: Dict[str, Any], config: Dict[str, Any], scenario: Optional[str] = None) -> str:
    """
    Call OpenAI to generate summary from structured risk context (v2 for Platinum scenarios).

    Args:
        risk_context: Structured risk context from build_risk_context()
        config: Application configuration
        scenario: Optional scenario name

    Returns:
        AI-generated summary
    """
    # Build prompt from structured context
    prompt = _build_platinum_risk_prompt(risk_context, config, scenario)

    # Use same AI config as v1
    ai_config = config.get("ai", {})
    model = ai_config.get("model", MODEL)
    temperature = ai_config.get("temperature", 0.3)
    max_tokens = ai_config.get("max_tokens", 2000)

    print(f"\n🤖 Generating Platinum-tier risk analysis with {model}...")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a senior Customer Experience Risk Advisor for Aurora National Bank. "
                    "You create consulting-grade, board-ready executive risk assessments with McKinsey-level clarity and rigor. "
                    "Your reports inform multi-million dollar resource allocation decisions for C-level executives.\n\n"
                    "CRITICAL OUTPUT RULES:\n"
                    "• Output ONLY plain markdown (headings, paragraphs, bullet lists, tables)\n"
                    "• Do NOT emit any raw HTML tags (<div>, <span>, <section>, class=, etc.)\n"
                    "• Do NOT wrap your answer in code fences (no ```markdown or ``` blocks)\n"
                    "• Start immediately with the first markdown heading"
                )
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return response.choices[0].message.content.strip()


def summarize_cyber_program_with_ai(context: Dict[str, Any], config: Dict[str, Any], scenario: str) -> str:
    """
    Generate executive-grade cybersecurity program report from CyberRiskProgramContext.

    This function produces a CISO-level report analyzing security posture, control gaps,
    vulnerability exposure, security debt, and business impact. The output is structured
    for C-suite consumption with clear separation of facts and interpretation.

    Args:
        context: Structured cybersecurity context from build_cyber_risk_program_context()
        config: Application configuration
        scenario: Scenario name (e.g., 'sentient_cyber_pmo')

    Returns:
        AI-generated markdown report (7 sections)
    """
    print(f"\n🤖 Generating cybersecurity program analysis for {scenario}...")

    # Get scenario configuration
    scenario_config = config.get("scenarios", {}).get(scenario, {})
    scenario_title = scenario_config.get("title", "Cyber PMO Intelligence")
    prompt_focus = scenario_config.get("prompt_focus", [])
    analytics = scenario_config.get("analytics", {})

    # Extract key metrics from context for prompt
    security_debt = context.get("security_debt", {})
    program_backlog = context.get("program_backlog", {})
    ebitda_impact = context.get("ebitda_impact_components", {})
    stakeholder_map = context.get("stakeholder_map", {})

    # Serialize context to JSON for structured prompt
    import json

    # Create a condensed context summary for the prompt (avoid overwhelming the LLM)
    condensed_context = {
        "scenario_title": context.get("scenario_title"),
        "top_risks": context.get("top_risks", [])[:5],  # Top 5 risks
        "vulnerabilities_summary": {
            "total": len(context.get("vulnerabilities", [])),
            "critical_open": len([v for v in context.get("vulnerabilities", []) if v["severity"] == "Critical" and v["status"] == "Open"]),
            "high_open": len([v for v in context.get("vulnerabilities", []) if v["severity"] == "High" and v["status"] == "Open"]),
            "sla_breaches": security_debt.get("sla_breaches", 0),
            "critical_with_exploits": len([v for v in context.get("vulnerabilities", []) if v["severity"] == "Critical" and v["exploit_in_wild"] == "Yes"]),
            "sample_breaches": [v for v in context.get("vulnerabilities", []) if v.get("is_sla_breach")][:3]
        },
        "incidents_summary": {
            "total": len(context.get("incidents", [])),
            "critical": len([i for i in context.get("incidents", []) if i["severity"] == "Critical"]),
            "data_exfiltration": len([i for i in context.get("incidents", []) if i["data_exfiltrated"] not in ["No", ""]]),
            "mttr_exceeded": len([i for i in context.get("incidents", []) if i.get("mttr_exceeded")]),
            "recent_incidents": context.get("incidents", [])[-5:]  # Last 5 incidents
        },
        "control_gaps": context.get("control_gaps", []),
        "control_maturity_distribution": {
            "mature": len([c for c in context.get("controls", []) if c["maturity_label"] == "Mature"]),
            "developing": len([c for c in context.get("controls", []) if c["maturity_label"] == "Developing"]),
            "baseline": len([c for c in context.get("controls", []) if c["maturity_label"] == "Baseline"]),
            "immature": len([c for c in context.get("controls", []) if c["maturity_label"] == "Immature"])
        },
        "security_debt": security_debt,
        "program_backlog": {
            "total_tasks": program_backlog.get("total_tasks", 0),
            "overdue_count": program_backlog.get("overdue_count", 0),
            "at_risk_count": program_backlog.get("at_risk_count", 0),
            "blocked_count": program_backlog.get("blocked_count", 0),
            "overdue_tasks": program_backlog.get("overdue_tasks", []),
            "blocked_tasks": program_backlog.get("blocked_tasks", [])
        },
        "incident_patterns": context.get("incident_patterns", []),
        "vuln_hotspots": context.get("vuln_hotspots", [])[:5],
        "stakeholder_map": {
            "champions": stakeholder_map.get("champions", []),
            "blockers": stakeholder_map.get("blockers", []),
            "advocates": stakeholder_map.get("advocates", [])
        },
        "threat_intel": context.get("threat_intel", [])[:5],  # Top 5 threats
        "compliance_summary": {
            "total_frameworks": len(set([c.get("Framework", "Unknown") for c in context.get("compliance_status", []) if c.get("Framework")])),
            "critical_gaps": [c for c in context.get("compliance_status", []) if int(c.get("NonCompliant", 0)) > 2][:3]
        },
        "ebitda_impact": ebitda_impact,
        "security_metrics_trend": context.get("security_metrics", [])[-4:],  # Last 4 weeks
        "exec_updates": context.get("exec_updates", [])[-5:]  # Last 5 updates
    }

    context_json = json.dumps(condensed_context, indent=2, default=str)

    # Build the cybersecurity-specific prompt using data-driven prompt builder
    prompt = build_data_driven_cyber_prompt(context, config, scenario)


    # Use OpenAI to generate the report
    ai_config = config.get("ai", {})
    model = ai_config.get("model", MODEL)
    temperature = ai_config.get("temperature", 0.3)
    max_tokens = ai_config.get("max_tokens", 4000)  # Longer for cyber reports

    print(f"   Model: {model}")
    print(f"   Temperature: {temperature}")
    print(f"   Max tokens: {max_tokens}")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a Chief Information Security Officer (CISO) and elite cybersecurity management consultant. "
                    "You create board-ready security program intelligence reports with exceptional clarity, rigor, and business acumen. "
                    "Your reports inform multi-million dollar security investment decisions and risk mitigation strategies for Fortune 500 executives.\n\n"
                    "CRITICAL OUTPUT RULES:\n"
                    "• Output ONLY plain markdown (headings, paragraphs, bullet lists, tables)\n"
                    "• Do NOT emit any raw HTML tags (<div>, <span>, <section>, class=, etc.)\n"
                    "• Do NOT wrap your answer in code fences (no ```markdown or ``` blocks)\n"
                    "• Start immediately with the first markdown heading\n"
                    "• Use professional, executive-level language\n"
                    "• Separate facts (from data) from interpretation (your analysis)\n"
                    "• Quantify everything: use dollars, percentages, counts, dates"
                )
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    print("   ✓ Report generated successfully\n")
    return response.choices[0].message.content.strip()


def write_markdown_output(summary: str, config: Dict[str, Any], scenario: str = None) -> str:
    """Write summary to Markdown file."""
    # Get output config from scenario or default
    if scenario and scenario in config.get("scenarios", {}):
        scenario_config = config["scenarios"][scenario]
        md_config = scenario_config.get("output", {}).get("formats", {}).get("markdown", {})
        report_title = scenario_config.get("title", "Report")
        sources = "Jira, Wrike, Slack, Gmail, HubSpot, Confluence, Calendar, Risk Register"
    else:
        md_config = config.get("output", {}).get("formats", {}).get("markdown", {})
        report_title = config.get("report", {}).get("title", "Weekly Program Status")
        sources = "Meeting Notes, Jira, Slack"

    if not md_config.get("enabled", True):
        return None

    output_dir = md_config.get("path", "output")
    os.makedirs(output_dir, exist_ok=True)

    today = datetime.date.today().strftime("%Y-%m-%d")
    filename_pattern = md_config.get("filename_pattern", "weekly_summary_{date}.md")
    filename = filename_pattern.replace("{date}", today)
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {report_title} ({today})\n\n")
        f.write(summary)
        f.write(f"\n\n---\n")
        f.write(f"*Generated automatically by Status Summarizer Bot | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
        f.write(f"*Sources: {sources}*\n")

    return filepath


def markdown_to_html_sections(markdown_text: str) -> str:
    """
    Convert Markdown summary to HTML sections matching the new template structure.
    Converts tables, badges, and sections with proper CSS classes.
    """
    import re

    html_parts = []
    lines = markdown_text.split("\n")

    in_table = False
    in_list = False
    in_card = False
    current_card_content = []
    current_section = None
    i = 0

    def close_card():
        nonlocal in_card, current_card_content, html_parts
        if in_card and current_card_content:
            html_parts.append("</div>")  # Close card
            in_card = False
            current_card_content = []

    def get_badge_class(text):
        """Determine badge class based on status emoji/text"""
        if '🟢' in text or '✅' in text or 'Complete' in text or 'Positive' in text:
            return 'badge ok'
        elif '🟠' in text or '⚠️' in text or 'At Risk' in text or 'High' in text or 'Concern' in text:
            return 'badge warn'
        elif '🔴' in text or '🔥' in text or 'Critical' in text or 'Urgent' in text:
            return 'badge danger'
        else:
            return 'badge'

    def process_table_row(row, is_header=False):
        """Convert markdown table row to HTML with badges"""
        cells = [cell.strip() for cell in row.split('|')[1:-1]]  # Remove empty first/last

        if is_header:
            html_cells = ''.join(f'<th>{cell}</th>' for cell in cells)
            return f'<tr>{html_cells}</tr>'
        else:
            html_cells = []
            for cell in cells:
                # Check if cell contains status indicator and wrap in badge
                if any(emoji in cell for emoji in ['🟢', '🟠', '🔴', '✅', '⚠️', '🔥', '⚙️']):
                    badge_class = get_badge_class(cell)
                    html_cells.append(f'<td><span class="{badge_class}">{cell}</span></td>')
                else:
                    html_cells.append(f'<td>{cell}</td>')
            return f'<tr>{"".join(html_cells)}</tr>'

    while i < len(lines):
        line = lines[i]

        # Detect section headers (### 1. AT-A-GLANCE DASHBOARD)
        if line.startswith('###'):
            close_card()

            title = line.replace('###', '').strip()
            section_lower = title.lower()

            # Determine section structure
            if 'at-a-glance' in section_lower or 'dashboard' in section_lower:
                html_parts.append('<div class="card">')
                html_parts.append(f'<h3>{title}</h3>')
                in_card = True

            elif 'executive highlight' in section_lower:
                # Start 2-column grid
                html_parts.append('<div class="grid-2">')
                html_parts.append('<div class="card">')
                html_parts.append(f'<h3>{title}</h3>')
                in_card = True
                current_section = 'highlights'

            elif 'key win' in section_lower:
                # Second column of grid
                html_parts.append('<div class="card">')
                html_parts.append(f'<h3>{title}</h3>')
                in_card = True
                current_section = 'wins'

            elif 'risk' in section_lower:
                html_parts.append('</div>')  # Close previous grid if any
                html_parts.append('<section class="section">')
                html_parts.append('<h2>Tier 2 — Why it matters?</h2>')
                html_parts.append('<div class="card">')
                html_parts.append(f'<h3>{title}</h3>')
                in_card = True

            elif 'stakeholder' in section_lower:
                html_parts.append('</div>')  # Close previous section if any
                html_parts.append('<section class="section">')
                html_parts.append('<h2>Tier 3 — What\'s next?</h2>')
                html_parts.append('<div class="twocol">')
                html_parts.append('<div class="card alt">')
                html_parts.append(f'<h3>{title}</h3>')
                in_card = True

            elif 'next week' in section_lower or 'executive action' in section_lower:
                html_parts.append('<div class="card">')
                html_parts.append(f'<h3>{title}</h3>')
                in_card = True

            elif 'metric' in section_lower:
                html_parts.append('</div>')  # Close twocol
                html_parts.append('</section>')  # Close section
                html_parts.append('<section class="section">')
                html_parts.append('<div class="card">')
                html_parts.append(f'<h3>{title}</h3>')
                in_card = True

            else:
                html_parts.append('<div class="card">')
                html_parts.append(f'<h3>{title}</h3>')
                in_card = True

        # Detect markdown tables
        elif '|' in line and line.strip().startswith('|'):
            if not in_table:
                html_parts.append('<table class="table">')
                in_table = True

                # Check if next line is separator
                if i + 1 < len(lines) and '---' in lines[i + 1]:
                    html_parts.append('<thead>')
                    html_parts.append(process_table_row(line, is_header=True))
                    html_parts.append('</thead>')
                    html_parts.append('<tbody>')
                    i += 1  # Skip separator line
                else:
                    html_parts.append('<tbody>')
                    html_parts.append(process_table_row(line))
            else:
                html_parts.append(process_table_row(line))

        # Close table when no more table rows
        elif in_table and '|' not in line:
            html_parts.append('</tbody>')
            html_parts.append('</table>')
            in_table = False

        # Detect lists
        elif line.strip().startswith('- '):
            if not in_list:
                html_parts.append('<ul class="clean">')
                in_list = True
            item = line.strip()[2:]
            html_parts.append(f'<li>{item}</li>')

        elif re.match(r'^\d+\.', line.strip()):
            if not in_list:
                html_parts.append('<ol class="clean">')
                in_list = True
            item = re.sub(r'^\d+\.\s*', '', line.strip())
            html_parts.append(f'<li>{item}</li>')

        # Close list when encountering non-list content
        elif in_list and line.strip() and not line.strip().startswith(('-', '1.', '2.', '3.')):
            html_parts.append('</ul>' if '<ul' in ''.join(html_parts[-10:]) else '</ol>')
            in_list = False

        # Detect subsections (Top 3 Priorities, Decisions Needed)
        elif line.strip().startswith('**') and line.strip().endswith('**'):
            if in_list:
                html_parts.append('</ul>' if '<ul' in ''.join(html_parts[-10:]) else '</ol>')
                in_list = False
            subtitle = line.strip('*').strip()
            html_parts.append(f'<div class="sub">{subtitle}</div>')

        # Handle blockquotes (summary line after dashboard)
        elif line.strip().startswith('>'):
            text = line.strip()[1:].strip()
            html_parts.append(f'<p><em>{text}</em></p>')

        # Regular paragraphs
        elif line.strip() and not line.startswith('#'):
            html_parts.append(f'<p>{line.strip()}</p>')

        i += 1

    # Close any open elements
    if in_list:
        html_parts.append('</ul>')
    if in_table:
        html_parts.append('</tbody></table>')
    if in_card:
        html_parts.append('</div>')  # Close card

    # Close any open grids/sections
    html_parts.append('</div>')  # Close last grid/twocol if any
    html_parts.append('</section>')  # Close section

    return '\n'.join(html_parts)


def write_html_output(summary: str, config: Dict[str, Any], scenario: str = None, risk_context: Optional[Dict[str, Any]] = None, ebitda_chart_path: Optional[str] = None, cyber_context: Optional[Dict[str, Any]] = None) -> str:
    """Write summary to HTML file using template."""
    # Get output config from scenario or default
    if scenario and scenario in config.get("scenarios", {}):
        scenario_config = config["scenarios"][scenario]
        html_config = scenario_config.get("output", {}).get("formats", {}).get("html", {})
        report_title = scenario_config.get("title", "Report")
    else:
        html_config = config.get("output", {}).get("formats", {}).get("html", {})
        report_title = config.get("report", {}).get("title", "Weekly Program Status")

    if not html_config.get("enabled", False):
        return None

    output_dir = html_config.get("path", "output")
    os.makedirs(output_dir, exist_ok=True)

    today = datetime.date.today().strftime("%Y-%m-%d")
    filename_pattern = html_config.get("filename_pattern", "weekly_summary_{date}.html")
    filename = filename_pattern.replace("{date}", today)
    filepath = os.path.join(output_dir, filename)

    # Load template
    from jinja2 import Template

    template_path = html_config.get("template", "templates/executive_report.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template_str = f.read()

    # Convert markdown summary to HTML
    html_content = markdown_to_html_sections(summary)

    # Extract Analyst Notes section for Cyber PMO scenario
    analyst_notes_content = ""
    if scenario == 'sentient_cyber_pmo':
        # Extract the "Analyst Notes & Key Insights" section from markdown
        import re
        match = re.search(r'# Analyst Notes & Key Insights\n+(.*?)(?=\n---|\Z)', summary, re.DOTALL)
        if match:
            analyst_notes_md = match.group(1).strip()
            # Convert markdown to HTML with proper list handling
            lines = analyst_notes_md.split('\n')
            html_lines = []
            in_list = False

            for line in lines:
                if line.startswith('### '):
                    # Close any open list before starting new heading
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    heading = line[4:]  # Remove '### '
                    html_lines.append(f'<h3>{heading}</h3>')
                elif line.startswith('- '):
                    # Start list if not already in one
                    if not in_list:
                        html_lines.append('<ul>')
                        in_list = True
                    item = line[2:]  # Remove '- '
                    # Convert markdown formatting
                    item = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item)
                    item = re.sub(r'`(.*?)`', r'<code>\1</code>', item)
                    html_lines.append(f'<li>{item}</li>')
                elif line.strip() == '':
                    # Close list on empty line
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                else:
                    # Regular paragraph text
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    if line.strip():
                        # Convert markdown formatting
                        line = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
                        line = re.sub(r'`(.*?)`', r'<code>\1</code>', line)
                        html_lines.append(f'<p>{line}</p>')

            # Close any remaining open list
            if in_list:
                html_lines.append('</ul>')

            analyst_notes_content = '\n'.join(html_lines)

    # Prepare template variables
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create Jinja2 template and render
    template = Template(template_str)
    template_vars = {
        'title': report_title,
        'date': today,
        'content': html_content if scenario != 'sentient_cyber_pmo' else analyst_notes_content,
        'timestamp': timestamp,
        'scenario': scenario
    }

    # Add scenario-specific variables
    if scenario == 'sentient_cx_risk_radar':
        # Build dashboard context from CSV data
        dashboard_ctx = build_dashboard_context(config, scenario)

        # Merge dashboard context into template vars
        template_vars.update(dashboard_ctx)

        # Inject risk_context data if provided (for charts and legacy heatmap data)
        if risk_context:
            # Add chart paths
            if 'chart_paths' in risk_context:
                chart_paths = risk_context['chart_paths']
                template_vars['sentiment_trend_chart'] = chart_paths.get('sentiment_trend')
                template_vars['complaints_escalations_chart'] = chart_paths.get('complaints_escalations')
                template_vars['risk_exposure_chart'] = chart_paths.get('risk_exposure')
                template_vars['risk_heatmap_chart'] = chart_paths.get('risk_heatmap')
                template_vars['stakeholder_map_chart'] = chart_paths.get('stakeholder_map')

            # Add EBITDA context
            if 'ebitda' in risk_context:
                template_vars['ebitda'] = risk_context['ebitda']

            # Add EBITDA chart path
            if ebitda_chart_path:
                template_vars['ebitda_chart_path'] = os.path.basename(ebitda_chart_path)

    elif scenario == 'sentient_cyber_pmo':
        # Inject cyber_context data if provided
        if cyber_context:
            # Merge all cyber context data into template vars
            template_vars.update(cyber_context)

    else:
        # Default KPI values for standard reports
        template_vars.update({
            'kpi_delivery_value': 'Stable',
            'kpi_delivery_trend': 'Trajectory ↗',
            'kpi_velocity_value': 'Healthy',
            'kpi_velocity_trend': 'Sustained ↑',
            'kpi_cost_value': 'Caution',
            'kpi_cost_trend': 'Infra ↑'
        })

    html_output = template.render(**template_vars)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_output)

    return filepath


def prioritize_cyber_context(cyber_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 2: Prioritization/Compression Layer

    Distills the rich cyber_context from Stage 1 into a small, LLM-ready summary.

    This function is pure and deterministic:
    - No LLM calls
    - No I/O operations
    - Same input always produces same output

    Args:
        cyber_context: Rich context dict from build_cyber_context() (Stage 1)

    Returns:
        Prioritized dict with:
        - top_risks: Top 5 risks by EBITDA_Impact
        - weakest_domains: 3 weakest CISSP domains
        - kpis: Executive-level KPI subset
        - top_compliance_gaps: Top 3 compliance gaps by risk rating
        - security_debt: Curated security debt metrics
        - program_health: Curated program health metrics
        - financials: Full financial aggregates (passed through)
    """
    print("\n🎯 [Stage 2] Prioritizing cyber context for LLM processing...")

    prioritized = {}

    # === 1. Top 5 Risks by EBITDA Impact ===
    risks_df = cyber_context.get("risks", pd.DataFrame())

    if not risks_df.empty and "EBITDA_Impact" in risks_df.columns:
        # Sort by EBITDA_Impact descending, take top 5
        top_risks_df = risks_df.nlargest(5, "EBITDA_Impact")

        # Convert to list of dicts with required fields
        prioritized["top_risks"] = []
        for _, row in top_risks_df.iterrows():
            prioritized["top_risks"].append({
                "RiskID": row.get("RiskID", "Unknown"),
                "Domain": row.get("Domain", "Unknown"),
                "Description": row.get("Description", ""),
                "ExposureAmount": row.get("ExposureAmount", 0),
                "Likelihood": row.get("Likelihood", "Unknown"),
                "EBITDA_Impact": row.get("EBITDA_Impact", 0)
            })

        print(f"    ✓ Selected top 5 risks by EBITDA impact (total: ${sum(r['EBITDA_Impact'] for r in prioritized['top_risks']) / 1_000_000:.1f}M)")
    else:
        prioritized["top_risks"] = []
        print("    ✗ No risk data available")

    # === 2. Top 3 Weakest CISSP Domains ===
    domain_scores = cyber_context.get("domain_scores", {})

    if domain_scores:
        # Sort by score ascending (lowest scores = weakest domains)
        sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1])

        # Take top 3 weakest
        prioritized["weakest_domains"] = [
            {"domain": domain, "score": score}
            for domain, score in sorted_domains[:3]
        ]

        print(f"    ✓ Identified 3 weakest CISSP domains: {', '.join(d['domain'] for d in prioritized['weakest_domains'])}")
    else:
        prioritized["weakest_domains"] = []
        print("    ✗ No domain scores available")

    # === 3. Executive KPI Subset ===
    all_kpis = cyber_context.get("kpis", {})

    # Curated subset for executives
    executive_kpi_keys = [
        "total_incidents",
        "critical_incidents_count",
        "avg_mttd_hours",
        "avg_mttr_hours",
        "open_critical_vulns",
        "overdue_vulns_count",
        "failing_controls_count",
        "total_ebitda_impact"
    ]

    prioritized["kpis"] = {
        key: all_kpis.get(key, 0)
        for key in executive_kpi_keys
    }

    kpi_count = len([v for v in prioritized["kpis"].values() if v != 0])
    print(f"    ✓ Selected {kpi_count} executive KPIs from {len(all_kpis)} total metrics")

    # === 4. Top 3 Compliance Gaps ===
    compliance_gaps = cyber_context.get("compliance_gaps", [])

    if compliance_gaps:
        # Filter for High or Medium-High risk rating
        high_risk_gaps = [
            gap for gap in compliance_gaps
            if gap.get("RiskRating", "").lower() in ["high", "medium-high"]
        ]

        # Take top 3
        prioritized["top_compliance_gaps"] = high_risk_gaps[:3]

        print(f"    ✓ Selected top 3 compliance gaps (from {len(compliance_gaps)} total)")
    else:
        prioritized["top_compliance_gaps"] = []
        print("    ✗ No compliance gaps available")

    # === 5. Curated Security Debt Metrics ===
    security_debt = cyber_context.get("security_debt", {})

    # Only include executive-relevant fields
    prioritized["security_debt"] = {
        "total_open_vulns": security_debt.get("total_open_vulns", 0),
        "critical_vulns_open": security_debt.get("critical_vulns_open", 0),
        "count_overdue_vulns": security_debt.get("count_overdue_vulns", 0),
        "oldest_vuln_age_days": security_debt.get("oldest_vuln_age_days", 0)
    }

    print(f"    ✓ Curated security debt: {prioritized['security_debt']['critical_vulns_open']} critical vulns, {prioritized['security_debt']['count_overdue_vulns']} overdue")

    # === 6. Curated Program Health Metrics ===
    program_health = cyber_context.get("program_health", {})

    prioritized["program_health"] = {
        "total_tasks": program_health.get("total_tasks", 0),
        "percent_in_progress": program_health.get("percent_in_progress", 0.0),
        "percent_not_started": program_health.get("percent_not_started", 0.0),
        "tasks_blocked_count": program_health.get("tasks_blocked_count", 0),
        "high_risk_tasks_open": program_health.get("high_risk_tasks_open", 0)
    }

    print(f"    ✓ Curated program health: {prioritized['program_health']['total_tasks']} tasks, {prioritized['program_health']['tasks_blocked_count']} blocked")

    # === 7. Financial Aggregates (Pass Through) ===
    prioritized["financials"] = cyber_context.get("financials", {})

    total_exposure = prioritized["financials"].get("total_exposure", 0)
    total_ebitda = prioritized["financials"].get("total_ebitda_impact", 0)
    print(f"    ✓ Financial aggregates: ${total_exposure / 1_000_000:.1f}M exposure, ${total_ebitda / 1_000_000:.1f}M EBITDA impact")

    print(f"\n✅ [Stage 2] Prioritization complete!")
    print(f"    • Compressed from full context → {len(prioritized['top_risks'])} risks + {len(prioritized['weakest_domains'])} domains + {len(prioritized['kpis'])} KPIs")

    return prioritized


def generate_cyber_executive_summary(prioritized: Dict[str, Any], config: Dict[str, Any]) -> str:
    """
    Stage 3a: Generate Executive Summary from prioritized context

    Uses LLM to create a concise executive summary focusing on:
    - One headline sentence
    - 4-6 KPI bullets
    - Exactly 3 "Decisions Required"

    Args:
        prioritized: Prioritized context from Stage 2
        config: Application configuration

    Returns:
        Executive summary markdown string (~8 lines total)
    """
    print("\n📝 [Stage 3a] Generating Executive Summary...")

    # Extract relevant data
    kpis = prioritized.get("kpis", {})
    top_risks = prioritized.get("top_risks", [])[:3]  # Top 3 only
    financials = prioritized.get("financials", {})
    weakest_domains = prioritized.get("weakest_domains", [])

    # Build prompt
    import json
    data_json = json.dumps({
        "kpis": kpis,
        "top_3_risks": top_risks,
        "total_ebitda_impact": financials.get("total_ebitda_impact", 0),
        "total_exposure": financials.get("total_exposure", 0),
        "weakest_domains": weakest_domains
    }, indent=2)

    prompt = f"""You are a CISO preparing an executive cybersecurity summary for the CEO, CFO, and Board.

**Data** (from prioritized context):
{data_json}

**Task**: Generate an executive summary with EXACTLY this structure:

1. **ONE HEADLINE SENTENCE** (15 words max):
   Pattern: "Security posture is [improving/stable/deteriorating] across [domains], creating [preventable/active] breach path with $X.XM EBITDA exposure."

2. **KPI ROW** (4-6 bullets):
   - **Total Risk Exposure**: $X.XM
   - **Incidents**: X (from total_incidents)
   - **MTTR**: X.X hours (from avg_mttr_hours)
   - **Critical Vulns Overdue**: X (from overdue_vulns_count)
   - **Failing Controls**: X (from failing_controls_count)
   - **EBITDA Impact**: $X.XM (from total_ebitda_impact)

3. **EXACTLY 3 DECISIONS REQUIRED**:
   Format per decision:
   **[Decision]** (Owner: [Role] | When: [Timeframe] | Addresses: [RiskID/Domain])

   Base decisions on top_3_risks and weakest_domains data above.

**Constraints**:
- Total output: ~8 lines
- No paragraphs
- No generic advice
- Use actual RiskIDs, dollar amounts, and metrics from data above
- Each decision must reference a specific risk or domain from the data

**Output Format**: Plain markdown, no code fences.

Generate the executive summary now:"""

    # Call LLM
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500
        )
        summary = response.choices[0].message.content.strip()
        print(f"    ✓ Generated executive summary ({len(summary)} chars, ~{len(summary.split())} words)")
        return summary
    except Exception as e:
        print(f"    ✗ Error generating executive summary: {e}")
        return "# Executive Summary\n\n[Error generating summary]"


def generate_cyber_section_summaries(prioritized: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
    """
    Stage 3b: Generate section summaries from prioritized context

    Creates focused summaries for 6 sections:
    - risk_posture
    - threats_and_incidents
    - vulnerabilities_and_debt
    - controls_and_compliance
    - program_execution
    - financial_impact

    Each section follows "What → Why → Do" structure (5-7 lines max).

    Args:
        prioritized: Prioritized context from Stage 2
        config: Application configuration

    Returns:
        Dict mapping section name to markdown summary
    """
    print("\n📝 [Stage 3b] Generating section summaries...")

    sections = {}

    # Extract data for sections
    top_risks = prioritized.get("top_risks", [])
    kpis = prioritized.get("kpis", {})
    compliance_gaps = prioritized.get("top_compliance_gaps", [])
    security_debt = prioritized.get("security_debt", {})
    program_health = prioritized.get("program_health", {})
    financials = prioritized.get("financials", {})
    weakest_domains = prioritized.get("weakest_domains", [])

    import json

    # === 1. Risk Posture ===
    risk_data = json.dumps({
        "top_5_risks": top_risks[:5],
        "weakest_domains": weakest_domains
    }, indent=2)

    sections["risk_posture"] = _generate_section(
        section_name="Cyber Risk Posture",
        data=risk_data,
        instructions="""
**What**: Summarize top risks by RiskID with breach paths (Initial Access → Lateral Movement → Impact)
**Why**: State CISSP domain + business impact (e.g., "Cloud Security: Credential theft → $X.XM GDPR penalties")
**Do**: Concrete action with timeframe

5-7 lines max. No repetition of executive summary."""
    )

    # === 2. Threats & Incidents ===
    incident_data = json.dumps({
        "total_incidents": kpis.get("total_incidents", 0),
        "critical_incidents": kpis.get("critical_incidents_count", 0),
        "avg_mttd_hours": kpis.get("avg_mttd_hours", 0),
        "avg_mttr_hours": kpis.get("avg_mttr_hours", 0)
    }, indent=2)

    sections["threats_and_incidents"] = _generate_section(
        section_name="Threat & Incident Trends",
        data=incident_data,
        instructions="""
**What**: Describe incident patterns and attack types
**Why**: CISSP domain (Security Operations) + business impact
**Do**: Concrete action with timeframe

5-7 lines max. Start with "Incident trends show..."."""
    )

    # === 3. Vulnerabilities & Debt ===
    vuln_data = json.dumps({
        "security_debt": security_debt,
        "open_critical_vulns": kpis.get("open_critical_vulns", 0),
        "overdue_vulns": kpis.get("overdue_vulns_count", 0)
    }, indent=2)

    sections["vulnerabilities_and_debt"] = _generate_section(
        section_name="Vulnerability & Security Debt",
        data=vuln_data,
        instructions="""
**What**: Highlight critical CVEs and SLA breaches
**Why**: CISSP domain (IAM/Software Security) + business impact
**Do**: Concrete action with timeframe

5-7 lines max. Start with "Vulnerability data shows..."."""
    )

    # === 4. Controls & Compliance ===
    compliance_data = json.dumps({
        "top_compliance_gaps": compliance_gaps,
        "failing_controls": kpis.get("failing_controls_count", 0),
        "weakest_domains": weakest_domains
    }, indent=2)

    sections["controls_and_compliance"] = _generate_section(
        section_name="Controls & Compliance (CISSP Alignment)",
        data=compliance_data,
        instructions="""
**What**: List failing controls and compliance gaps by framework
**Why**: CISSP domain (Security & Risk Management) + audit/contract risk
**Do**: Concrete action with timeframe

5-7 lines max."""
    )

    # === 5. Program Execution ===
    program_data = json.dumps({
        "program_health": program_health
    }, indent=2)

    sections["program_execution"] = _generate_section(
        section_name="Program Execution & Governance",
        data=program_data,
        instructions="""
**What**: Highlight blocked tasks and velocity issues
**Why**: CISSP domain (Security Governance) + business impact
**Do**: Concrete action with timeframe

5-7 lines max."""
    )

    # === 6. Financial Impact ===
    financial_data = json.dumps({
        "total_ebitda_impact": financials.get("total_ebitda_impact", 0),
        "ebitda_by_driver": financials.get("ebitda_by_driver", {}),
        "top_risks": top_risks[:3]
    }, indent=2)

    sections["financial_impact"] = _generate_section(
        section_name="Financial Impact (EBITDA)",
        data=financial_data,
        instructions="""
**What**: Show EBITDA drivers by category (revenue, opex, penalties, downtime)
**Why**: CFO-ready: What's controllable in 90 days?
**Do**: State 90-day scenarios: "Do nothing" vs "Controllable"

5-7 lines max. Start with "EBITDA waterfall shows..."."""
    )

    print(f"    ✓ Generated {len(sections)} section summaries")
    return sections


def _generate_section(section_name: str, data: str, instructions: str) -> str:
    """Helper function to generate a single section summary."""
    prompt = f"""You are a CISO writing a concise section for an executive cyber report.

**Section**: {section_name}

**Data**:
{data}

**Instructions**:
{instructions}

**Structure**: What → Why → Do (bullets only, no paragraphs)
**Length**: 5-7 lines max
**Audience**: CEO, CFO, CTO

**Output Format**: Plain markdown, no code fences.

Generate the section now:"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"    ✗ Error generating {section_name}: {e}")
        return f"## {section_name}\n\n[Error generating section]"


def generate_cyber_decisions_block(prioritized: Dict[str, Any], config: Dict[str, Any]) -> str:
    """
    Stage 3c: Generate "Decisions & Next 30 Days" block

    Creates a focused decision list with:
    - 3-5 numbered recommendations
    - Each with: Action + Owner role + Timeframe + Risk/EBITDA driver

    Args:
        prioritized: Prioritized context from Stage 2
        config: Application configuration

    Returns:
        Decisions block markdown string (~6 lines)
    """
    print("\n📝 [Stage 3c] Generating Decisions & Next 30 Days...")

    # Extract relevant data
    top_risks = prioritized.get("top_risks", [])[:5]
    weakest_domains = prioritized.get("weakest_domains", [])
    financials = prioritized.get("financials", {})
    program_health = prioritized.get("program_health", {})

    import json
    data_json = json.dumps({
        "top_5_risks": top_risks,
        "weakest_domains": weakest_domains,
        "total_ebitda_impact": financials.get("total_ebitda_impact", 0),
        "tasks_blocked_count": program_health.get("tasks_blocked_count", 0)
    }, indent=2)

    prompt = f"""You are a CISO preparing a "Decisions & Next 30 Days" section for the CEO and Board.

**Data** (from prioritized context):
{data_json}

**Task**: Generate a decisions block with:

1. **Intro line**:
   "To materially improve cyber posture over the next 30 days, we recommend:"

2. **3-5 numbered recommendations**:
   Format per recommendation:
   [#]. **[Action]** | Owner: [Role] | Timeframe: [< X days] | Domain: [CISSP Domain] | Addresses: [RiskID + $X.XM]

   Example:
   1. **Deploy CSPM for S3 bucket scanning** | Owner: CISO | Timeframe: < 14 days | Domain: Cloud Security | Addresses: SR-003 → $9.0M regulatory penalties

   Base recommendations on top_5_risks and weakest_domains from data above.

**Constraints**:
- Total output: ~6 lines (intro + 3-5 recommendations)
- No "Decisions Required" subsection (this is the full output)
- Use actual RiskIDs and dollar amounts from data
- Each recommendation must reference specific risk or domain from data

**Output Format**: Plain markdown, no code fences.

Generate the decisions block now:"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=400
        )
        decisions = response.choices[0].message.content.strip()
        print(f"    ✓ Generated decisions block ({len(decisions)} chars)")
        return decisions
    except Exception as e:
        print(f"    ✗ Error generating decisions: {e}")
        return "# Decisions & Next 30 Days\n\n[Error generating decisions]"


def generate_cyber_narrative(prioritized: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 3: Generate complete cyber narrative from prioritized context

    Orchestrates LLM calls to create executive-grade narrative components:
    - Executive summary (headline + KPIs + 3 decisions)
    - 6 section summaries (risk, threats, vulns, compliance, program, financial)
    - Decisions block (3-5 recommendations)

    This is the LLM processing stage of the pipeline:
    Stage 1 (build_cyber_context) → Stage 2 (prioritize) → Stage 3 (narrative) → Stage 4 (output)

    Args:
        prioritized: Prioritized context from Stage 2 (prioritize_cyber_context)
        config: Application configuration

    Returns:
        Dict with:
        - executive_summary: str
        - sections: Dict[str, str]
        - decisions: str
    """
    print("\n" + "=" * 80)
    print("STAGE 3: LLM Narrative Generation")
    print("=" * 80)

    narrative = {}

    # 3a. Executive Summary
    narrative["executive_summary"] = generate_cyber_executive_summary(prioritized, config)

    # 3b. Section Summaries
    narrative["sections"] = generate_cyber_section_summaries(prioritized, config)

    # 3c. Decisions Block
    narrative["decisions"] = generate_cyber_decisions_block(prioritized, config)

    print("\n✅ [Stage 3] Narrative generation complete!")
    print(f"    • Executive Summary: {len(narrative['executive_summary'])} chars")
    print(f"    • Sections: {len(narrative['sections'])} sections")
    print(f"    • Decisions: {len(narrative['decisions'])} chars")

    return narrative


def main(scenario: str = None):
    """
    Main execution flow.

    Args:
        scenario: Optional scenario name to run (e.g., 'sentient_cx_risk_radar')
                 If None, runs default weekly status report
    """
    print("=" * 80)
    if scenario:
        print(f"🤖 STATUS SUMMARIZER BOT v2.0 - Scenario: {scenario}")
    else:
        print("🤖 STATUS SUMMARIZER BOT v2.0")
    print("=" * 80)

    # Load configuration
    config = load_config()

    # Route to appropriate pipeline based on scenario
    if scenario == "sentient_cx_risk_radar":
        # Platinum Day 2 pipeline: structured context → charts → v2 AI summarizer
        risk_context = build_risk_context(config, scenario)

        # Build EBITDA waterfall context
        ebitda_context = build_ebitda_context(risk_context, config)
        risk_context["ebitda"] = ebitda_context
        print(f"\n💰 EBITDA Context:")
        print(f"   Baseline: ${ebitda_context['baseline_ebitda']}M")
        print(f"   Final: ${ebitda_context['final_ebitda']}M")
        print(f"   Impact: ${ebitda_context['total_impact']}M ({ebitda_context['impact_pct']}%)")

        # Get output directory from config
        scenario_config = config.get("scenarios", {}).get(scenario, {})
        output_config = scenario_config.get("output", {}).get("formats", {})
        output_dir = output_config.get("markdown", {}).get("path", "output")

        # Generate timestamp for consistent filenames
        today = datetime.date.today().strftime("%Y-%m-%d")
        timestamp = today

        # Generate EBITDA waterfall chart
        ebitda_chart_path = None
        if ebitda_context and ebitda_context.get('baseline_ebitda', 0) > 0:
            ebitda_chart_filename = f"ebitda_waterfall_{timestamp}.png"
            ebitda_chart_path = os.path.join(output_dir, ebitda_chart_filename)

            try:
                print("\n📊 Generating EBITDA waterfall chart...")
                generate_ebitda_waterfall_chart(ebitda_context, ebitda_chart_path)
                print(f"   ✓ Generated EBITDA chart: {ebitda_chart_filename}")
            except Exception as e:
                print(f"   ⚠ Failed to generate EBITDA waterfall chart: {e}")
                ebitda_chart_path = None

        # Generate charts and attach paths to risk_context
        print("\n📊 Generating risk visualization charts...")
        chart_paths = generate_risk_charts(risk_context, output_dir)
        risk_context["chart_paths"] = chart_paths
        print(f"   ✓ Generated {len(chart_paths)} charts")

        # Generate AI summary
        summary = summarize_with_ai_v2(risk_context, config, scenario)

        # Write outputs with chart paths for Day 2
        print("\n📝 Writing outputs...")
        outputs = []

        md_path = write_markdown_output(summary, config, scenario)
        if md_path:
            outputs.append(f"Markdown: {md_path}")

        html_path = write_html_output(summary, config, scenario, risk_context=risk_context, ebitda_chart_path=ebitda_chart_path)
        if html_path:
            outputs.append(f"HTML: {html_path}")

    elif scenario == "sentient_cyber_pmo":
        # Platinum Day 3 pipeline: structured cybersecurity context → cyber AI summarizer

        # === STAGE 1: Fortune-500-Grade Context Builder ===
        # New simplified approach: Pure data transformation (pandas only, no LLM)
        # Loads CSVs → Computes KPIs → Returns structured dict
        # This is a cleaner, focused alternative to the comprehensive build_cyber_risk_program_context()

        # Option A: Use new Stage 1 builder (recommended for future scenarios)
        # cyber_context = build_cyber_context(config, scenario)

        # Option B: Use existing comprehensive builder (current production path)
        # build_cyber_risk_program_context() already:
        #   - Loads 11 CSV files into DataFrames
        #   - Computes cyber KPIs (compute_cyber_kpis)
        #   - Builds risk matrix and stakeholder quadrants
        #   - Computes EBITDA impact (compute_cyber_ebitda)
        #   - Generates all 9 charts (generate_all_cyber_charts)
        #   - Returns complete structured context
        cyber_context = build_cyber_risk_program_context(config, scenario)

        # Charts are already generated and in cyber_context["chart_paths"]
        # KPIs are already computed and in cyber_context["computed_kpis"]
        # EBITDA is already computed and in cyber_context["cyber_ebitda_detailed"]
        # Risk matrix is already built and in cyber_context["cyber_risk_matrix"]
        # Stakeholder quadrants are already built and in cyber_context["stakeholder_quadrants"]

        # === STAGE 2: Prioritization/Compression Layer ===
        # Distill rich cyber_context into LLM-ready summary
        # Pure function (no LLM calls, no I/O)
        # Selects:
        #   - Top 5 risks by EBITDA impact
        #   - 3 weakest CISSP domains
        #   - Executive KPI subset (8 key metrics)
        #   - Top 3 compliance gaps
        #   - Curated security debt and program health
        # prioritized = prioritize_cyber_context(cyber_context)
        # NOTE: Not yet wired - keeping existing flow for now

        # === STAGE 3: LLM Narrative Generation ===
        # NEW APPROACH (using Stage 2 + Stage 3):
        # narrative = generate_cyber_narrative(prioritized, config)
        # Returns:
        #   {
        #     "executive_summary": str,
        #     "sections": {
        #       "risk_posture": str,
        #       "threats_and_incidents": str,
        #       "vulnerabilities_and_debt": str,
        #       "controls_and_compliance": str,
        #       "program_execution": str,
        #       "financial_impact": str
        #     },
        #     "decisions": str
        #   }
        #
        # Then assemble into final markdown:
        # summary = f"""# Executive Summary
        # {narrative['executive_summary']}
        #
        # ## Cyber Risk Posture
        # {narrative['sections']['risk_posture']}
        #
        # ## Threat & Incident Trends
        # {narrative['sections']['threats_and_incidents']}
        # ... etc
        # """

        # EXISTING APPROACH (current production):
        # Generate AI summary using cybersecurity-specific summarizer
        # This uses build_data_driven_cyber_prompt() with 10 rules:
        #   RULE 1-6: Data grounding and trend validation
        #   RULE 7: Eliminate redundancy
        #   RULE 8: No generic filler phrases
        #   RULE 9: Analyst notes must be labeled
        #   RULE 10: Word limits per section (2,000 words total)
        # Generates 9 sections including new "Decisions Required"
        summary = summarize_cyber_program_with_ai(cyber_context, config, scenario)

        # Write outputs
        print("\n📝 Writing outputs...")
        outputs = []

        md_path = write_markdown_output(summary, config, scenario)
        if md_path:
            outputs.append(f"Markdown: {md_path}")

        # Pass cyber_context as risk_context for HTML template access
        # Template uses cyber_context["chart_paths"], cyber_context["cyber_ebitda_detailed"], etc.
        html_path = write_html_output(summary, config, scenario, risk_context=None, ebitda_chart_path=None, cyber_context=cyber_context)
        if html_path:
            outputs.append(f"HTML: {html_path}")

    else:
        # Default pipeline: text ingestion → v1 AI summarizer
        combined_data = ingest_all_sources(config, scenario)
        summary = summarize_with_ai(combined_data, config, scenario)

        # Write outputs without risk_context
        print("\n📝 Writing outputs...")
        outputs = []

        md_path = write_markdown_output(summary, config, scenario)
        if md_path:
            outputs.append(f"Markdown: {md_path}")

        html_path = write_html_output(summary, config, scenario)
        if html_path:
            outputs.append(f"HTML: {html_path}")

    # Display results
    print("\n✅ Summary generated successfully!")
    for output in outputs:
        print(f"   📄 {output}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    import sys

    # Check for scenario argument
    scenario_arg = None
    if len(sys.argv) > 1:
        if sys.argv[1] == "--scenario" and len(sys.argv) > 2:
            scenario_arg = sys.argv[2]
        else:
            scenario_arg = sys.argv[1]

    main(scenario=scenario_arg)
