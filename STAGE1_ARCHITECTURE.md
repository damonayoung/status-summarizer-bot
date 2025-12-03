# Stage 1 Context Builder - Architecture Diagram

## Multi-Stage Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  FORTUNE-500-GRADE CYBER PMO REPORTING PIPELINE                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: CONTEXT BUILDER (Pure Data Transformation)                        │
│ Module: src/cyber_context_builder.py                                       │
│ Dependencies: pandas, Python stdlib only                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  INPUT: config.yaml + scenario name                                        │
│    │                                                                        │
│    ├─> Load 6 CSVs:                                                        │
│    │   • risk_financials.csv         → risks DataFrame                    │
│    │   • security_incidents.csv       → incidents DataFrame               │
│    │   • vulnerability_findings.csv   → vulnerabilities DataFrame         │
│    │   • security_controls.csv        → controls DataFrame                │
│    │   • compliance_status.csv        → compliance DataFrame              │
│    │   • security_program_tasks.csv   → tasks DataFrame                   │
│    │                                                                        │
│    ├─> Compute KPIs:                                                       │
│    │   • Incident metrics (MTTD, MTTR, critical count)                    │
│    │   • Vulnerability metrics (open critical, overdue)                   │
│    │   • Control metrics (failing, at risk)                               │
│    │   • Risk exposure (high-risk total, EBITDA impact)                   │
│    │                                                                        │
│    ├─> Compute CISSP Domain Scores (1-5 scale):                           │
│    │   • Algorithm:                                                        │
│    │     - Base score: 3.0                                                │
│    │     - +1 if majority controls are Healthy                            │
│    │     - -1 if majority controls are At Risk                            │
│    │     - -2 if any control is Failing                                   │
│    │     - Clamp to [1.0, 5.0]                                            │
│    │                                                                        │
│    ├─> Identify Compliance Gaps:                                          │
│    │   • Filter Status = "Fail" or "At Risk"                              │
│    │   • Sort by RiskRating (High → Medium → Low)                         │
│    │   • Return top 10                                                    │
│    │                                                                        │
│    ├─> Compute Security Debt:                                             │
│    │   • Open vulnerabilities count                                       │
│    │   • Critical vulnerabilities count                                   │
│    │   • Average age (days)                                               │
│    │   • Overdue count (Age_Days > SLA_Days)                              │
│    │                                                                        │
│    ├─> Compute Program Health:                                            │
│    │   • Task status distribution (In Progress %, Not Started %)          │
│    │   • Blocked tasks count                                              │
│    │   • High-risk tasks open (linked to High/Medium-High risks)          │
│    │                                                                        │
│    └─> Compute Financial Aggregates:                                      │
│        • Total exposure                                                    │
│        • Total EBITDA impact                                               │
│        • Exposure by domain                                                │
│        • EBITDA by driver (revenue, opex, penalties, downtime, other)     │
│                                                                             │
│  OUTPUT: Structured dict with:                                             │
│    {                                                                        │
│      "risks": pd.DataFrame,                                                │
│      "incidents": pd.DataFrame,                                            │
│      "vulnerabilities": pd.DataFrame,                                      │
│      "controls": pd.DataFrame,                                             │
│      "compliance": pd.DataFrame,                                           │
│      "tasks": pd.DataFrame,                                                │
│      "kpis": {...},                                                        │
│      "domain_scores": {...},                                               │
│      "compliance_gaps": [...],                                             │
│      "security_debt": {...},                                               │
│      "program_health": {...},                                              │
│      "financials": {...}                                                   │
│    }                                                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   │ cyber_context dict
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: VISUALIZATION (Chart Generation)                                  │
│ Module: src/cyber_charts.py                                                │
│ Dependencies: matplotlib, seaborn                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  INPUT: cyber_context from Stage 1                                         │
│    │                                                                        │
│    ├─> Generate 10 charts:                                                 │
│    │   1. Risk Matrix (Likelihood × Impact)                               │
│    │   2. Stakeholder Quadrant (Influence × Sentiment)                    │
│    │   3. EBITDA Waterfall (Risk drivers)                                 │
│    │   4. Incident Trends (30-day timeline)                               │
│    │   5. Vulnerability Age Distribution                                  │
│    │   6. Control Health Heatmap                                          │
│    │   7. Compliance Status by Framework                                  │
│    │   8. Program Health Dashboard                                        │
│    │   9. Financial Exposure by Domain                                    │
│    │   10. CISSP Domain Maturity (horizontal bars)                        │
│    │                                                                        │
│    └─> Save charts to output/ directory                                   │
│                                                                             │
│  OUTPUT: chart_paths dict                                                  │
│    {                                                                        │
│      "risk_matrix": "output/risk_matrix.png",                              │
│      "stakeholder_quadrant": "output/stakeholder_quadrant.png",            │
│      "ebitda_waterfall": "output/ebitda_waterfall.png",                    │
│      ...                                                                    │
│    }                                                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   │ cyber_context + chart_paths
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: LLM PROCESSING (AI Summary Generation)                           │
│ Module: src/cyber_prompt_builder.py + OpenAI API                          │
│ Dependencies: openai, src/cyber_prompt_builder                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  INPUT: cyber_context + chart_paths                                        │
│    │                                                                        │
│    ├─> Build data-driven prompt:                                          │
│    │   • Include computed KPIs, domain scores, compliance gaps            │
│    │   • Reference chart paths for visual context                         │
│    │   • Apply 10 prompt rules (data grounding, no redundancy, etc.)      │
│    │   • Enforce word limits (1,000-1,200 total, 100 words/section)       │
│    │                                                                        │
│    ├─> Call OpenAI API:                                                   │
│    │   • Model: gpt-4o                                                    │
│    │   • Temperature: 0.3 (focused, deterministic)                        │
│    │   • Max tokens: 3000                                                 │
│    │                                                                        │
│    └─> Generate 8 sections:                                               │
│        1. Executive Summary (~120 words)                                  │
│        2. Top Security Risks (~100 words)                                 │
│        3. Active Incidents & Response (~100 words)                        │
│        4. Vulnerability Exposure (~100 words)                             │
│        5. Control Gaps & Compliance (~100 words)                          │
│        6. Financial Impact (EBITDA) (~100 words)                          │
│        7. Program Health (~100 words)                                     │
│        7b. CISSP Domain Maturity (~100 words)                             │
│        8. Decisions & Next 30 Days (~200 words)                           │
│                                                                             │
│  OUTPUT: summary markdown string                                           │
│    """                                                                      │
│    # Executive Summary                                                     │
│    [8 lines: headline + KPI row + 3 decisions]                             │
│                                                                             │
│    ## Top Security Risks                                                   │
│    [5-7 lines with specific RiskIDs and $ amounts]                         │
│    ...                                                                      │
│    """                                                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   │ summary + cyber_context + chart_paths
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: OUTPUT GENERATION (HTML/Markdown/PDF)                            │
│ Module: templates/executive_report.html + Jinja2                          │
│ Dependencies: jinja2, weasyprint (for PDF)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  INPUT: summary + cyber_context + chart_paths                              │
│    │                                                                        │
│    ├─> Render HTML template:                                              │
│    │   • Inject LLM summary markdown (converted to HTML)                  │
│    │   • Embed charts as base64 images                                    │
│    │   • Add interactive elements (clickable charts, tooltips)            │
│    │   • Apply CSS styling (professional, board-ready)                    │
│    │                                                                        │
│    ├─> Write outputs:                                                     │
│    │   • output/cyber_pmo_report.html                                     │
│    │   • output/cyber_pmo_report.md                                       │
│    │   • output/cyber_pmo_report.pdf (optional)                           │
│    │                                                                        │
│    └─> Display file paths to user                                         │
│                                                                             │
│  OUTPUT: File paths                                                        │
│    • HTML: /path/to/output/cyber_pmo_report.html                          │
│    • Markdown: /path/to/output/cyber_pmo_report.md                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
config.yaml
    │
    ├─> scenario: "sentient_cyber_pmo"
    │
    ├─> data_sources:
    │   ├─> risk_financials: "sample_data/day3_cyber/risk_financials.csv"
    │   ├─> security_incidents: "sample_data/day3_cyber/security_incidents.csv"
    │   ├─> vulnerability_findings: "sample_data/day3_cyber/vulnerability_findings.csv"
    │   ├─> security_controls: "sample_data/day3_cyber/security_controls.csv"
    │   ├─> compliance_status: "sample_data/day3_cyber/compliance_status.csv"
    │   └─> security_program_tasks: "sample_data/day3_cyber/security_program_tasks.csv"
    │
    ▼
