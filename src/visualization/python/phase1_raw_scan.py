"""Phase 1: Raw point cloud 3D viewer. Preserves true geometry (aspectmode='data')."""

from typing import Optional
import numpy as np
import plotly.graph_objects as go

from .base_figure import default_layout_scene


def generate_raw_scan_figure(
    points_mm: np.ndarray,
    downsample: int = 5,
    colors: Optional[np.ndarray] = None,
) -> go.Figure:
    """
    Interactive 3D scatter of raw scan. For dense/overlapped blades, downsampling
    keeps the view responsive while preserving aspectmode='data'.

    Args:
        points_mm: Nx3 in mm
        downsample: show every Nth point (display only)
        colors: optional Nx3 RGB [0..1]; if None, color by Z height
    """
    pts = points_mm[::downsample]

    if colors is not None:
        c = colors[::downsample]
        color_strs = [f"rgb({int(r*255)},{int(g*255)},{int(b*255)})" for r, g, b in c]
        marker = dict(size=1.5, color=color_strs, opacity=0.8)
    else:
        marker = dict(
            size=1.5,
            color=pts[:, 2],
            colorscale="Viridis",
            colorbar=dict(title="Z (mm)", thickness=15),
            opacity=0.8,
        )

    fig = go.Figure(
        data=[
            go.Scatter3d(
                x=pts[:, 0],
                y=pts[:, 1],
                z=pts[:, 2],
                mode="markers",
                marker=marker,
                name="Raw Scan",
                hovertemplate="X: %{x:.3f} mm<br>Y: %{y:.3f} mm<br>Z: %{z:.3f} mm<extra></extra>",
            )
        ]
    )

    fig.update_layout(
        scene=default_layout_scene("Phase 1: Raw Point Cloud", "isometric"),
        margin=dict(l=0, r=0, t=40, b=0),
        template="plotly_dark",
        meta=dict(
            pipeline_phase=1,
            point_count=len(pts),
            original_point_count=len(points_mm),
            downsample=downsample,
        ),
    )
    if fig.layout.title is None or not fig.layout.title.text:
        fig.update_layout(title=dict(text="Phase 1: Raw Point Cloud Scan", font=dict(size=16)))
    return fig
