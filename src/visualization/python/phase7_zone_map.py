"""Phase 7: P&W 13-zone classification overlay on blade geometry."""

import numpy as np
import plotly.graph_objects as go

from .base_figure import default_layout_scene

ZONE_COLORS = {
    "LE_TIP": "#FF6B6B",
    "TE_TIP": "#FF8E8E",
    "A1": "#4ECDC4",
    "A2": "#45B7D1",
    "A3": "#96CEB4",
    "B1": "#26B5AC",
    "B2": "#2E9BBE",
    "C1": "#FFEAA7",
    "C2": "#DDA0DD",
    "D1": "#87CEEB",
    "D2": "#B0E0E6",
    "E1": "#98df8a",
    "E2": "#c5b0d5",
}


def generate_zone_map_figure(
    blade_points_mm: np.ndarray,
    defects: list = None,
    downsample: int = 3,
) -> go.Figure:
    """
    Blade surface (grey) with defect locations labeled by zone.
    defects: list of dicts with centroid_mm (or centroid), zone_ids (or applied_zone), defect_id.
    aspectmode='data' for true geometry.
    """
    pts = blade_points_mm[::downsample]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter3d(
            x=pts[:, 0],
            y=pts[:, 1],
            z=pts[:, 2],
            mode="markers",
            marker=dict(size=1.5, color="rgba(120,120,120,0.4)"),
            name="Blade",
            hovertemplate="X: %{x:.3f}<br>Y: %{y:.3f}<br>Z: %{z:.3f}<extra></extra>",
        )
    )

    defect_centroids = []
    if defects:
        for d in defects:
            c = d.get("centroid_mm") if d.get("centroid_mm") is not None else d.get("centroid")
            if c is None:
                continue
            c = np.asarray(c).ravel()[:3].astype(float)
            if np.median(np.abs(c)) < 1:
                c = c * 1000.0  # meters -> mm
            zid = d.get("applied_zone") or ((d.get("zone_ids") or [None])[0] if d.get("zone_ids") else None)
            did = d.get("defect_id", "?")
            defect_centroids.append(dict(centroid=c, zone=zid, defect_id=did))

    if defect_centroids:
        for d in defect_centroids:
            c = np.asarray(d["centroid"]).ravel()
            zid = d.get("zone", "?")
            did = d.get("defect_id", "?")
            fig.add_trace(
                go.Scatter3d(
                    x=[float(c[0])],
                    y=[float(c[1])],
                    z=[float(c[2])],
                    mode="markers+text",
                    marker=dict(size=10, color="red", symbol="x"),
                    text=[f"D{did}: Zone {zid}"],
                    textposition="top center",
                    textfont=dict(size=11, color="white"),
                    name=f"Defect {did} → Zone {zid}",
                    showlegend=True,
                )
            )

    fig.update_layout(
        title=dict(text="Phase 7: P&W 13-Zone Classification", font=dict(size=16)),
        scene=default_layout_scene("", "side_profile"),
        margin=dict(l=0, r=0, t=40, b=0),
        template="plotly_dark",
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(0,0,0,0.6)", font=dict(size=10)),
        meta=dict(
            pipeline_phase=7,
            defect_count=len(defect_centroids) if defect_centroids else 0,
        ),
    )
    return fig