[STAGE 1: build_cyber_context()]
    │
    ├─> Load CSVs into pandas DataFrames
    ├─> Compute KPIs (incidents, vulnerabilities, controls, risks)
    ├─> Score CISSP domains (1-5 scale based on control health)
    ├─> Identify compliance gaps (top 10 high-risk failures)
    ├─> Compute security debt (vuln age, overdue count)
    ├─> Compute program health (task status, blockers)
    └─> Aggregate financials (exposure, EBITDA by driver)
    │
    ▼
cyber_context = {
    risks: DataFrame,
    incidents: DataFrame,
    vulnerabilities: DataFrame,
    controls: DataFrame,
    compliance: DataFrame,
    tasks: DataFrame,
    kpis: {...},
    domain_scores: {...},
    compliance_gaps: [...],
    security_debt: {...},
    program_health: {...},
    financials: {...}
}
    │
    ▼
[STAGE 2: generate_all_cyber_charts(cyber_context)]
    │
    ├─> Generate 10 matplotlib/seaborn charts
    └─> Save to output/ directory
    │
    ▼
chart_paths = {
    "risk_matrix": "output/risk_matrix.png",
    "domain_maturity": "output/domain_maturity.png",
    ...
}
    │
    ▼
[STAGE 3: summarize_cyber_program_with_ai(cyber_context)]
    │
    ├─> Build data-driven prompt with KPIs and domain scores
    ├─> Call OpenAI API (gpt-4o, temp=0.3)
    └─> Generate 8-section markdown summary (1,000-1,200 words)
    │
    ▼
