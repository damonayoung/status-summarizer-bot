"""
EBITDA Waterfall Chart Generator

Standalone module for creating professional waterfall charts suitable for executive presentations.
"""

from typing import Dict, Any
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


def generate_ebitda_waterfall_chart(ebitda_context: Dict[str, Any], output_path: str) -> None:
    """
    Generate a professional-looking EBITDA waterfall chart and save it as a PNG.

    Expected keys in ebitda_context:
      - baseline_ebitda: float
      - revenue_leakage: float    # negative impact
      - compliance_penalties: float  # negative impact
      - opex_inefficiency: float  # negative impact
      - automation_gains: float   # positive impact
      - final_ebitda: float       # baseline + all movements

    The chart should look like something a CFO would see in a board deck:
    - x-axis categories: Baseline, Revenue Leakage, Compliance, Opex Drag, Automation Gains, Final
    - Waterfall style: starting bar, intermediate up/down bars, ending bar
    - Use neutral/board-friendly colors (e.g., grey for baseline/final, red-ish for negatives, green-ish for positives)
    - Add value labels on top of each bar
    - Add a y-axis label: "EBITDA ($M)"
    - Make the figure wide and readable (e.g., figsize=(10, 5))

    Requirements:
    - Convert all values to millions for display (baseline_ebitda / 1e6, etc.)
    - Use a white background and minimal gridlines to keep it "consulting style"
    - Save the chart to output_path as a PNG
    - Do not display the plot (no plt.show()), just save and close.
    """

    # Extract values from context (already in millions)
    baseline = ebitda_context.get("baseline_ebitda", 0.0)
    revenue_leakage = ebitda_context.get("revenue_leakage", 0.0)
    compliance_penalties = ebitda_context.get("compliance_penalties", 0.0)
    opex_inefficiency = ebitda_context.get("opex_inefficiency", 0.0)
    automation_gains = ebitda_context.get("automation_gains", 0.0)
    final = ebitda_context.get("final_ebitda", 0.0)

    # Define categories and values
    categories = [
        "Baseline\nEBITDA",
        "Revenue\nLeakage",
        "Compliance\nPenalties",
        "OpEx\nInefficiency",
        "Automation\nGains",
        "Final\nEBITDA"
    ]

    # Values for each category (negatives are shown as negative impacts)
    values = [
        baseline,
        -revenue_leakage,      # Negative impact
        -compliance_penalties, # Negative impact
        -opex_inefficiency,    # Negative impact
        automation_gains,      # Positive impact
        final
    ]

    # Calculate cumulative values for waterfall positioning
    cumulative = [0.0] * len(values)
    cumulative[0] = 0  # Baseline starts at 0

    # Running total for positioning intermediate bars
    running_total = baseline

    for i in range(1, len(values) - 1):
        cumulative[i] = running_total
        running_total += values[i]

    cumulative[-1] = 0  # Final bar starts at 0

    # Define colors (consulting/board-friendly palette)
    colors = []
    for i, val in enumerate(values):
        if i == 0 or i == len(values) - 1:
            colors.append("#7F8C8D")  # Grey for baseline and final
        elif val < 0:
            colors.append("#E74C3C")  # Red for negative impacts
        else:
            colors.append("#27AE60")  # Green for positive impacts

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 5))

    # Set white background
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    # Create bars
    bars = ax.bar(
        range(len(categories)),
        [abs(v) if i in [0, len(values) - 1] else abs(v) for i, v in enumerate(values)],
        bottom=cumulative,
        color=colors,
        edgecolor='black',
        linewidth=0.5,
        width=0.6
    )

    # Add connecting lines between bars (optional, for waterfall effect)
    for i in range(len(values) - 1):
        if i == 0:
            # Connect baseline to first impact
            start_y = baseline
            end_y = baseline
        else:
            # Connect previous bar top to current bar bottom
            start_y = cumulative[i] + values[i]
            end_y = cumulative[i + 1]

        if i < len(values) - 2:  # Don't draw line to final bar
            ax.plot(
                [i + 0.3, i + 0.7],
                [start_y, end_y],
                color='black',
                linewidth=0.8,
                linestyle='--',
                alpha=0.3
            )

    # Add value labels on top of each bar
    for i, (bar, val) in enumerate(zip(bars, values)):
        if i in [0, len(values) - 1]:
            # Baseline and final: show absolute value
            label_y = bar.get_height()
            label_text = f"${abs(val):.1f}M"
        else:
            # Intermediate bars: show change with +/- sign
            label_y = cumulative[i] + abs(val)
            if val >= 0:
                label_text = f"+${val:.1f}M"
            else:
                label_text = f"-${abs(val):.1f}M"

        ax.text(
            bar.get_x() + bar.get_width() / 2,
            label_y + 0.5,
            label_text,
            ha='center',
            va='bottom',
            fontsize=9,
            fontweight='bold'
        )

    # Customize axes
    ax.set_xticks(range(len(categories)))
    ax.set_xticklabels(categories, fontsize=10)
    ax.set_ylabel("EBITDA ($M)", fontsize=11, fontweight='bold')
    ax.set_title("EBITDA Waterfall Analysis", fontsize=13, fontweight='bold', pad=20)

    # Add minimal gridlines (horizontal only)
    ax.yaxis.grid(True, linestyle='--', alpha=0.3, linewidth=0.5)
    ax.set_axisbelow(True)

    # Remove top and right spines for cleaner look
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Set y-axis to start at 0 with some padding
    y_min = min(0, min(cumulative))
    y_max = max(baseline, final) * 1.15
    ax.set_ylim(y_min, y_max)

    # Tight layout to prevent label cutoff
    plt.tight_layout()

    # Save the chart
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
