# Stage 3 Template Integration Guide

## Overview

This guide shows how to update the HTML template and rendering code to use the new multi-step narrative structure from Stage 3.

## Current State

**Current Flow**:
```python
# main_v2.py
summary = summarize_cyber_program_with_ai(cyber_context, config, scenario)  # Single markdown string
html_path = write_html_output(summary, config, scenario, cyber_context=cyber_context)
```

**Template** (`templates/executive_report.html`):
- Line 4136: `{% elif scenario == 'sentient_cyber_pmo' %}`
- Expects single `summary` variable with full markdown
- Has pre-built sections for KPIs, charts, EBITDA waterfall
- Currently ~1400 lines of hardcoded layout

## New Approach

### 1. Update main() to use Stage 2 + Stage 3

**File**: `src/main_v2.py` lines 4987-5028

```python
elif scenario == "sentient_cyber_pmo":
    # === STAGE 1: Context Builder ===
    cyber_context = build_cyber_risk_program_context(config, scenario)

    # === STAGE 2: Prioritization ===
    prioritized = prioritize_cyber_context(cyber_context)

    # === STAGE 3: LLM Narrative Generation ===
    narrative = generate_cyber_narrative(prioritized, config)

    # Assemble final markdown for compatibility
    summary = f"""# Executive Summary
{narrative['executive_summary']}

## Cyber Risk Posture
{narrative['sections']['risk_posture']}

## Threat & Incident Trends
{narrative['sections']['threats_and_incidents']}

## Vulnerability & Security Debt
{narrative['sections']['vulnerabilities_and_debt']}

## Controls & Compliance (CISSP Alignment)
{narrative['sections']['controls_and_compliance']}

## Program Execution & Governance
{narrative['sections']['program_execution']}

## Financial Impact (EBITDA)
{narrative['sections']['financial_impact']}

## Decisions & Next 30 Days
{narrative['decisions']}
"""

    # === STAGE 4: Output Generation ===
    # Pass both narrative and prioritized to template
    html_path = write_html_output(
        summary=summary,  # For backward compatibility
        config=config,
        scenario=scenario,
        cyber_context=cyber_context,  # Existing charts/data
        narrative=narrative,  # NEW: Stage 3 output
        prioritized=prioritized  # NEW: Stage 2 output
    )
```

### 2. Update write_html_output() signature

**File**: `src/main_v2.py` line 4192

**Before**:
```python
def write_html_output(summary: str, config: Dict[str, Any], scenario: str = None,
                     risk_context: Optional[Dict[str, Any]] = None,
                     ebitda_chart_path: Optional[str] = None,
                     cyber_context: Optional[Dict[str, Any]] = None) -> str:
```

**After**:
```python
def write_html_output(summary: str, config: Dict[str, Any], scenario: str = None,
                     risk_context: Optional[Dict[str, Any]] = None,
                     ebitda_chart_path: Optional[str] = None,
                     cyber_context: Optional[Dict[str, Any]] = None,
                     narrative: Optional[Dict[str, Any]] = None,  # NEW
                     prioritized: Optional[Dict[str, Any]] = None) -> str:  # NEW
```

### 3. Pass narrative and prioritized to template

**File**: `src/main_v2.py` ~line 4300 (inside write_html_output)

Find the template.render() call and add:

```python
# Inside write_html_output(), around line 4300:
html_output = template.render(
    # ... existing variables ...
    scenario=scenario,
    cyber_context=cyber_context,
    # NEW: Add narrative and prioritized
    narrative=narrative,
    prioritized=prioritized
)
```

### 4. Create New Template Section for Narrative-First Layout

**File**: `templates/executive_report.html`

**Option A**: Add inside existing `{% elif scenario == 'sentient_cyber_pmo' %}` block (recommended for minimal changes)

**Location**: After line 4224 (after KPI strip, before existing charts)

