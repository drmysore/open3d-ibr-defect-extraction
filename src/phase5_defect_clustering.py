import numpy as np
from sklearn.cluster import DBSCAN
import yaml
import os


class DefectClustering:
    """Phase 5: DBSCAN clustering of defect points into discrete defect regions."""

    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config not found: {config_path}")
        with open(config_path) as f:
            full_config = yaml.safe_load(f)
        if "defect_clustering" not in full_config:
            raise KeyError("Missing 'defect_clustering' section in config")
        self.config = full_config["defect_clustering"]

    def execute(
        self,
        defect_points: np.ndarray,
        defect_deviations: np.ndarray,
        foil_number: int,
    ) -> list[dict]:
        if len(defect_points) == 0:
            print(f"  [Phase 5] Foil {foil_number}: No defect candidates")
            return []

        eps = self.config["dbscan_eps_mm"]
        min_samples = self.config["dbscan_min_samples"]
        min_cluster = self.config["min_cluster_size"]

        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(defect_points)
        labels = clustering.labels_
        unique_labels = set(labels) - {-1}

        defects = []
        counter = 0
        for label in sorted(unique_labels):
            mask = labels == label
            cluster_pts = defect_points[mask]
            cluster_devs = defect_deviations[mask]

            if len(cluster_pts) < min_cluster:
                continue

            counter += 1
            centroid = np.mean(cluster_pts, axis=0)
            defect = {
                "defect_id": f"F{foil_number:03d}_D{counter:03d}",
                "foil_number": foil_number,
                "points": cluster_pts,
                "deviations": cluster_devs,
                "centroid_mm": centroid,
                "max_depth_mm": float(np.abs(np.min(cluster_devs))),
                "mean_depth_mm": float(np.abs(np.mean(cluster_devs))),
                "extent_mm": np.ptp(cluster_pts, axis=0),
                "n_points": len(cluster_pts),
            }
            defects.append(defect)

        print(
            f"  [Phase 5] Foil {foil_number}: "
            f"{len(defects)} defects from {len(defect_points)} points"
        )
        return defects
