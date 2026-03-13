"""Phase 5: DBSCAN defect clusters — blade surface grey, clusters colored, centroids marked."""

import numpy as np
import plotly.graph_objects as go

from .base_figure import default_layout_scene

CLUSTER_COLORS = [
    "#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
    "#ffff33", "#a65628", "#f781bf", "#999999", "#66c2a5",
]


def generate_clustering_figure(
    blade_points_mm: np.ndarray,
    cluster_labels: np.ndarray,
    cluster_centroids_mm: list,
    downsample: int = 3,
) -> go.Figure:
    """
    Blade surface (grey), defect clusters (bright colors), centroids (gold).
    aspectmode='data' for true geometry with dense blades.
    """
    pts = blade_points_mm[::downsample]
    labels = cluster_labels[::downsample]

    fig = go.Figure()

    noise = labels == -1
    if np.any(noise):
        fig.add_trace(
            go.Scatter3d(
                x=pts[noise, 0],
                y=pts[noise, 1],
                z=pts[noise, 2],
                mode="markers",
                marker=dict(size=1, color="rgba(150,150,150,0.15)"),
                name="Blade Surface",
                hoverinfo="skip",
            )
        )

    unique = np.unique(labels[labels >= 0])
    for i, cid in enumerate(unique):
        mask = labels == cid
        fig.add_trace(
            go.Scatter3d(
                x=pts[mask, 0],
                y=pts[mask, 1],
                z=pts[mask, 2],
                mode="markers",
                marker=dict(
                    size=3,
                    color=CLUSTER_COLORS[i % len(CLUSTER_COLORS)],
                    opacity=0.9,
                ),
                name=f"Defect #{int(cid)+1}",
                hovertemplate=f"Defect #{int(cid)+1}<br>X: %{{x:.3f}}<br>Y: %{{y:.3f}}<br>Z: %{{z:.3f}}<extra></extra>",
            )
        )

    if cluster_centroids_mm:
        centroids = np.array(cluster_centroids_mm)
        fig.add_trace(
            go.Scatter3d(
                x=centroids[:, 0],
                y=centroids[:, 1],
                z=centroids[:, 2],
                mode="markers+text",
                marker=dict(size=8, color="gold", symbol="diamond"),
                text=[f"D{i+1}" for i in range(len(centroids))],
                textposition="top center",
                textfont=dict(size=10, color="gold"),
                name="Centroids",
                showlegend=True,
            )
        )

    fig.update_layout(
        title=dict(text="Phase 5: DBSCAN Defect Clustering", font=dict(size=16)),
        scene=default_layout_scene("", "side_profile"),
        margin=dict(l=0, r=0, t=40, b=0),
        template="plotly_dark",
        annotations=[
            dict(
                text=f"Clusters: {len(unique)} | Noise pts: {int(noise.sum()) * downsample}",
                xref="paper",
                yref="paper",
                x=0.02,
                y=0.98,
                showarrow=False,
                font=dict(size=11, color="white"),
                bgcolor="rgba(0,0,0,0.7)",
            )
        ],
        meta=dict(pipeline_phase=5, cluster_count=len(unique)),
    )
    return fig
