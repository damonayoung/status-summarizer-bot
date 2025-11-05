# Architecture Overview

## System Design Philosophy

This project transforms the traditional TPM status reporting workflow from **manual, time-consuming synthesis** to **automated, intelligent analysis**.

### The Traditional Problem

```
TPM Manual Workflow (20-30% of time):
┌─────────────┐
│ Read Jira   │ ──┐
└─────────────┘   │
┌─────────────┐   │
│ Read Slack  │ ──┤    ┌─────────────┐    ┌──────────┐
└─────────────┘   ├───→│ TPM Brain   │───→│  Report  │
┌─────────────┐   │    │ (Manual)    │    │ (Manual) │
│ Read Notes  │ ──┤    └─────────────┘    └──────────┘
└─────────────┘   │
┌─────────────┐   │
│ Read Emails │ ──┘
└─────────────┘
```

### The AI Solution

```
Automated Workflow (< 1 minute):
┌─────────────┐
│ Jira Data   │ ──┐
└─────────────┘   │
┌─────────────┐   │    ┌─────────────┐    ┌──────────┐
│ Slack Data  │ ──┼───→│  AI Engine  │───→│  Report  │
└─────────────┘   │    │  (GPT-4o)   │    │ (Auto)   │
┌─────────────┐   │    └─────────────┘    └──────────┘
│ Notes Data  │ ──┘
└─────────────┘
```

## Architecture Layers

### 1. Data Ingestion Layer (`src/ingestors/`)

**Purpose**: Modular, extensible data source integration

```python
BaseIngestor (Abstract)
    ├── JiraIngestor
    ├── SlackIngestor
    ├── NotesIngestor
    └── [Future: GitHubIngestor, LinearIngestor, etc.]
```

**Key Design Decisions**:
- **Abstract base class**: Ensures consistent interface
- **Independent modules**: Each source is self-contained
- **Format normalization**: Each ingestor converts raw data to standardized text
- **Enable/disable via config**: Sources can be toggled without code changes

**Example Ingestor Flow**:
```python
1. ingest() → Load raw data (JSON, text, API)
2. format_for_prompt() → Convert to AI-friendly text
3. Return structured data → Pass to AI engine
```

### 2. AI Analysis Layer (`src/main_v2.py`)

**Purpose**: Intelligent synthesis and pattern recognition

**Prompt Engineering Strategy**:
- **Multi-source context**: Combine all data sources into unified prompt
- **Structured output**: Request specific report sections
- **Role-based framing**: Position AI as "elite TPM assistant"
- **Actionable focus**: Emphasize insights over raw summarization

**Configuration-Driven**:
```yaml
ai:
  model: "gpt-4o"           # Swappable models
  temperature: 0.3          # Consistency over creativity
  max_tokens: 2000          # Control output length
```

### 3. Output Generation Layer

**Purpose**: Multi-format professional reports

**Supported Formats**:
- **Markdown**: Version-controllable, human-readable
- **HTML**: Rich formatting, executive-ready
- **JSON** (future): Machine-readable for dashboards

**Template System**:
- HTML templates in `templates/`
- Customizable styling and branding
- Responsive design for mobile viewing

### 4. Configuration Layer (`config.yaml`)

**Purpose**: Declarative system behavior

**Key Sections**:
```yaml
data_sources:    # What to ingest
report:          # What to include in output
output:          # How to format results
distribution:    # Where to send reports (future)
advanced:        # AI features (future)
```

**Benefits**:
- No code changes for customization
- Environment-specific configs (dev/prod)
- Easy experimentation with settings

## Data Flow

### Complete Request Flow

```
1. LOAD CONFIG
   config.yaml → Python dict

2. INGEST DATA
   For each enabled source:
   ├── Load raw data (file/API)
   ├── Parse & validate
   └── Format for AI prompt

3. COMBINE SOURCES
   All formatted data → Single text block

4. BUILD PROMPT
   ├── System message (role definition)
   ├── User message (data + instructions)
   └── Configuration (sections, stakeholders)

5. AI ANALYSIS
   OpenAI API → GPT-4o processing → Structured summary

6. GENERATE OUTPUTS
   For each enabled format:
   ├── Markdown → file
   ├── HTML → templated file
   └── (Future: Slack post, email, etc.)

7. RETURN RESULTS
   Print file paths to user
```

### Error Handling Strategy

```python
Level 1: Source-level resilience
   - Individual source failures don't crash system
   - Continue with available sources

Level 2: Validation
   - Check API keys before processing
   - Validate config structure
   - Ensure data sources exist

Level 3: User feedback
   - Clear error messages with fixes
   - Progress indicators during execution
   - Success confirmation with paths
```

