# 🤖 Status Summarizer Bot

> **AI-powered TPM status report generator that obsoletes manual status reporting**
> Transforms project updates into autonomous, living systems that monitor, report, and adapt.

[![OpenAI](https://img.shields.io/badge/Powered%20by-OpenAI%20GPT--4-412991.svg)](https://openai.com/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 💡 The Problem

**Conventional wisdom**: TPMs spend 20-30% of their week crafting updates, summarizing meetings, and manually consolidating data from Jira, Slack, and Notion.

**The challenge**: Why should humans be the reporting layer of a system when AI can already see, summarize, and forecast?

**Our thesis**: AI will obsolete the status report by creating **dynamic, real-time program narratives** — accessible anytime by any stakeholder.

Instead of manually describing progress, this project builds a system that understands and communicates it.

## ⚡ What It Does

An intelligent AI agent that:

- ✅ **Ingests from multiple sources**: Meeting notes, Jira tickets, and Slack threads
- ✅ **Synthesizes intelligently**: Uses OpenAI's GPT-4/GPT-4o to identify patterns, risks, and priorities
- ✅ **Generates executive-ready reports**: At-a-glance dashboards, risk tables, and decision summaries
- ✅ **Visual & scannable**: Color-coded status (🟢🟠🔴), trend indicators (▲▼), and emoji markers
- ✅ **Decision-focused**: Highlights critical risks and surfaces required executive actions
- 🔄 **Supports distribution**: Ready for Slack posting and email delivery (configurable)
- 📊 **Real-time capable**: Built to support dynamic, on-demand status updates

### 🎯 Executive Format Features

The bot now generates **2-minute readable** status reports with:

1. **At-a-Glance Dashboard** - Instant program health overview (🟢🟠🔴)
2. **Max 3 Highlights** - Business outcomes, not technical details
3. **Risk Table** - Severity-coded with owners and ETAs
4. **Key Wins** - Emoji-coded achievements (🚀🔒📉⚙️)
5. **Stakeholder Pulse** - Sentiment analysis (✅⚙️⚠️🔥)
6. **Decisions Needed** - Explicit executive action items
7. **Metrics Snapshot** - Trends with indicators (▲▼)

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- OpenAI API key ([get one here](https://platform.openai.com/api-keys))

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/status-summarizer-bot.git
cd status-summarizer-bot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### Run It

```bash
# Run with multi-source ingestion
python src/main_v2.py

# Or run the simple version (meeting notes only)
python src/main.py
```

## 📁 Project Structure

```
status-summarizer-bot/
├── src/
│   ├── main.py              # Simple version (meeting notes only)
│   ├── main_v2.py           # Multi-source version ⭐
│   └── ingestors/           # Modular data ingestion
│       ├── base.py          # Base ingestor class
│       ├── jira_ingestor.py # Jira ticket ingestion
│       ├── slack_ingestor.py# Slack thread ingestion
│       └── notes_ingestor.py# Meeting notes ingestion
├── sample_data/
│   ├── meeting_notes.txt    # Sample TPM meeting notes
│   ├── jira_export.json     # Sample Jira tickets
│   └── slack_threads.json   # Sample Slack conversations
├── templates/
│   └── executive_report.html# HTML report template
├── output/                  # Generated reports
├── config.yaml             # Configuration file
├── .env                    # Environment variables (API keys)
└── README.md
```

## 🎯 Features

### v2.0 - Multi-Source Intelligence

- **📥 Multi-Source Ingestion**
  - Meeting notes (plain text/markdown)
  - Jira tickets (JSON export)
  - Slack threads (JSON export)
  - Extensible architecture for adding more sources

- **🧠 Intelligent Analysis**
  - Pattern recognition across sources
  - Risk identification and prioritization
  - Action item extraction with owners
  - Stakeholder sentiment analysis
  - Metric tracking and trend analysis

- **📊 Professional Output**
  - Executive-ready Markdown reports
  - Beautiful HTML reports with styling
  - Configurable report sections
  - Customizable templates

- **⚙️ Highly Configurable**
  - YAML-based configuration
  - Enable/disable data sources
  - Customize report sections
  - Control AI parameters
  - Multiple output formats

### Roadmap (Future Enhancements)

- [ ] **Live Integrations**
  - Direct Jira API integration
  - Real-time Slack bot
  - GitHub project sync
  - Linear integration

- [ ] **Distribution Channels**
  - Slack webhook posting
  - Email delivery (SMTP)
  - Notion page creation
  - Teams integration

- [ ] **Real-time Dashboard**
  - Web-based status viewer
  - Live refresh capabilities
  - Interactive filtering
  - Historical trend visualization

- [ ] **Advanced AI Features**
  - Predictive risk forecasting
  - Automated action item tracking
  - Sentiment trend analysis
  - Custom insight generation

## 📝 Configuration

Edit `config.yaml` to customize:

```yaml
# Enable/disable data sources
data_sources:
  meeting_notes:
    enabled: true
    path: "sample_data/meeting_notes.txt"
  jira:
    enabled: true
    path: "sample_data/jira_export.json"
  slack:
    enabled: true
    path: "sample_data/slack_threads.json"

# AI model settings
ai:
  model: "gpt-4o"  # or gpt-4, gpt-4o-mini
  temperature: 0.3

# Report customization
report:
  title: "Weekly Program Status"
  sections:
    - highlights
    - risks_and_mitigations
    - action_items
    - stakeholder_pulse
    - metrics
    - next_week_priorities

# Output formats
output:
  formats:
    markdown:
      enabled: true
    html:
      enabled: true
```

## 📊 Sample Output

The bot generates comprehensive reports including:

- **🎯 Highlights**: Key achievements and wins
- **⚠️ Risks & Mitigations**: Categorized by severity with mitigation plans
- **✅ Action Items**: Specific tasks with owners and deadlines
- **👥 Stakeholder Pulse**: Perspectives from Engineering, Product, Sales, etc.
- **📈 Metrics**: Sprint velocity, bug counts, deployment frequency, NPS
- **🔮 Next Week Priorities**: Forward-looking action items

[View sample HTML output](output/weekly_summary_2025-10-24.html) | [View sample Markdown](output/weekly_summary_2025-10-24.md)

## 🔧 How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA SOURCES                             │
├─────────────────────────────────────────────────────────────┤
│  Meeting Notes  │  Jira Tickets  │  Slack Threads          │
└────────┬────────┴────────┬───────┴──────────┬──────────────┘
         │                 │                   │
         └─────────────────┼───────────────────┘
                           │
                    ┌──────▼──────┐
                    │  INGESTORS  │
                    │  (Modular)  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ AI ANALYZER │
                    │  (GPT-4o)   │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
    │Markdown │      │  HTML   │      │  Slack  │
    │ Report  │      │ Report  │      │  Post   │
    └─────────┘      └─────────┘      └─────────┘
```

## 🧪 Example Use Cases

1. **Weekly Executive Updates**: Auto-generate Friday status reports
2. **Sprint Reviews**: Consolidate Jira + Slack into sprint summaries
3. **Incident Reports**: Quickly synthesize post-mortems from multiple sources
4. **Stakeholder Briefings**: Create role-specific views for different audiences
5. **Program Health Checks**: Real-time status for leadership reviews

## 🛠️ Development

### Adding a New Data Source

1. Create a new ingestor in `src/ingestors/`:

```python
from .base import BaseIngestor

class MyIngestor(BaseIngestor):
    def get_source_name(self) -> str:
        return "My Source"

    def ingest(self) -> Dict[str, Any]:
        # Your ingestion logic
        pass

    def format_for_prompt(self, data: Dict[str, Any]) -> str:
        # Format data for AI prompt
        pass
```

2. Add configuration to `config.yaml`
3. Import and use in `main_v2.py`

### Testing

```bash
# Test with sample data
python src/main_v2.py

# Test individual components
python -m pytest tests/
```

## 💰 Cost Considerations

- **GPT-4o**: ~$0.01-0.05 per report (depending on data volume)
- **GPT-4o-mini**: ~$0.001-0.005 per report (cheaper alternative)
- **GPT-3.5-turbo**: ~$0.0005-0.002 per report (budget option)

Estimated monthly cost for weekly reports: **$1-5/month**

## 🤝 Contributing

Contributions welcome! Areas for improvement:

- Additional data source integrations
- Enhanced AI prompts for better insights
- Real-time dashboard implementation
- Distribution channel integrations
- Testing and documentation

## 📜 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- Powered by OpenAI's GPT-4/GPT-4o
- Inspired by the need to free TPMs from repetitive reporting
- Built to demonstrate AI's potential in program management

---

**Made with ❤️ by a TPM who was tired of writing status reports**

*"Why should humans be the reporting layer when AI can do it better?"*
