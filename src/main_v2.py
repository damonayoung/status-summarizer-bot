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
from charts import generate_risk_charts



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
    sentiment_delta_text = None
    escalations_current = None
    escalations_delta_text = None

    if not sentiment_df.empty:
        # Actual columns: week_start, avg_sentiment_score, complaints, escalations, latency_ms, blocked_tickets, trust_index, notes
        sentiment_df = sentiment_df.sort_values("week_start")
        latest = sentiment_df.iloc[-1]
        sentiment_index_current = float(latest.get("avg_sentiment_score", 0.0))

        if len(sentiment_df) >= 2:
            prev = sentiment_df.iloc[-2]
            prev_val = float(prev.get("avg_sentiment_score", sentiment_index_current))
            if prev_val:
                pct_change = (sentiment_index_current - prev_val) / prev_val * 100.0
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
        "sentiment_delta_text": sentiment_delta_text,
        "escalations_current": escalations_current,
        "escalations_delta_text": escalations_delta_text,
        "top_exposure_label": top_exposure_label,
        "top_exposure_comment": top_exposure_comment,
        "total_exposure_millions": round(total_exposure_millions, 1) if total_exposure_millions else 0.0,
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


def write_html_output(summary: str, config: Dict[str, Any], scenario: str = None, risk_context: Optional[Dict[str, Any]] = None) -> str:
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

    # Prepare template variables
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create Jinja2 template and render
    template = Template(template_str)
    template_vars = {
        'title': report_title,
        'date': today,
        'content': html_content,
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

        # Get output directory from config
        scenario_config = config.get("scenarios", {}).get(scenario, {})
        output_config = scenario_config.get("output", {}).get("formats", {})
        output_dir = output_config.get("markdown", {}).get("path", "output")

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

        html_path = write_html_output(summary, config, scenario, risk_context=risk_context)
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