summary = """
# Executive Summary
[8 lines: headline + KPI row + 3 decisions]

## Top Security Risks
[5-7 lines with RiskIDs and $ amounts]
...
"""
    │
    ▼
[STAGE 4: write_html_output(summary, cyber_context, chart_paths)]
    │
    ├─> Render Jinja2 template
    ├─> Embed charts as base64
    ├─> Apply CSS styling
    └─> Write HTML and Markdown files
    │
    ▼
OUTPUT FILES:
    • output/cyber_pmo_report.html (interactive, board-ready)
    • output/cyber_pmo_report.md (plain text backup)
```

## Function Call Hierarchy

```
main()
  │
  ├─> load_config("config.yaml")
  │   └─> Returns: config dict
  │
  ├─> [STAGE 1] build_cyber_context(config, "sentient_cyber_pmo")
  │   │
  │   ├─> _load_csv("risk_financials") → risks DataFrame
  │   ├─> _load_csv("security_incidents") → incidents DataFrame
  │   ├─> _load_csv("vulnerability_findings") → vulnerabilities DataFrame
  │   ├─> _load_csv("security_controls") → controls DataFrame
  │   ├─> _load_csv("compliance_status") → compliance DataFrame
  │   ├─> _load_csv("security_program_tasks") → tasks DataFrame
  │   │
  │   ├─> _compute_kpis(context)
  │   │   ├─> Calculate incident metrics (MTTD, MTTR, critical count)
  │   │   ├─> Calculate vulnerability metrics (open, overdue)
  │   │   ├─> Calculate control metrics (failing, at risk)
  │   │   └─> Calculate risk exposure (high-risk total, EBITDA)
  │   │
  │   ├─> _compute_domain_scores(context)
  │   │   ├─> Group controls by CISSP domain
  │   │   ├─> Apply scoring algorithm (base 3, +/-1/-2)
  │   │   └─> Clamp to [1, 5]
  │   │
  │   ├─> _compute_compliance_gaps(context)
  │   │   ├─> Filter Status = "Fail" or "At Risk"
  │   │   └─> Sort by RiskRating, return top 10
  │   │
  │   ├─> _compute_security_debt(context)
  │   │   ├─> Count open vulnerabilities
  │   │   ├─> Calculate average age
  │   │   └─> Count overdue (Age > SLA)
  │   │
  │   ├─> _compute_program_health(context)
  │   │   ├─> Calculate task status distribution
  │   │   ├─> Count blocked tasks
  │   │   └─> Count high-risk tasks
  │   │
  │   └─> _compute_financials(context)
  │       ├─> Sum total exposure
  │       ├─> Sum total EBITDA impact
  │       ├─> Group by domain
  │       └─> Categorize by driver (_categorize_ebitda_driver)
  │           ├─> "revenue" if keywords ["revenue", "sales", "customer"]
  │           ├─> "opex" if keywords ["opex", "operational", "cost"]
  │           ├─> "penalties" if keywords ["penalty", "fine", "regulatory"]
  │           ├─> "downtime" if keywords ["downtime", "outage"]
  │           └─> "other" otherwise
  │
  ├─> [STAGE 2] generate_all_cyber_charts(cyber_context)
  │   ├─> generate_risk_matrix_chart()
  │   ├─> generate_stakeholder_quadrant_chart()
  │   ├─> generate_ebitda_waterfall_chart()
  │   ├─> generate_incident_trends_chart()
  │   ├─> generate_vulnerability_age_chart()
  │   ├─> generate_control_health_heatmap()
  │   ├─> generate_compliance_status_chart()
  │   ├─> generate_program_health_dashboard()
  │   ├─> generate_financial_exposure_chart()
  │   └─> generate_domain_maturity_chart()  # NEW - CISSP domains
  │
  ├─> [STAGE 3] summarize_cyber_program_with_ai(cyber_context)
  │   ├─> build_data_driven_cyber_prompt(cyber_context)
  │   │   ├─> Include KPIs in prompt
  │   │   ├─> Include domain scores in prompt
  │   │   ├─> Include compliance gaps in prompt
  │   │   ├─> Apply 10 prompt rules
  │   │   └─> Enforce word limits
  │   │
  │   └─> client.chat.completions.create(
  │           model="gpt-4o",
  │           messages=[{"role": "system", "content": prompt}],
  │           temperature=0.3,
  │           max_tokens=3000
  │       )
  │
  └─> [STAGE 4] write_html_output(summary, config, scenario, cyber_context)
      ├─> Load template: templates/executive_report.html
      ├─> Render Jinja2 with:
      │   ├─> summary (markdown → HTML via markdown.markdown())
      │   ├─> chart_paths (base64 encoded)
      │   ├─> domain_scores table
      │   ├─> compliance_gaps table
      │   └─> CSS styling
      │
      └─> Write files:
          ├─> output/cyber_pmo_report.html
          └─> output/cyber_pmo_report.md
```

## Key Design Principles

### 1. **Separation of Concerns**
- Each stage has a single responsibility
- Stages can be tested independently
- Easy to swap implementations (e.g., different chart library)

### 2. **Pure Functions**
- Stage 1 is a pure function (no side effects beyond file I/O)
- Same inputs always produce same outputs
- No global state, no LLM calls

### 3. **Type Safety**
- Full type annotations throughout
- Clear input/output contracts
- Easier to catch bugs at development time

### 4. **Error Handling**
- Try-except blocks around CSV loading
- Graceful degradation (empty DataFrames if CSV fails)
- Detailed error logging

### 5. **Extensibility**
- Easy to add new KPIs (just add to `_compute_kpis()`)
- Easy to add new CISSP domains (just update `domain_scores`)
- Easy to add new chart types (just add to Stage 2)

### 6. **Performance**
- Stages 2 and 3 can run in parallel (independent)
- Pandas vectorized operations (faster than loops)
- Charts saved to disk (cached for reuse)

---

**Last Updated**: December 2, 2025
**Version**: 1.0
**Status**: ✅ Production-Ready
