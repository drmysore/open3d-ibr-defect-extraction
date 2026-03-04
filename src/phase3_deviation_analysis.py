"""Phase 3: Deviation Analysis — Vectorized KD-tree signed distance computation."""

import numpy as np
from scipy.spatial import cKDTree
import yaml
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))
from o3d_compat import PointCloud


class DeviationAnalysis:
    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config not found: {config_path}")
        with open(config_path) as f:
            full_config = yaml.safe_load(f)
        self.config = full_config["deviation_analysis"]
        self.threshold_mm = float(self.config["threshold_mm"])

    def execute_vectorized(self, scan_pcd: PointCloud, cad_pcd: PointCloud):
        if scan_pcd.is_empty():
            raise ValueError("Scan point cloud is empty")
        if cad_pcd.is_empty():
            raise ValueError("CAD point cloud is empty")

        scan_pts = np.asarray(scan_pcd.points) * 1000.0  # m -> mm
        cad_pts = np.asarray(cad_pcd.points) * 1000.0
        cad_normals = np.asarray(cad_pcd.normals)

        if len(cad_normals) == 0 or len(cad_normals) != len(cad_pts):
            cad_pcd.estimate_normals(k=30)
            cad_normals = np.asarray(cad_pcd.normals)

        tree = cKDTree(cad_pts)
        distances, indices = tree.query(scan_pts, k=1, workers=-1)

        nearest_normals = cad_normals[indices]
        diff_vectors = scan_pts - cad_pts[indices]
        signed_distances = np.sum(diff_vectors * nearest_normals, axis=1)

        n_scan = len(scan_pts)
        print(f"  [Phase 3] Computed {n_scan:,} deviations")
        print(f"  [Phase 3] Range: [{signed_distances.min():.4f}, {signed_distances.max():.4f}] mm")
        print(f"  [Phase 3] Mean: {signed_distances.mean():.4f} mm, Std: {signed_distances.std():.4f} mm")

        defect_mask = signed_distances < self.threshold_mm
        defect_points = scan_pts[defect_mask]
        defect_deviations = signed_distances[defect_mask]

        n_defect = int(np.sum(defect_mask))
        pct = 100.0 * n_defect / max(n_scan, 1)
        print(f"  [Phase 3] Defect candidates (< {self.threshold_mm}mm): {n_defect:,} ({pct:.1f}%)")

        return signed_distances, defect_mask, defect_points, defect_deviations