## Scalability & Extensibility

### Adding New Data Sources

**Pattern to follow**:

1. Create `src/ingestors/new_source_ingestor.py`:
```python
from .base import BaseIngestor

class NewSourceIngestor(BaseIngestor):
    def get_source_name(self) -> str:
        return "New Source"

    def ingest(self) -> Dict[str, Any]:
        # Load data from file/API
        pass

    def format_for_prompt(self, data: Dict[str, Any]) -> str:
        # Convert to text for AI
        pass
```

2. Add to `config.yaml`:
```yaml
data_sources:
  new_source:
    enabled: true
    path: "sample_data/new_source.json"
```

3. Import in `main_v2.py`:
```python
from ingestors.new_source_ingestor import NewSourceIngestor
```

**Examples of future sources**:
- GitHub Issues/PRs
- Linear tickets
- Notion databases
- Email threads (Gmail API)
- Calendar events
- Confluence pages

### Future Enhancement Opportunities

#### 1. Real-time Integration
Replace file-based ingestion with live API calls:

```python
class LiveJiraIngestor(JiraIngestor):
    def ingest(self):
        jira = JIRA(server=config['jira_url'], ...)
        issues = jira.search_issues('project = ENG')
        return self._normalize(issues)
```

#### 2. Scheduled Execution
Add cron/GitHub Actions for automatic reports:

```yaml
# .github/workflows/weekly-report.yml
on:
  schedule:
    - cron: '0 17 * * 5'  # Every Friday 5pm
```

#### 3. Web Dashboard
Real-time status viewer with Flask/FastAPI:

```python
@app.get("/status")
async def get_status():
    # Run summarizer on-demand
    summary = generate_summary()
    return JSONResponse(summary)
```

#### 4. Slack Bot
Interactive bot for on-demand reports:

```python
@app.slack_command("/status")
def status_command(payload):
    summary = generate_summary()
    return post_to_slack(summary)
```

#### 5. Predictive Analytics
Historical analysis for trend forecasting:

```python
def analyze_trends(weeks=4):
    # Load past summaries
    # Identify patterns
    # Predict risks
    return forecast
```

## Security Considerations

### API Key Management
- ✅ Environment variables (`.env`)
- ✅ `.gitignore` for secrets
- ⚠️ Future: Use secret managers (AWS Secrets, Vault)

### Data Privacy
- Local processing (data doesn't leave OpenAI)
- Sanitize sensitive data before AI processing
- Configurable PII filtering

### Cost Controls
- Token estimation before API calls
- Configurable model selection (cheaper alternatives)
- Rate limiting for scheduled jobs

## Performance Optimization

### Current Performance
- **File ingestion**: < 1 second
- **AI processing**: 5-15 seconds
- **Output generation**: < 1 second
- **Total**: ~20 seconds end-to-end

### Optimization Strategies

1. **Caching**:
```python
@lru_cache
def ingest_jira():
    # Cache for 5 minutes
```

2. **Parallel ingestion**:
```python
import asyncio
results = await asyncio.gather(
    ingest_jira(),
    ingest_slack(),
    ingest_notes()
)
```

3. **Incremental updates**:
- Only process new data since last run
- Store checksums to detect changes

## Testing Strategy

### Unit Tests
```python
# tests/test_ingestors.py
def test_jira_ingestor():
    ingestor = JiraIngestor(config)
    data = ingestor.ingest()
    assert 'issues' in data
```

### Integration Tests
```python
# tests/test_end_to_end.py
def test_full_pipeline():
    summary = main()
    assert os.path.exists('output/summary.md')
```

### Sample Data Tests
- Included realistic sample data
- Tests run without API calls
- Fast feedback loop

## Deployment Options

### 1. Local Execution
```bash
python src/main_v2.py
```

### 2. GitHub Actions (CI/CD)
```yaml
- name: Generate Report
  run: python src/main_v2.py
- name: Commit Report
  run: git add output/ && git commit -m "Weekly report"
```

### 3. Cloud Functions (AWS Lambda)
```python
def lambda_handler(event, context):
    summary = main()
    return {'statusCode': 200, 'body': summary}
```

### 4. Docker Container
```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "src/main_v2.py"]
```

## Conclusion

This architecture prioritizes:
- **Modularity**: Easy to extend and modify
- **Configurability**: Behavior controlled via YAML
- **Maintainability**: Clear separation of concerns
- **Scalability**: Ready for real-time and cloud deployment
- **User Experience**: Fast, reliable, professional output

The system demonstrates how AI can **obsolete manual TPM reporting** while remaining flexible enough to adapt to diverse organizational needs.
