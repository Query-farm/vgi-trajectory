"""Render trajectory evidence and verify the unchanged projected fence fixture."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon
from vgi_notebooks import finish

COLORS = {"visit": "#28765A", "trip": "#426DB3", "gap": "#A77038"}
SOURCE = "Source: VGI Trajectory v0.1.0 · bundled synthetic fixes and projected fences · modeled movement only"


def validate_gap(value):
    """Require finite positive seconds for the interpolation rule."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("MAX_GAP_S must be a finite positive number")
    return float(value)


def verify_fence():
    """Check the local polygon against the published worker's bundled bytes."""
    if (
        hashlib.sha256(Path("fixtures/fences.json").read_bytes()).hexdigest()
        != "348ee9f7a48e1b748f93930c0d9532e3b0b08e100506d50631fd56cae48fa3bd"
    ):
        raise ValueError("Fence differs from the published synthetic input")


def track_map(coverage, fence_shapes, spatial_paths, observations, max_gap_s):
    """Present recorded coordinates and modeled geometry on equal projected axes."""
    origin = np.array([500000.0, 4100000.0])
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.4), sharex=True, sharey=True)
    for ax, entity in zip(axes, coverage.entity_id, strict=True):
        for row in fence_shapes.itertuples():
            vertices = np.asarray(json.loads(row.fence_geojson)["coordinates"][0]) - origin
            ax.add_patch(Polygon(vertices, facecolor="#E3ECE5", edgecolor="#6E8977", linewidth=1.5))
            ax.text(vertices[:, 0].min() + 1, vertices[:, 1].max() - 2, row.fence_id, fontsize=10)
        paths = spatial_paths.loc[spatial_paths.entity_id == entity]
        for row in paths.itertuples():
            if pd.notna(row.path_geojson):
                xy = np.atleast_2d(json.loads(row.path_geojson)["coordinates"]) - origin
                ax.plot(xy[:, 0], xy[:, 1], color=COLORS[row.episode_type], linewidth=5, solid_capstyle="butt")
        points = observations.loc[observations.entity_id == entity].sort_values("observed_at_utc")
        xy = points[["easting_m", "northing_m"]].to_numpy() - origin
        ax.scatter(xy[:, 0], xy[:, 1], color="#263D32", s=65, edgecolor="white", zorder=5)
        if np.all(xy == xy[0]):
            labels = " / ".join(points.observed_at_utc.dt.strftime("%H:%M:%S")) + " UTC"
            ax.annotate(labels, xy[0], xytext=(0, -25), textcoords="offset points", ha="center", fontsize=9)
        else:
            for (_, row), point in zip(points.iterrows(), xy, strict=True):
                ax.annotate(
                    row.observed_at_utc.strftime("%H:%M:%S"),
                    point,
                    xytext=(0, -22),
                    textcoords="offset points",
                    ha="center",
                    fontsize=9,
                )
        if paths.episode_type.eq("gap").all():
            ax.text(10, 25, "No path inferred", ha="center", color=COLORS["gap"], fontsize=10)
        ax.set(
            title=coverage.set_index("entity_id").loc[entity, "vehicle"],
            xlabel="Easting offset from 500,000 m (m)",
            xlim=(-16, 36),
            ylim=(-6, 29),
        )
        ax.set_aspect("equal", adjustable="box")
    axes[0].set_ylabel("Northing offset from 4,100,000 m (m)")
    legend = [Line2D([0], [0], marker="o", color="none", markerfacecolor="#263D32", label="Recorded fix")]
    legend += [Line2D([0], [0], color=COLORS[t], lw=4, label=t.title() + " path") for t in ("trip", "visit")]
    fig.legend(handles=legend, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 0.80))
    finish(
        fig,
        "The yard lies between the crossing's recorded fixes",
        f"EPSG:32618 · equal map scales · 1 Jan 2026 UTC · max gap {max_gap_s:g} s. Lines are modeled paths.",
        SOURCE,
        name="01-observed-and-modeled-paths",
    )


