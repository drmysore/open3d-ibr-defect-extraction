"""Shared Plotly 3D layout, camera, and theme for IBR visualizations.

CRITICAL: aspectmode='data' preserves true geometry for dense/overlapped blades.
"""

import plotly.graph_objects as go
from typing import Optional

# Camera presets (mm-space; eye in scene units)
CAMERA_PRESETS = {
    "top_down": dict(eye=dict(x=0, y=0, z=2.5), up=dict(x=0, y=1, z=0)),
    "side_profile": dict(eye=dict(x=0, y=-2, z=0.5), up=dict(x=0, y=0, z=1)),
    "isometric": dict(eye=dict(x=1.5, y=1.5, z=1.0), up=dict(x=0, y=0, z=1)),
    "detail_closeup": dict(eye=dict(x=0, y=-0.8, z=0.3), up=dict(x=0, y=0, z=1)),
}


def default_layout_scene(
    title: str = "",
    camera_preset: str = "isometric",
    x_title: str = "X (mm)",
    y_title: str = "Y (mm)",
    z_title: str = "Z (mm)",
) -> dict:
    """Scene dict with aspectmode='data' for true blade proportions."""
    camera = CAMERA_PRESETS.get(camera_preset, CAMERA_PRESETS["isometric"])
    return dict(
        xaxis_title=x_title,
        yaxis_title=y_title,
        zaxis_title=z_title,
        aspectmode="data",
        camera=camera,
    )


def apply_dark_theme(
    fig: go.Figure,
    title: str = "",
    margin: Optional[dict] = None,
    meta: Optional[dict] = None,
) -> go.Figure:
    """Apply plotly_dark template and optional metadata."""
    layout_updates = dict(
        template="plotly_dark",
        margin=margin or dict(l=0, r=0, t=40, b=0),
    )
    if title:
        layout_updates["title"] = dict(text=title, font=dict(size=16))
    if meta is not None:
        layout_updates["meta"] = meta
    fig.update_layout(**layout_updates)
    return fig