```html
<!-- NEW: Narrative-Driven Executive Report (if narrative is provided) -->
{% if narrative %}
<section class="narrative-report">
  <!-- Hero Panel: Executive Summary -->
  <div class="hero-panel" style="background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); color: white; padding: 40px; border-radius: 12px; margin-bottom: 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.15);">
    <h1 style="font-size: 28px; font-weight: 700; margin-bottom: 16px; color: white;">Cyber PMO – Executive Security Briefing</h1>
    <div class="executive-summary-content" style="font-size: 16px; line-height: 1.8; color: rgba(255,255,255,0.95);">
      {{ narrative.executive_summary|safe }}
    </div>
  </div>

  <!-- KPI Tiles from Prioritized Context -->
  <div class="kpi-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 40px;">
    {% if prioritized and prioritized.kpis %}
    <div class="kpi-tile" style="background: white; padding: 24px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-left: 4px solid #dc2626;">
      <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; font-weight: 600; margin-bottom: 8px;">Total EBITDA Impact</div>
      <div style="font-size: 28px; font-weight: 700; color: #dc2626;">${{ (prioritized.kpis.total_ebitda_impact / 1000000)|round(1) }}M</div>
    </div>
    <div class="kpi-tile" style="background: white; padding: 24px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-left: 4px solid #f59e0b;">
      <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; font-weight: 600; margin-bottom: 8px;">Critical Vulns Overdue</div>
      <div style="font-size: 28px; font-weight: 700; color: #f59e0b;">{{ prioritized.kpis.overdue_vulns_count }}</div>
    </div>
    <div class="kpi-tile" style="background: white; padding: 24px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-left: 4px solid #10b981;">
      <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; font-weight: 600; margin-bottom: 8px;">MTTR (hours)</div>
      <div style="font-size: 28px; font-weight: 700; color: #10b981;">{{ prioritized.kpis.avg_mttr_hours|round(1) }}</div>
    </div>
    <div class="kpi-tile" style="background: white; padding: 24px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-left: 4px solid #3b82f6;">
      <div style="font-size: 12px; color: #6b7280; text-transform: uppercase; font-weight: 600; margin-bottom: 8px;">Failing Controls</div>
      <div style="font-size: 28px; font-weight: 700; color: #3b82f6;">{{ prioritized.kpis.failing_controls_count }}</div>
    </div>
    {% endif %}
  </div>

  <!-- Section 1: Risk Posture -->
  <section class="narrative-section" style="background: white; padding: 32px; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <h2 style="font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 20px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px;">Cyber Risk Posture</h2>
    {% if cyber_context and cyber_context.chart_paths and cyber_context.chart_paths.risk_matrix %}
    <img src="{{ cyber_context.chart_paths.risk_matrix }}" alt="Risk Matrix" style="max-width: 100%; height: auto; margin-bottom: 20px; border-radius: 4px;" />
    {% endif %}
    <div class="narrative-content" style="font-size: 15px; line-height: 1.8; color: #374151;">
      {{ narrative.sections.risk_posture|safe }}
    </div>
  </section>

  <!-- Section 2: Threats & Incidents -->
  <section class="narrative-section" style="background: white; padding: 32px; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <h2 style="font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 20px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px;">Threat & Incident Trends</h2>
    {% if cyber_context and cyber_context.chart_paths and cyber_context.chart_paths.incident_trends %}
    <img src="{{ cyber_context.chart_paths.incident_trends }}" alt="Incident Trends" style="max-width: 100%; height: auto; margin-bottom: 20px; border-radius: 4px;" />
    {% endif %}
    <div class="narrative-content" style="font-size: 15px; line-height: 1.8; color: #374151;">
      {{ narrative.sections.threats_and_incidents|safe }}
    </div>
  </section>

  <!-- Section 3: Vulnerabilities & Debt -->
  <section class="narrative-section" style="background: white; padding: 32px; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <h2 style="font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 20px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px;">Vulnerability & Security Debt</h2>
    {% if cyber_context and cyber_context.chart_paths and cyber_context.chart_paths.vulnerability_age %}
    <img src="{{ cyber_context.chart_paths.vulnerability_age }}" alt="Vulnerability Age Distribution" style="max-width: 100%; height: auto; margin-bottom: 20px; border-radius: 4px;" />
    {% endif %}
    <div class="narrative-content" style="font-size: 15px; line-height: 1.8; color: #374151;">
      {{ narrative.sections.vulnerabilities_and_debt|safe }}
    </div>
  </section>

  <!-- Section 4: Controls & Compliance -->
  <section class="narrative-section" style="background: white; padding: 32px; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <h2 style="font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 20px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px;">Controls & Compliance (CISSP Alignment)</h2>
    {% if cyber_context and cyber_context.chart_paths and cyber_context.chart_paths.control_health %}
    <img src="{{ cyber_context.chart_paths.control_health }}" alt="Control Health Heatmap" style="max-width: 100%; height: auto; margin-bottom: 20px; border-radius: 4px;" />
    {% endif %}
    <div class="narrative-content" style="font-size: 15px; line-height: 1.8; color: #374151;">
      {{ narrative.sections.controls_and_compliance|safe }}
    </div>
  </section>

  <!-- Section 5: Program Execution -->
  <section class="narrative-section" style="background: white; padding: 32px; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <h2 style="font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 20px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px;">Program Execution & Governance</h2>
    {% if cyber_context and cyber_context.chart_paths and cyber_context.chart_paths.program_health %}
    <img src="{{ cyber_context.chart_paths.program_health }}" alt="Program Health Dashboard" style="max-width: 100%; height: auto; margin-bottom: 20px; border-radius: 4px;" />
    {% endif %}
    <div class="narrative-content" style="font-size: 15px; line-height: 1.8; color: #374151;">
      {{ narrative.sections.program_execution|safe }}
    </div>
  </section>

  <!-- Section 6: Financial Impact -->
  <section class="narrative-section" style="background: white; padding: 32px; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <h2 style="font-size: 22px; font-weight: 700; color: #1e293b; margin-bottom: 20px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px;">Financial Impact (EBITDA)</h2>
    {% if cyber_context and cyber_context.chart_paths and cyber_context.chart_paths.ebitda_waterfall %}
    <img src="{{ cyber_context.chart_paths.ebitda_waterfall }}" alt="EBITDA Waterfall" style="max-width: 100%; height: auto; margin-bottom: 20px; border-radius: 4px;" />
    {% endif %}
    <div class="narrative-content" style="font-size: 15px; line-height: 1.8; color: #374151;">
      {{ narrative.sections.financial_impact|safe }}
    </div>
  </section>

  <!-- Section 7: Decisions & Next 30 Days -->
  <section class="narrative-section" style="background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); padding: 32px; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); border: 2px solid #fbbf24;">
    <h2 style="font-size: 22px; font-weight: 700; color: #92400e; margin-bottom: 20px;">🎯 Decisions & Next 30 Days</h2>
    <div class="narrative-content" style="font-size: 15px; line-height: 1.8; color: #78350f;">
      {{ narrative.decisions|safe }}
    </div>
  </section>
</section>
{% else %}
<!-- Fallback: Use existing template layout if narrative not provided -->
```

