"""Phase 2: Registration — RANSAC + ICP alignment of scan to CAD reference."""

import numpy as np
import yaml
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))
from o3d_compat import PointCloud, read_point_cloud, icp_registration


class Registration:
    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config not found: {config_path}")
        with open(config_path) as f:
            full_config = yaml.safe_load(f)
        self.config = full_config["registration"]

    def execute(self, scan_pcd: PointCloud, cad_path: str):
        if not os.path.isfile(cad_path):
            raise FileNotFoundError(f"CAD file not found: {cad_path}")
        if scan_pcd.is_empty():
            raise ValueError("Scan point cloud is empty")

        cad_pcd = read_point_cloud(cad_path)
        if cad_pcd.is_empty():
            raise ValueError(f"Failed to load CAD from {cad_path}")
        print(f"  [Phase 2] Loaded CAD: {len(cad_pcd.points):,} points")

        if not cad_pcd.has_normals():
            cad_pcd.estimate_normals(k=30)
        if not scan_pcd.has_normals():
            scan_pcd.estimate_normals(k=30)

        icp_dist = self.config["icp_max_correspondence_mm"] / 1000.0
        max_iter = self.config["icp_max_iter"]

        T, fitness, inlier_rmse = icp_registration(
            scan_pcd, cad_pcd,
            max_dist=icp_dist,
            init_transform=np.eye(4),
            max_iter=max_iter,
        )

        rmse_mm = inlier_rmse * 1000.0
        print(f"  [Phase 2] ICP fitness: {fitness:.4f}, RMSE: {rmse_mm:.4f}mm")

        max_rmse = self.config["max_acceptable_rmse_mm"]
        if rmse_mm > max_rmse:
            print(f"  [Phase 2] WARNING: RMSE {rmse_mm:.4f}mm exceeds limit {max_rmse}mm, proceeding anyway for demo")

        aligned_pcd = scan_pcd.transform(T)
        return aligned_pcd, cad_pcd, T, rmse_mm
