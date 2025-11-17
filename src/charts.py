"""
Generate static PNG charts for Platinum-tier CX Risk Radar reports using matplotlib.

This module creates professional, print-ready visualizations for:
  - CX Sentiment trends over time
  - Complaints & escalations grouped bar chart
  - Top risks by financial exposure
  - Risk heat maps (Impact vs Likelihood)
  - Stakeholder influence/support quadrant maps
"""

import os
from pathlib import Path
from typing import Dict, Any, List
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.ticker import FuncFormatter
import numpy as np

# Try importing seaborn for better styling
try:
    import seaborn as sns
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False


def generate_risk_charts(risk_context: Dict[str, Any], output_dir: str) -> Dict[str, str]:
    """
    Generate chart images and return a dict mapping chart keys to image paths.

    Args:
        risk_context: Structured context containing:
            - cx_sentiment_trend: List[Dict] with week_start, sentiment_index, complaints, escalations
            - risks: List[Dict] with id, title, severity, total_exposure
            - stakeholders: List[Dict] with name, influence, support, role
            - timeline: Optional List[Dict] with label, summary
        output_dir: Base output directory (e.g., 'output/')

    Returns:
        Dict mapping chart keys to relative image paths
        e.g., {'sentiment_trend': 'charts/sentiment_trend.png', ...}
    """
    # Create charts subdirectory
    charts_dir = os.path.join(output_dir, 'charts')
    os.makedirs(charts_dir, exist_ok=True)

    # Set professional matplotlib style
    if HAS_SEABORN:
        sns.set_style('whitegrid')
        sns.set_palette('muted')
    else:
        plt.style.use('seaborn-v0_8-darkgrid')

    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
    plt.rcParams['font.size'] = 10
    plt.rcParams['axes.labelsize'] = 11
    plt.rcParams['axes.titlesize'] = 12
    plt.rcParams['xtick.labelsize'] = 9
    plt.rcParams['ytick.labelsize'] = 9
    plt.rcParams['legend.fontsize'] = 9

    chart_paths = {}

    # 1. Sentiment Trend Chart (line chart)
    sentiment_path = _generate_sentiment_trend_chart(
        risk_context.get('cx_sentiment_trend', []),
        charts_dir
    )
    if sentiment_path:
        chart_paths['sentiment_trend'] = os.path.relpath(sentiment_path, output_dir)

    # 2. Complaints & Escalations Chart (grouped bar chart)
    complaints_path = _generate_complaints_escalations_chart(
        risk_context.get('cx_sentiment_trend', []),
        charts_dir
    )
    if complaints_path:
        chart_paths['complaints_escalations'] = os.path.relpath(complaints_path, output_dir)

    # 3. Risk Exposure Chart (horizontal bar chart of top 5 risks)
    exposure_path = _generate_risk_exposure_chart(
        risk_context.get('risks', []),
        charts_dir
    )
    if exposure_path:
        chart_paths['risk_exposure'] = os.path.relpath(exposure_path, output_dir)

    # 4. Risk Heat Map (3x3 Impact vs Likelihood)
    heatmap_path = _generate_risk_heatmap(
        risk_context.get('risks', []),
        charts_dir
    )
    if heatmap_path:
        chart_paths['risk_heatmap'] = os.path.relpath(heatmap_path, output_dir)

    # 5. Stakeholder Map (scatter plot: Influence vs Support)
    stakeholder_path = _generate_stakeholder_map(
        risk_context.get('stakeholders', []),
        charts_dir
    )
    if stakeholder_path:
        chart_paths['stakeholder_map'] = os.path.relpath(stakeholder_path, output_dir)

    return chart_paths


