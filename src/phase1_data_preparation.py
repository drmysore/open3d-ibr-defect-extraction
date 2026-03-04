"""Phase 1: Data Preparation — Load, validate, downsample, clean, compute normals."""

import numpy as np
import yaml
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))
from o3d_compat import PointCloud, read_point_cloud


class DataPreparation:
    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config not found: {config_path}")
        with open(config_path) as f:
            full_config = yaml.safe_load(f)
        self.config = full_config["data_preparation"]

    def execute(self, ply_path: str) -> PointCloud:
        if not os.path.isfile(ply_path):
            raise FileNotFoundError(f"PLY file not found: {ply_path}")

        pcd = read_point_cloud(ply_path)
        n_raw = len(pcd.points)
        print(f"  [Phase 1] Loaded {n_raw:,} points from {ply_path}")

        min_pts = self.config["min_points"]
        max_pts = self.config["max_points"]
        if n_raw < min_pts:
            raise ValueError(f"Too few points: {n_raw:,} < {min_pts:,}")
        if n_raw > max_pts:
            raise ValueError(f"Too many points: {n_raw:,} > {max_pts:,}")

        voxel_m = self.config["voxel_size_mm"] / 1000.0
        pcd = pcd.voxel_down_sample(voxel_m)
        print(f"  [Phase 1] After voxel downsample ({self.config['voxel_size_mm']}mm): {len(pcd.points):,}")

        nb = self.config["statistical_outlier_neighbors"]
        std = self.config["statistical_outlier_std"]
        pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=nb, std_ratio=std)
        n_after = len(pcd.points)
        print(f"  [Phase 1] After outlier removal: {n_after:,}")

        if n_after == 0:
            raise ValueError("All points removed during outlier filtering")

        if not pcd.has_normals():
            pcd.estimate_normals(k=self.config["normal_max_nn"])
        print(f"  [Phase 1] Normals computed ({n_after:,} points)")

        return pcd
