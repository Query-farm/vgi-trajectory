"""Small presentation helpers for the trajectory notebook; domain work stays in SQL."""

from __future__ import annotations

import math
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from IPython.display import Markdown, display

COLORS = {"visit": "#28765A", "trip": "#426DB3", "gap": "#A77038"}
SOURCE = "Source: bundled synthetic trajectory.main.demo_input + fences.json; real VGI worker, local computation."


def validate_gap(value: Any) -> float:
    """Require a finite positive interpolation gap in seconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("MAX_GAP_S must be a finite positive number of seconds, e.g. 900 or 60.")
    return float(value)


def prose(value: str) -> None:
    """Display result-derived narrative with folded source code."""
    display(Markdown(value))


def number(value: Any, digits: int = 0) -> str:
    """Keep unavailable values separate from zero in explanations."""
    return "unavailable" if pd.isna(value) else f"{value:,.{digits}f}"


def set_theme() -> None:
    """Apply a readable shared Seaborn theme."""
    sns.set_theme(
        style="whitegrid",
        context="notebook",
        palette=list(COLORS.values()),
        rc={
            "figure.dpi": 140,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#CCD5CF",
            "text.color": "#243B2F",
            "axes.labelcolor": "#405047",
            "grid.color": "#E8EDE9",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titlelocation": "left",
            "axes.titleweight": "semibold",
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "legend.frameon": False,
            "text.parse_math": False,
        },
    )
    pd.set_option("display.max_columns", 14)
    pd.set_option("display.width", 130)
    pd.set_option("display.precision", 2)


def finish_chart(fig: Any, title: str, subtitle: str) -> None:
    """Add readable context and provenance, preserving the inline chart output."""
    fig.suptitle(title, x=0.075, y=0.99, ha="left", fontsize=17, fontweight="semibold")
    fig.text(0.075, 0.92, subtitle, ha="left", va="top", fontsize=10, color="#58685F")
    fig.tight_layout(rect=(0.02, 0.095, 0.99, 0.85), w_pad=2.8, h_pad=2)
    fig.text(0.075, 0.025, SOURCE, ha="left", fontsize=8, color="#67786D")
    plt.show()