def _generate_sentiment_trend_chart(sentiment_data: List[Dict[str, Any]], charts_dir: str) -> str:
    """
    Generate line chart of CX sentiment index over time with baseline reference.

    Args:
        sentiment_data: List of dicts with 'week_start', 'sentiment_index', 'complaints', 'escalations'
        charts_dir: Directory to save chart

    Returns:
        Path to saved chart PNG
    """
    if not sentiment_data:
        return ""

    # Extract data
    weeks = []
    sentiment_scores = []

    for entry in sentiment_data:
        week_start = entry.get('week_start', entry.get('avg_sentiment_score', ''))
        sentiment = entry.get('sentiment_index', entry.get('avg_sentiment_score', 0))

        if week_start:
            weeks.append(week_start)
            sentiment_scores.append(float(sentiment) if sentiment else 0)

    if not weeks:
        return ""

    # Create figure
    fig, ax = plt.subplots(figsize=(6.5, 3))

    # Plot sentiment score
    color = '#0ea5e9'
    ax.plot(weeks, sentiment_scores, color=color, marker='o', linewidth=2.5,
            markersize=6, label='Sentiment Index')
    ax.set_xlabel('Week', fontweight='bold')
    ax.set_ylabel('Sentiment Index', fontweight='bold', color=color)
    ax.tick_params(axis='y', labelcolor=color)
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)

    # Add baseline reference line at 75
    baseline = 75
    ax.axhline(y=baseline, color='#10b981', linestyle='--', linewidth=1.5, alpha=0.6, label=f'Baseline ({baseline})')

    # Rotate x-axis labels for readability
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

    ax.legend(loc='upper left', framealpha=0.95)
    fig.suptitle('CX Sentiment Index Trend', fontsize=13, fontweight='bold')
    fig.tight_layout()

    # Save
    output_path = os.path.join(charts_dir, 'sentiment_trend.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()

    return output_path


def _generate_complaints_escalations_chart(sentiment_data: List[Dict[str, Any]], charts_dir: str) -> str:
    """
    Generate grouped bar chart of complaints & escalations per period.

    Args:
        sentiment_data: List of dicts with 'week_start', 'complaints', 'escalations'
        charts_dir: Directory to save chart

    Returns:
        Path to saved chart PNG
    """
    if not sentiment_data:
        return ""

    # Extract data
    weeks = []
    complaints = []
    escalations = []

    for entry in sentiment_data:
        week_start = entry.get('week_start', '')
        complaint_count = entry.get('complaints', 0)
        escalation_count = entry.get('escalations', 0)

        if week_start:
            weeks.append(week_start)
            complaints.append(int(complaint_count) if complaint_count else 0)
            escalations.append(int(escalation_count) if escalation_count else 0)

    if not weeks:
        return ""

    # Create figure
    fig, ax = plt.subplots(figsize=(6.5, 3))

    x = np.arange(len(weeks))
    width = 0.35

    # Plot grouped bars
    bars1 = ax.bar(x - width/2, complaints, width, label='Complaints', color='#f59e0b', alpha=0.8)
    bars2 = ax.bar(x + width/2, escalations, width, label='Escalations', color='#ef4444', alpha=0.8)

    ax.set_xlabel('Week', fontweight='bold')
    ax.set_ylabel('Count', fontweight='bold')
    ax.set_title('Complaints & Escalations per Week', fontsize=13, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(weeks, rotation=45, ha='right')
    ax.legend(loc='upper left', framealpha=0.95)
    ax.grid(True, alpha=0.3, axis='y')

    fig.tight_layout()

    # Save
    output_path = os.path.join(charts_dir, 'complaints_escalations.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()

    return output_path


def _generate_risk_exposure_chart(risks: List[Dict[str, Any]], charts_dir: str) -> str:
    """
    Generate horizontal bar chart of top 5 risks by total_exposure.

    Args:
        risks: List of risk dicts with 'id', 'title', 'total_exposure'
        charts_dir: Directory to save chart

    Returns:
        Path to saved chart PNG
    """
    if not risks:
        return ""

    # Sort by total_exposure descending and take top 5
    sorted_risks = sorted(risks, key=lambda r: float(r.get('total_exposure', 0) or 0), reverse=True)
    top_risks = sorted_risks[:5]

    if not top_risks:
        return ""

    # Extract data
    risk_labels = []
    exposures = []

    for risk in top_risks:
        risk_id = risk.get('id', 'N/A')
        title = risk.get('title', 'Unknown')
        exposure = float(risk.get('total_exposure', 0) or 0)

        # Truncate title if too long
        display_title = title[:30] + '...' if len(title) > 30 else title
        risk_labels.append(f"{risk_id}: {display_title}")
        exposures.append(exposure)

    # Create figure
    fig, ax = plt.subplots(figsize=(7, 3.5))

    # Create horizontal bar chart
    bars = ax.barh(risk_labels, exposures, color='#fb923c', edgecolor='#7c2d12', linewidth=1.5)

    # Add value labels on bars
    for i, (bar, exposure) in enumerate(zip(bars, exposures)):
        width = bar.get_width()
        label_x = width + (max(exposures) * 0.02) if max(exposures) > 0 else 0
        ax.text(label_x, bar.get_y() + bar.get_height() / 2,
                f'${exposure / 1_000_000:.1f}M',
                va='center', fontsize=9, fontweight='bold', color='#7c2d12')

    ax.set_xlabel('Total Exposure ($)', fontweight='bold')
    ax.set_ylabel('Risk', fontweight='bold')
    ax.set_title('Top 5 Financially Exposed Risks', fontsize=13, fontweight='bold', pad=15)

    # Format x-axis as currency
    def currency_formatter(x, pos):
        return f'${x / 1_000_000:.1f}M'

    ax.xaxis.set_major_formatter(FuncFormatter(currency_formatter))

    ax.grid(axis='x', alpha=0.3)
    fig.tight_layout()

    # Save
    output_path = os.path.join(charts_dir, 'risk_exposure.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()

    return output_path


def _generate_risk_heatmap(risks: List[Dict[str, Any]], charts_dir: str) -> str:
    """
    Generate 3x3 heat map of Impact vs Likelihood with risk counts and total exposure.

    Args:
        risks: List of risk dicts with 'severity' (impact), 'likelihood', 'total_exposure'
        charts_dir: Directory to save chart

    Returns:
        Path to saved chart PNG
    """
    if not risks:
        return ""

    # Map severity/likelihood to numeric values
    level_map = {'High': 3, 'Critical': 3, 'Medium': 2, 'Low': 1}

    # Initialize 3x3 grid
    grid_counts = [[0 for _ in range(3)] for _ in range(3)]
    grid_exposure = [[0.0 for _ in range(3)] for _ in range(3)]

    # Populate grid
    for risk in risks:
        severity = risk.get('severity', 'Medium')
        likelihood = risk.get('likelihood', 'Medium')
        exposure = float(risk.get('total_exposure', 0) or 0)

        impact_idx = level_map.get(severity, 2) - 1  # 0-indexed
        likelihood_idx = level_map.get(likelihood, 2) - 1

        grid_counts[impact_idx][likelihood_idx] += 1
        grid_exposure[impact_idx][likelihood_idx] += exposure

    # Create figure
    fig, ax = plt.subplots(figsize=(6, 5))

    # Create heat map using imshow
    # Define color intensity based on risk score (impact * likelihood * exposure)
    risk_scores = [[0.0 for _ in range(3)] for _ in range(3)]
    for i in range(3):
        for j in range(3):
            # Score = (impact_level) * (likelihood_level) * log(exposure + 1)
            import math
            score = (i + 1) * (j + 1) * math.log(grid_exposure[i][j] + 1, 10)
            risk_scores[i][j] = score

    # Reverse rows so High is at top
    risk_scores_display = risk_scores[::-1]
    grid_counts_display = grid_counts[::-1]
    grid_exposure_display = grid_exposure[::-1]

    im = ax.imshow(risk_scores_display, cmap='YlOrRd', aspect='auto', alpha=0.8)

    # Set ticks and labels
    ax.set_xticks([0, 1, 2])
    ax.set_yticks([0, 1, 2])
    ax.set_xticklabels(['Low', 'Medium', 'High'], fontweight='bold')
    ax.set_yticklabels(['High', 'Medium', 'Low'], fontweight='bold')

    ax.set_xlabel('Likelihood', fontsize=11, fontweight='bold')
    ax.set_ylabel('Impact', fontsize=11, fontweight='bold')
    ax.set_title('CX Risk Heat Map (Impact x Likelihood)', fontsize=13, fontweight='bold', pad=15)

    # Annotate cells with counts and exposure
    for i in range(3):
        for j in range(3):
            count = grid_counts_display[i][j]
            exposure = grid_exposure_display[i][j]
            text = f"{count} risks\n${exposure / 1_000_000:.1f}M" if exposure > 0 else f"{count} risks"
            max_score = max(max(row) for row in risk_scores_display) if any(any(row) for row in risk_scores_display) else 1
            color = 'white' if risk_scores_display[i][j] > max_score * 0.5 else 'black'
            ax.text(j, i, text, ha='center', va='center', fontsize=10, fontweight='bold', color=color)

    fig.tight_layout()

    # Save
    output_path = os.path.join(charts_dir, 'risk_heatmap.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()

    return output_path


def _generate_stakeholder_map(stakeholders: List[Dict[str, Any]], charts_dir: str) -> str:
    """
    Generate scatter plot of Influence vs Support with stakeholder initials as labels.

    Args:
        stakeholders: List of dicts with 'name', 'influence', 'support', 'role'
        charts_dir: Directory to save chart

    Returns:
        Path to saved chart PNG
    """
    if not stakeholders:
        return ""

    # Map text levels to numeric values
    level_map = {'High': 3, 'Medium': 2, 'Low': 1}

    # Extract data
    names = []
    influence_values = []
    support_values = []
    colors = []

    for stakeholder in stakeholders:
        name = stakeholder.get('name', stakeholder.get('Name', 'Unknown'))
        influence = stakeholder.get('influence', stakeholder.get('Influence', 'Medium'))
        support = stakeholder.get('support', stakeholder.get('Support', 'Medium'))
        stakeholder_type = stakeholder.get('type', stakeholder.get('Type', 'Neutral'))

        influence_val = level_map.get(influence, 2)
        support_val = level_map.get(support, 2)

        names.append(name)
        influence_values.append(influence_val)
        support_values.append(support_val)

        # Color based on type
        if stakeholder_type == 'Sponsor':
            colors.append('#10b981')  # Green
        elif stakeholder_type == 'Blocker':
            colors.append('#ef4444')  # Red
        else:
            colors.append('#6b7280')  # Gray

    if not names:
        return ""

    # Create figure
    fig, ax = plt.subplots(figsize=(6, 5))

    # Scatter plot
    ax.scatter(support_values, influence_values, c=colors, s=200, alpha=0.6, edgecolors='black', linewidths=1.5)

    # Add initials as labels
    for i, name in enumerate(names):
        # Get initials (first letter of each word)
        initials = ''.join([word[0].upper() for word in name.split() if word])[:3]
        ax.text(support_values[i], influence_values[i], initials, ha='center', va='center',
                fontsize=8, fontweight='bold', color='white')

    # Set axis labels and limits
    ax.set_xlabel('Support Level', fontsize=11, fontweight='bold')
    ax.set_ylabel('Influence Level', fontsize=11, fontweight='bold')
    ax.set_title('Stakeholder Influence x Support Map', fontsize=13, fontweight='bold', pad=15)

    ax.set_xticks([1, 2, 3])
    ax.set_yticks([1, 2, 3])
    ax.set_xticklabels(['Low', 'Medium', 'High'], fontweight='bold')
    ax.set_yticklabels(['Low', 'Medium', 'High'], fontweight='bold')

    ax.set_xlim(0.5, 3.5)
    ax.set_ylim(0.5, 3.5)

    # Add quadrant dividers
    ax.axhline(y=2.5, color='gray', linestyle='--', linewidth=1, alpha=0.5)
    ax.axvline(x=2.5, color='gray', linestyle='--', linewidth=1, alpha=0.5)

    # Add quadrant labels
    ax.text(1.25, 3.25, 'Blockers', fontsize=9, ha='center', color='#ef4444', fontweight='bold', alpha=0.7)
    ax.text(3.25, 3.25, 'Champions', fontsize=9, ha='center', color='#10b981', fontweight='bold', alpha=0.7)
    ax.text(3.25, 1.25, 'Advocates', fontsize=9, ha='center', color='#6b7280', fontweight='bold', alpha=0.7)
    ax.text(1.25, 1.25, 'Observers', fontsize=9, ha='center', color='#6b7280', fontweight='bold', alpha=0.7)

    # Legend
    legend_elements = [
        mpatches.Patch(facecolor='#10b981', edgecolor='black', label='Sponsor'),
        mpatches.Patch(facecolor='#ef4444', edgecolor='black', label='Blocker'),
        mpatches.Patch(facecolor='#6b7280', edgecolor='black', label='Neutral')
    ]
    ax.legend(handles=legend_elements, loc='upper left', framealpha=0.95, fontsize=9)

    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    # Save
    output_path = os.path.join(charts_dir, 'stakeholder_map.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()

    return output_path
