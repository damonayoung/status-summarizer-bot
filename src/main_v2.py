"""
Status Summarizer Bot v2
AI-powered TPM status report generator that ingests from multiple sources.
"""

import os
import sys
import datetime
import yaml
from pathlib import Path
from typing import Dict, Any, List
from dotenv import load_dotenv
from openai import OpenAI

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from ingestors.jira_ingestor import JiraIngestor
from ingestors.slack_ingestor import SlackIngestor
from ingestors.notes_ingestor import NotesIngestor
from ingestors.csv_ingestor import CSVIngestor

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

    prompt = f"""You are an elite Customer Experience Risk Analyst creating a RISK-FOCUSED executive briefing for {title}.

DATA SOURCES (Jira, Wrike, Slack, Gmail, HubSpot, Confluence, Calendar, Risk Register, Stakeholders):
{combined_data}

CRITICAL INSTRUCTIONS - CX RISK RADAR FORMAT:

Your mission: Identify customer experience threats, assess severity, and recommend immediate actions.

**DATA SOURCE MAPPING** (use these exact sections from the data above):
- **RISK REGISTER**: Pre-identified risks with RiskID, Title, Severity, Strategy, Plan, Owner, TargetDate
- **STAKEHOLDERS**: Key people with Name, Role, Type, Org, Influence, EngagementPlan
- **JIRA**: Issues with IssueKey, Summary, Status, Priority, Assignee, DueDate, Labels
- **WRIKE**: Tasks with TaskID, Title, Status, Priority, Owner, DueDate
- **SLACK**: Team updates and discussions - extract sentiment and themes
- **GMAIL**: Email highlights - executive communications and escalations
- **HUBSPOT**: Deal pipeline data - account health and revenue risks
- **CONFLUENCE**: Documentation and knowledge base - context and policies
- **CALENDAR**: Upcoming meetings and deadlines

## STRUCTURE (EXACT FORMAT REQUIRED):

### 1. EXECUTIVE OVERVIEW
**CX Risk Posture**: [One sentence: Current state - Green/Yellow/Red and why]

**Instructions**: Synthesize from Risk Register (count High risks), Jira/Wrike (blocked items), HubSpot (at-risk deals)

**Critical Context**: 2-3 bullets summarizing:
- Most urgent CX threat and business impact (from Risk Register High severity items)
- Key customer sentiment trends (from Slack/Gmail/HubSpot - aggregate positive vs. negative signals)
- Any imminent deadlines or escalations (from Jira/Wrike/Calendar/Risk Register TargetDate)

Format: **Bold risk** → customer impact (quantify when possible)

### 2. TOP RISKS (Priority Table)
Markdown table: Risk | Severity | Customer Impact | Owner | Due Date | Status

**Severity Levels** (mandatory):
- 🔴 **High**: Direct customer impact, revenue at risk, escalation to C-suite
- 🟠 **Medium**: Degraded CX, at-risk deals, requires immediate attention
- 🟡 **Low**: Monitoring required, proactive mitigation

**Instructions**:
- **PRIMARY SOURCE**: Use RISK REGISTER as authoritative source (RiskID, Title, Severity, Owner, TargetDate)
- **SUPPLEMENT WITH**: Jira issues (High/Blocked priority), Wrike tasks (urgent/overdue)
- Cross-reference with customer sentiment signals (Slack complaints, Gmail escalations, HubSpot deal risks)
- Include due dates from Risk Register/Jira/Wrike/Calendar to show escalation timelines
- Show status: 🚨 Overdue, ⚠️ At Risk, 🔄 In Progress, ✅ Mitigated
- Prioritize by: (1) Customer revenue impact, (2) Escalation proximity, (3) Cross-functional dependencies
- **Format risks as**: "[RiskID/IssueKey] Risk Title" for traceability

List 5-7 highest severity risks only.

### 3. CX SIGNALS (Sentiment Analysis)
**Customer Sentiment Pulse**:

**Instructions**: Aggregate insights from SLACK, GMAIL, HUBSPOT, CONFLUENCE, JIRA, WRIKE

Analyze for:
- 😊 **Positive signals**: Customer wins, successful launches, deal closures, praise
- 😐 **Neutral signals**: Standard operations, monitoring items, routine updates
- 😟 **Negative signals**: Complaints, escalations, churn risks, support issues
- 🔥 **Critical alerts**: Executive escalations, at-risk renewals, urgent support tickets

Format as grouped bullets by source:
**SLACK** (Team Updates):
- [sentiment emoji] Key theme → insight (quote if available)

**GMAIL** (Executive Communications):
- [sentiment emoji] Key theme → insight (quote if available)

**HUBSPOT** (Deals & Pipeline):
- [sentiment emoji] Deal health → account risks (specific accounts if mentioned)

**JIRA + WRIKE** (Project Signals):
- [sentiment emoji] Development velocity → blocked/at-risk items

Include:
- Quote snippets that illustrate sentiment (1-2 per source)
- Trending patterns (▲ improving, ▼ declining, ↔ stable)
- Correlation with risks from Section 2

### 4. STAKEHOLDER IMPACT (Cross-Functional Risk Map)
Markdown table: Stakeholder | Role | Impact Level | Primary Concern | Action Needed

**Impact Levels**:
- 🔴 Critical: Blocked, urgent escalation, requires immediate exec decision
- 🟠 High: At-risk deliverables, coordination needed, potential delays
- 🟡 Medium: Monitoring, dependencies, proactive communication
- 🟢 Low: On track, no action required

**Instructions**:
- **PRIMARY SOURCE**: Use STAKEHOLDERS CSV (Name, Role, Type, Influence, EngagementPlan)
- Map risks from Section 2 to stakeholder owners (from Risk Register Owner field and Jira Assignee)
- Cross-reference Calendar meetings for stakeholder engagement
- Cross-reference Confluence for documented concerns/plans
- Show what each stakeholder needs (decision, resource, visibility, approval)
- Prioritize by Influence level (High > Medium > Low) and Type (Sponsor > Driver > Deliver > Govern)

### 5. NEXT 7-DAY ACTIONS (Tactical Mitigation Plan)
**Immediate Actions** (prioritized by urgency):

**Instructions**: Extract from Risk Register (Plan field), Jira (In Progress/To Do), Wrike (active tasks), Calendar (upcoming deadlines)

1. **[Day 1-2]** Action item → expected outcome (owner from Stakeholders/Risk Register, due date from Jira/Wrike)
2. **[Day 3-4]** Action item → expected outcome (owner, due date)
3. **[Day 5-7]** Action item → expected outcome (owner, due date)

**Escalation Watch List**:
- Item with approaching deadline → consequence if missed (date from Calendar/Jira/Risk Register TargetDate)
- Item requiring executive decision → business impact (decision owner from Stakeholders)

**Success Metrics**:
- How will we measure risk mitigation?
- What KPIs should improve in next 7 days?
- Reference Risk Register Strategy/Plan fields for mitigation approach

FOCUS AREAS (from configuration):
{chr(10).join('- ' + focus for focus in prompt_focus)}

TONE GUIDELINES:
- **Risk-first language**: Lead with severity and customer impact
- **Urgency indicators**: Use dates, deadlines, escalation timelines
- **Quantify impact**: Revenue at risk, customer count, SLA breaches, deal pipeline
- **Actionable**: Every risk needs a mitigation with owner and ETA
- **Data-driven**: Reference specific signals from Slack/Gmail/HubSpot
- **Executive-ready**: Assume audience is C-suite making budget/resource decisions

CRITICAL ANALYSIS RULES:
1. **Correlate data sources**: Connect Jira/Wrike tasks to CX signals (e.g., "Bug-123 delay correlates with 3 Slack escalations")
2. **Escalation math**: Calculate days until deadline, days overdue, trend velocity
3. **Sentiment scoring**: Aggregate positive/negative signals per source
4. **Risk prioritization**: High severity + near deadline + customer revenue = top priority
5. **Stakeholder mapping**: Who is blocked by what, who needs to decide what

AVOID:
- Generic risk descriptions without customer impact
- Missing severity levels or due dates
- Ignoring sentiment signals from Slack/Gmail/HubSpot
- Risks without clear owners or mitigation plans
- Technical jargon without business context

This report must enable leadership to triage CX risks and allocate resources in under 5 minutes.
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


def write_html_output(summary: str, config: Dict[str, Any], scenario: str = None) -> str:
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
        # Extract risk posture from summary if available (simple extraction)
        template_vars['risk_posture'] = None  # Could be extracted from summary
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

    # Ingest from all sources (scenario-aware)
    combined_data = ingest_all_sources(config, scenario)

    # Generate AI summary (scenario-aware)
    summary = summarize_with_ai(combined_data, config, scenario)

    print("\n📝 Writing outputs...")

    # Write outputs (scenario-aware)
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