**Option B**: Create entirely new scenario block (cleaner but requires more changes)

Add after line 5510 (end of file), before final `</body></html>`:

```html
{% elif scenario == 'sentient_cyber_pmo_v2' %}
<!-- Stage 3 Narrative-Driven Layout -->
[... same content as Option A ...]
{% endif %}
```

## Migration Path

### Phase 1: Add Support (Backward Compatible)
1. Update `write_html_output()` signature to accept `narrative` and `prioritized` (optional params)
2. Add `{% if narrative %}` block to template (Option A above)
3. Keep existing flow working with single `summary` markdown

### Phase 2: Enable Stage 2 + Stage 3 (Opt-In)
1. Uncomment Stage 2 + Stage 3 in main()
2. Pass `narrative` and `prioritized` to `write_html_output()`
3. Template automatically uses new layout when `narrative` is present

### Phase 3: Full Migration (Future)
1. Remove old single-markdown flow
2. Simplify template by removing hardcoded sections
3. Deprecate `summarize_cyber_program_with_ai()` in favor of `generate_cyber_narrative()`

## Example: Complete Integration Code

### main_v2.py (Updated)

```python
elif scenario == "sentient_cyber_pmo":
    # === STAGE 1 ===
    cyber_context = build_cyber_risk_program_context(config, scenario)

    # === STAGE 2 ===
    prioritized = prioritize_cyber_context(cyber_context)

    # === STAGE 3 ===
    narrative = generate_cyber_narrative(prioritized, config)

    # Assemble markdown (for backward compatibility / markdown output)
    summary = f"""# Executive Summary
{narrative['executive_summary']}

## Cyber Risk Posture
{narrative['sections']['risk_posture']}

## Threat & Incident Trends
{narrative['sections']['threats_and_incidents']}

## Vulnerability & Security Debt
{narrative['sections']['vulnerabilities_and_debt']}

## Controls & Compliance (CISSP Alignment)
{narrative['sections']['controls_and_compliance']}

## Program Execution & Governance
{narrative['sections']['program_execution']}

## Financial Impact (EBITDA)
{narrative['sections']['financial_impact']}

## Decisions & Next 30 Days
{narrative['decisions']}
"""

    # === STAGE 4: Outputs ===
    print("\n📝 Writing outputs...")
    outputs = []

    # Markdown output
    md_path = write_markdown_output(summary, config, scenario)
    if md_path:
        outputs.append(f"Markdown: {md_path}")

    # HTML output (with narrative structure)
    html_path = write_html_output(
        summary=summary,
        config=config,
        scenario=scenario,
        cyber_context=cyber_context,
        narrative=narrative,  # NEW
        prioritized=prioritized  # NEW
    )
    if html_path:
        outputs.append(f"HTML: {html_path}")
```