def episode_timeline(coverage, episode_rows, observations, max_gap_s):
    """Keep modeled episodes and observed times on one shared clock."""
    base = observations.observed_at_utc.min()
    fig, ax = plt.subplots(figsize=(11.5, 4.8))
    for y, entity in enumerate(coverage.entity_id):
        for row in episode_rows.loc[episode_rows.entity_id == entity].itertuples():
            left = (row.start_utc - base).total_seconds()
            ax.barh(
                y,
                row.duration_s,
                left=left,
                height=0.44,
                color=COLORS[row.episode_type],
                alpha=0.82,
                hatch="///" if row.episode_type == "gap" else None,
                edgecolor="white",
            )
            ax.text(
                left + row.duration_s / 2,
                y,
                f"{row.duration_s:g} s" if row.duration_s >= 45 else f"{row.duration_s:g}",
                ha="center",
                va="center",
                color="white",
                fontsize=9,
                fontweight="bold",
            )
        t = (observations.loc[observations.entity_id == entity].observed_at_utc - base).dt.total_seconds()
        ax.scatter(t, np.full(len(t), y - 0.32), color="#263D32", marker="|", s=160, zorder=5)
    ax.set_yticks(range(len(coverage)), coverage.vehicle)
    span = coverage.observed_span_s.max()
    ax.set(
        xlabel=f"Seconds since {base:%Y-%m-%d %H:%M:%S} UTC",
        xlim=(-0.025 * span, span * 1.04),
        ylim=(len(coverage) - 0.5, -0.55),
    )
    ax.grid(axis="y", visible=False)
    handles = [
        Patch(facecolor=COLORS[t], hatch="///" if t == "gap" else None, label=t.title())
        for t in ("visit", "trip", "gap")
    ]
    handles.append(Line2D([0], [0], color="#263D32", marker="|", linestyle="none", label="Recorded fix"))
    fig.legend(handles=handles, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 0.80))
    finish(
        fig,
        "Dwell time and observation coverage answer different questions",
        f"Shared time scale · maximum gap {max_gap_s:g} s · gaps are unknown movement, not zero-distance trips.",
        SOURCE,
        name="02-episode-time-accounting",
    )


def gap_comparison(coverage, experiment):
    """Compare fixed interpolation rules without changing the observation population."""
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5), sharex=True, sharey=True)
    for ax, entity in zip(axes, coverage.entity_id, strict=True):
        rows = experiment.loc[experiment.entity_id == entity].sort_values("gap_limit_s", ascending=False)
        left = np.zeros(len(rows))
        for kind, col in [("visit", "inferred_visit_s"), ("trip", "inferred_trip_s"), ("gap", "unknown_s")]:
            values = rows[col].to_numpy()
            ax.barh(
                np.arange(len(rows)),
                values,
                left=left,
                height=0.5,
                color=COLORS[kind],
                hatch="///" if kind == "gap" else None,
                edgecolor="white",
            )
            for y, (start, width) in enumerate(zip(left, values, strict=True)):
                if width:
                    ax.text(start + width / 2, y, f"{width:g}", ha="center", va="center", color="white", fontsize=10)
            left += values
        ax.set_yticks(np.arange(len(rows)), [f"{v:g} s limit" for v in rows.gap_limit_s])
        ax.set(
            title=coverage.set_index("entity_id").loc[entity, "vehicle"],
            xlabel="Accounted observation time (s)",
            xlim=(0, coverage.observed_span_s.max() * 1.04),
            ylim=(1.65, -0.65),
        )
        ax.tick_params(axis="y", labelleft=True)
        ax.grid(axis="y", visible=False)
    fig.legend(
        handles=[
            Patch(
                facecolor=COLORS[t],
                hatch="///" if t == "gap" else None,
                label={"visit": "Inferred visit", "trip": "Inferred trip", "gap": "Unknown time"}[t],
            )
            for t in ("visit", "trip", "gap")
        ],
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.80),
    )
    finish(
        fig,
        "A stricter gap limit trades inferred dwell for unknown time",
        "Only max_gap_s changes · shared seconds scale · fixed synthetic observations from 1 Jan 2026 UTC.",
        SOURCE,
        name="03-gap-sensitivity",
    )


def roster_accounting(pages, outcomes, page_size):
    """Contrast actual returned page rows with expected-identity coverage states."""
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 6.6))
    bars = axes[0].bar(pages.page, pages.returned_rows, color="#426db3", width=0.6)
    axes[0].bar_label(bars, padding=4)
    axes[0].set(xticks=pages.page, xlabel="Actual requested page", ylabel="Returned API records (count)", ylim=(0, 9))
    axes[0].yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    bars = axes[1].barh(outcomes.state, outcomes.identities, color=["#28765a", "#a77038", "#9ca9a1"])
    axes[1].bar_label(bars, padding=4)
    axes[1].invert_yaxis()
    axes[1].set(xlabel="Expected roster identities (count)", xlim=(0, 10))
    axes[1].xaxis.set_major_locator(plt.MaxNLocator(integer=True))
    finish(
        fig,
        "Page size changes transport, not roster completeness",
        (
            f"Requested page size {page_size} · API returns {int(pages.returned_rows.sum())} rows · "
            f"expected roster has {int(outcomes.identities.sum())} IDs"
        ),
        "Source: explicitly synthetic loopback roster · unchanged VGI Trajectory v0.1.0 examples APIs.\n"
        "Missing records and present records with NULL names are different states; greetings are only draft strings.",
        name="04-page-and-roster-accounting",
    )
