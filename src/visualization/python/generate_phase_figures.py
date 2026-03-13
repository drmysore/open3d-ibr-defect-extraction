"""
Generate Plotly phase figures from pipeline state and export to JSON/HTML.
Call this after a pipeline run to populate output/visualizations/ for the dashboard.
"""

import os
import json
import numpy as np
from pathlib import Path

from .phase1_raw_scan import generate_raw_scan_figure
from .phase3_deviation import generate_deviation_figure
from .phase4_segmentation import generate_segmentation_figure
from .phase5_clustering import generate_clustering_figure
from .phase7_zone_map import generate_zone_map_figure
from .figure_exporter import export_figure


def generate_and_export_all(
    scan_points_mm: np.ndarray,
    deviations_mm: np.ndarray,
    foil_labels: np.ndarray,
    all_defects: list,
    defect_cluster_points: list = None,
    defect_cluster_labels: list = None,
    output_dir: str = "output/visualizations",
    part_number: str = "4134613",
    threshold_mm: float = -0.01,
    expected_blades: int = 55,
) -> dict:
    """
    Generate phase figures from pipeline outputs and export JSON + HTML.
    Returns dict of phase -> { json_path, html_path }.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = {}

    # Phase 1: Raw scan
    fig1 = generate_raw_scan_figure(scan_points_mm, downsample=5)
    exp1 = export_figure(fig1, str(out), "phase1_raw_scan", ["json", "html"])
    results["phase1"] = exp1

    # Phase 3: Deviation
    fig3 = generate_deviation_figure(
        scan_points_mm, deviations_mm, threshold_mm=threshold_mm, downsample=3
    )
    exp3 = export_figure(fig3, str(out), "phase3_deviation", ["json", "html"])
    results["phase3"] = exp3

    # Phase 4: Segmentation (foil_labels: same length as scan_points_mm)
    if foil_labels is not None and len(foil_labels) == len(scan_points_mm):
        fig4 = generate_segmentation_figure(
            scan_points_mm, foil_labels, expected_blades, downsample=5
        )
        exp4 = export_figure(fig4, str(out), "phase4_segmentation", ["json", "html"])
        results["phase4"] = exp4

    # Phase 5: Clustering (build from all_defects if cluster arrays not provided)
    if defect_cluster_points is not None and defect_cluster_labels is not None:
        centroids = [np.asarray(d.get("centroid_mm") if d.get("centroid_mm") is not None else d.get("centroid")).ravel()[:3].tolist() for d in all_defects if d.get("centroid_mm") is not None or d.get("centroid") is not None]
        fig5 = generate_clustering_figure(
            defect_cluster_points,
            defect_cluster_labels,
            centroids,
            downsample=3,
        )
        exp5 = export_figure(fig5, str(out), "phase5_clustering", ["json", "html"])
        results["phase5"] = exp5
    elif all_defects:
        # Build from per-defect points (convert to mm if values are small = meters)
        all_pts = []
        all_lbl = []
        for i, d in enumerate(all_defects):
            pts = d.get("points")
            if pts is not None and len(pts):
                pts = np.asarray(pts)[:, :3]
                if np.median(np.abs(pts)) < 1:  # likely meters
                    pts = pts * 1000.0
                all_pts.append(pts)
                all_lbl.append(np.full(len(pts), i))
        if all_pts:
            blade_pts = np.vstack(all_pts)
            blade_lbl = np.concatenate(all_lbl)
            centroids = []
            for d in all_defects:
                c = d.get("centroid_mm") if d.get("centroid_mm") is not None else d.get("centroid")
                if c is not None:
                    c = np.asarray(c).ravel()[:3]
                    if np.median(np.abs(c)) < 1:
                        c = c * 1000.0
                    centroids.append(c.tolist())
            fig5 = generate_clustering_figure(blade_pts, blade_lbl, centroids, downsample=2)
            exp5 = export_figure(fig5, str(out), "phase5_clustering", ["json", "html"])
            results["phase5"] = exp5

    # Phase 7: Zone map (blade + defect locations)
    fig7 = generate_zone_map_figure(scan_points_mm, defects=all_defects, downsample=3)
    exp7 = export_figure(fig7, str(out), "phase7_zone_map", ["json", "html"])
    results["phase7"] = exp7

    # Save manifest for dashboard
    manifest = {
        "part_number": part_number,
        "phases": list(results.keys()),
        "paths": {k: v.get("json", v.get("html", "")) for k, v in results.items()},
    }
    with open(out / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    return results