### write_html_output() (Updated)

```python
def write_html_output(
    summary: str,
    config: Dict[str, Any],
    scenario: str = None,
    risk_context: Optional[Dict[str, Any]] = None,
    ebitda_chart_path: Optional[str] = None,
    cyber_context: Optional[Dict[str, Any]] = None,
    narrative: Optional[Dict[str, Any]] = None,  # NEW
    prioritized: Optional[Dict[str, Any]] = None  # NEW
) -> str:
    """Write HTML output with optional narrative structure."""

    # ... existing code ...

    # Around line 4300, in template.render():
    html_output = template.render(
        title=title,
        date=date,
        summary=summary_html,  # Converted markdown → HTML
        scenario=scenario,
        # ... all existing variables ...
        cyber_context=cyber_context,
        # NEW: Add narrative and prioritized
        narrative=narrative,
        prioritized=prioritized
    )

    # ... rest of function ...
```

## Testing

### Test 1: Verify Backward Compatibility
```bash
# Without narrative (should use existing template)
python src/main_v2.py --scenario sentient_cyber_pmo
# Expected: HTML output with existing layout
```

### Test 2: Verify New Narrative Layout
```bash
# With narrative (uncomment Stage 2 + Stage 3 in main())
python src/main_v2.py --scenario sentient_cyber_pmo
# Expected: HTML output with narrative-driven layout
```

### Test 3: Verify Both Outputs
```bash
# Check both files generated
ls -lh output/cyber_pmo_report.html
ls -lh output/cyber_pmo_report.md
```

## Benefits of This Approach

✅ **Backward Compatible** - Existing flow still works
✅ **Opt-In** - New layout only activates when `narrative` is provided
✅ **Clean Separation** - Narrative sections are independent of hardcoded template
✅ **Flexible** - Can use either layout based on needs
✅ **Maintainable** - Narrative sections easier to update than monolithic template

---

**Last Updated**: December 2, 2025
**Status**: Ready for Implementation
**Estimated Effort**: 1-2 hours (template changes + testing)
