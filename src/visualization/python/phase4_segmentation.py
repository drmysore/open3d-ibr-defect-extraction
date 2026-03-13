"""Phase 4: Foil segmentation — each foil distinct color; blade count verification."""

import numpy as np
import plotly.graph_objects as go

from .base_figure import default_layout_scene

# Distinct colors for foils (cycle if many blades)
FOIL_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
    "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
]


def generate_segmentation_figure(
    points_mm: np.ndarray,
    foil_labels: np.ndarray,
    expected_blade_count: int,
    downsample: int = 5,
) -> go.Figure:
    """
    Color each foil distinctly. Hub/unassigned (label < 0) in grey.
    aspectmode='data' preserves true geometry for dense blades.
    """
    pts = points_mm[::downsample]
    labels = foil_labels[::downsample]

    unique = np.unique(labels[labels >= 0])
    actual = len(unique)
    match = actual == expected_blade_count

    fig = go.Figure()

    hub = labels < 0
    if np.any(hub):
        fig.add_trace(
            go.Scatter3d(
                x=pts[hub, 0],
                y=pts[hub, 1],
                z=pts[hub, 2],
                mode="markers",
                marker=dict(size=1, color="rgba(100,100,100,0.2)"),
                name="Hub / Unassigned",
                visible="legendonly",
            )
        )

    for i, foil_id in enumerate(unique):
        mask = labels == foil_id
        fig.add_trace(
            go.Scatter3d(
                x=pts[mask, 0],
                y=pts[mask, 1],
                z=pts[mask, 2],
                mode="markers",
                marker=dict(
                    size=1.5,
                    color=FOIL_COLORS[int(foil_id) % len(FOIL_COLORS)],
                    opacity=0.8,
                ),
                name=f"Foil {int(foil_id) + 1}",
                hovertemplate=f"Foil {int(foil_id)+1}<br>X: %{{x:.3f}}<br>Y: %{{y:.3f}}<br>Z: %{{z:.3f}}<extra></extra>",
            )
        )

    status_color = "rgba(0,200,0,0.7)" if match else "rgba(255,0,0,0.7)"
    fig.update_layout(
        title=dict(text="Phase 4: Foil Segmentation", font=dict(size=16)),
        scene=default_layout_scene("", "top_down"),
        margin=dict(l=0, r=0, t=40, b=0),
        template="plotly_dark",
        annotations=[
            dict(
                text=f"Expected: {expected_blade_count} | Detected: {actual} | {'✓ MATCH' if match else '✗ MISMATCH'}",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.98,
                showarrow=False,
                font=dict(size=12, color="white"),
                bgcolor=status_color,
            )
        ],
        meta=dict(
            pipeline_phase=4,
            expected_blades=expected_blade_count,
            detected_blades=actual,
            count_verified=match,
        ),
    )
    return fig
