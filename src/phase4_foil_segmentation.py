"""Phase 4: Foil Segmentation — Angular DBSCAN to separate individual blades."""

import numpy as np
from sklearn.cluster import DBSCAN
import json
import yaml
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))
from o3d_compat import PointCloud


class FoilSegmentation:
    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config not found: {config_path}")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.config = cfg["foil_segmentation"]

        rotor_path = cfg.get("rotor_config_path", "config/rotor_configurations.json")
        if not os.path.isfile(rotor_path):
            raise FileNotFoundError(f"Rotor config not found: {rotor_path}")
        with open(rotor_path) as f:
            self.rotor_configs = json.load(f)

    def execute(self, pcd: PointCloud, part_number: str):
        if pcd.is_empty():
            raise ValueError("Input point cloud is empty")

        pts = np.asarray(pcd.points) * 1000.0  # m -> mm
        expected_blades = self._get_blade_count(part_number)
        print(f"  [Phase 4] Part: {part_number}, expected blades: {expected_blades}")

        centroid = np.mean(pts, axis=0)
        dx = pts[:, 0] - centroid[0]
        dy = pts[:, 1] - centroid[1]
        theta = np.arctan2(dy, dx)
        r = np.sqrt(dx ** 2 + dy ** 2)

        mean_radius = np.mean(r)
        if mean_radius < 1e-9:
            raise ValueError("Mean radius is near zero")

        angular_features = (theta * mean_radius).reshape(-1, 1)

        eps = self.config["dbscan_eps_mm"]
        min_samples = self.config["dbscan_min_samples"]
        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(angular_features)

        labels = clustering.labels_
        unique_labels = set(labels) - {-1}
        n_clusters = len(unique_labels)
        n_noise = int(np.sum(labels == -1))
        print(f"  [Phase 4] Found {n_clusters} blade clusters ({n_noise} noise points)")

        cluster_angles = []
        for label in unique_labels:
            mask = labels == label
            mean_angle = float(np.mean(theta[mask]))
            cluster_angles.append((label, mean_angle))
        cluster_angles.sort(key=lambda x: x[1])

        has_normals = pcd.has_normals()
        all_normals = pcd.normals if has_normals else None

        foils = []
        for foil_num, (label, angle) in enumerate(cluster_angles, start=1):
            mask = labels == label
            foil_pts_m = pts[mask] / 1000.0  # back to meters
            foil_normals = all_normals[mask] if has_normals else None
            foil_pcd = PointCloud(foil_pts_m, foil_normals)
            foils.append((foil_num, foil_pcd))
            print(f"    Foil {foil_num}: {int(np.sum(mask)):,} pts, angle={np.degrees(angle):.1f} deg")

        if n_clusters != expected_blades:
            print(f"  [Phase 4] WARNING: Found {n_clusters} foils, expected {expected_blades}")

        return foils

    def _get_blade_count(self, part_number: str) -> int:
        for config in self.rotor_configs:
            if config.get("part_number") == part_number:
                return int(config["blade_count"])
        available = [c.get("part_number", "?") for c in self.rotor_configs]
        raise ValueError(f"Unknown part number: {part_number}. Available: {available}")
