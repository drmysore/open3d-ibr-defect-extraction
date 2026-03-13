"""Phase 3: Deviation heatmap on blade surface. Red = material loss, green = nominal."""

import numpy as np
import plotly.graph_objects as go

from .base_figure import default_layout_scene


def generate_deviation_figure(
    points_mm: np.ndarray,
    deviations_mm: np.ndarray,
    threshold_mm: float = -0.010,
    colorscale: str = "RdYlGn_r",
    downsample: int = 3,
) -> go.Figure:
    """
    Color every point by signed distance from CAD. Negative = material removed.
    aspectmode='data' preserves true geometry for dense/overlapped blades.
    """
    pts = points_mm[::downsample]
    devs = deviations_mm[::downsample]

    vmin = max(devs.min(), -0.1)
    vmax = min(devs.max(), 0.05)

    fig = go.Figure(
        data=[
            go.Scatter3d(
                x=pts[:, 0],
                y=pts[:, 1],
                z=pts[:, 2],
                mode="markers",
                marker=dict(
                    size=1.5,
                    color=devs,
                    colorscale=colorscale,
                    cmin=vmin,
                    cmax=vmax,
                    colorbar=dict(
                        title=dict(text="Deviation (mm)", font=dict(size=12)),
                        thickness=15,
                        tickformat=".3f",
                    ),
                    opacity=0.9,
                ),
                name="Deviation",
                hovertemplate=(
                    "X: %{x:.3f} mm<br>Y: %{y:.3f} mm<br>Z: %{z:.3f} mm<br>"
                    "Deviation: %{marker.color:.4f} mm<extra></extra>"
                ),
            )
        ]
    )

    defect_mask = devs <= threshold_mm
    if np.any(defect_mask):
        d_pts = pts[defect_mask]
        fig.add_trace(
            go.Scatter3d(
                x=d_pts[:, 0],
                y=d_pts[:, 1],
                z=d_pts[:, 2],
                mode="markers",
                marker=dict(size=3, color="red", opacity=1.0, symbol="diamond"),
                name=f"Candidates (≤ {threshold_mm} mm)",
                visible="legendonly",
            )
        )

    fig.update_layout(
        title=dict(text="Phase 3: KD-Tree Deviation Analysis", font=dict(size=16)),
        scene=default_layout_scene("", "side_profile"),
        margin=dict(l=0, r=0, t=40, b=0),
        template="plotly_dark",
        annotations=[
            dict(
                text=f"Threshold: {threshold_mm} mm | Candidates: {int(defect_mask.sum())} pts",
                xref="paper",
                yref="paper",
                x=0.02,
                y=0.98,
                showarrow=False,
                font=dict(size=11, color="white"),
                bgcolor="rgba(0,0,0,0.7)",
            )
        ],
        meta=dict(
            pipeline_phase=3,
            threshold_mm=threshold_mm,
            candidate_count=int(defect_mask.sum()),
            total_points=len(devs),
        ),
    )
    return fig
