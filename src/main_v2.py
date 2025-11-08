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


def ingest_all_sources(config: Dict[str, Any]) -> str:
    """
    Ingest data from all enabled sources and combine into one text.

    Args:
        config: Application configuration

    Returns:
        Combined text from all data sources
    """
    data_sources = config.get("data_sources", {})
    combined_text = []

    print("\n📥 Ingesting data from sources...")

    # Meeting Notes
    if data_sources.get("meeting_notes", {}).get("enabled", False):
        try:
            notes_ingestor = NotesIngestor(data_sources["meeting_notes"])
            notes_data = notes_ingestor.ingest()
            formatted = notes_ingestor.format_for_prompt(notes_data)
            combined_text.append(formatted)
            print(f"  ✓ {notes_ingestor.get_source_name()}")
        except Exception as e:
            print(f"  ✗ Meeting Notes failed: {e}")

    # Jira
    if data_sources.get("jira", {}).get("enabled", False):
        try:
            jira_ingestor = JiraIngestor(data_sources["jira"])
            jira_data = jira_ingestor.ingest()
            formatted = jira_ingestor.format_for_prompt(jira_data)
            combined_text.append(formatted)
            print(f"  ✓ {jira_ingestor.get_source_name()}: {len(jira_data.get('issues', []))} issues")
        except Exception as e:
            print(f"  ✗ Jira failed: {e}")

    # Slack
    if data_sources.get("slack", {}).get("enabled", False):
        try:
            slack_ingestor = SlackIngestor(data_sources["slack"])
            slack_data = slack_ingestor.ingest()
            formatted = slack_ingestor.format_for_prompt(slack_data)
            combined_text.append(formatted)
            total_threads = sum(len(ch.get("threads", [])) for ch in slack_data.get("channels", []))
            print(f"  ✓ {slack_ingestor.get_source_name()}: {total_threads} threads")
        except Exception as e:
            print(f"  ✗ Slack failed: {e}")

    if not combined_text:
        raise ValueError("No data sources were successfully ingested!")

    return "\n\n" + "="*80 + "\n\n".join(combined_text)


def build_prompt(combined_data: str, config: Dict[str, Any]) -> str:
    """
    Build the AI prompt based on configuration.

    Args:
        combined_data: Combined text from all sources
        config: Application configuration

    Returns:
        Formatted prompt for the AI
    """
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


def summarize_with_ai(combined_data: str, config: Dict[str, Any]) -> str:
    """
    Call OpenAI to generate the summary.

    Args:
        combined_data: Combined text from all sources
        config: Application configuration

    Returns:
        AI-generated summary
    """
    prompt = build_prompt(combined_data, config)

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


def write_markdown_output(summary: str, config: Dict[str, Any]) -> str:
    """Write summary to Markdown file."""
    md_config = config.get("output", {}).get("formats", {}).get("markdown", {})

    if not md_config.get("enabled", True):
        return None

    output_dir = md_config.get("path", "output")
    os.makedirs(output_dir, exist_ok=True)

    today = datetime.date.today().strftime("%Y-%m-%d")
    filename_pattern = md_config.get("filename_pattern", "weekly_summary_{date}.md")
    filename = filename_pattern.replace("{date}", today)
    filepath = os.path.join(output_dir, filename)

    report_title = config.get("report", {}).get("title", "Weekly Program Status")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {report_title} ({today})\n\n")
        f.write(summary)
        f.write(f"\n\n---\n")
        f.write(f"*Generated automatically by Status Summarizer Bot | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
        f.write("*Sources: Meeting Notes, Jira, Slack*\n")

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


def write_html_output(summary: str, config: Dict[str, Any]) -> str:
    """Write summary to HTML file using template."""
    html_config = config.get("output", {}).get("formats", {}).get("html", {})

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
    report_title = config.get("report", {}).get("title", "Weekly Program Status")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create Jinja2 template and render
    template = Template(template_str)
    html_output = template.render(
        title=report_title,
        date=today,
        content=html_content,
        timestamp=timestamp,
        # Default KPI values (can be extracted from summary in future)
        kpi_delivery_value='Stable',
        kpi_delivery_trend='Trajectory ↗',
        kpi_velocity_value='Healthy',
        kpi_velocity_trend='Sustained ↑',
        kpi_cost_value='Caution',
        kpi_cost_trend='Infra ↑'
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_output)

    return filepath


def main():
    """Main execution flow."""
    print("=" * 80)
    print("🤖 STATUS SUMMARIZER BOT v2.0")
    print("=" * 80)

    # Load configuration
    config = load_config()

    # Ingest from all sources
    combined_data = ingest_all_sources(config)

    # Generate AI summary
    summary = summarize_with_ai(combined_data, config)

    print("\n📝 Writing outputs...")

    # Write outputs
    outputs = []

    md_path = write_markdown_output(summary, config)
    if md_path:
        outputs.append(f"Markdown: {md_path}")

    html_path = write_html_output(summary, config)
    if html_path:
        outputs.append(f"HTML: {html_path}")

    # Display results
    print("\n✅ Summary generated successfully!")
    for output in outputs:
        print(f"   📄 {output}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
