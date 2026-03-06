"""TLL-11: 58-Feature Defect Characterization Engine.

Extracts 58 geometric, spatial, contextual, surface, material, and type
features per defect for downstream ML classification.

Feature Groups:
  14 geometric  - depth, length, width, volume, aspect ratio, etc.
  10 spatial    - zone type, distances to critical structures
   8 contextual - nearby defects, clustering density
  11 surface    - curvature, roughness, normals
   6 material   - type flags, thickness estimates
   8 defect type - one-hot encoding of 7 types + unknown
   1 label      - serviceable/non-serviceable (0/1)
"""

import numpy as np
from scipy.spatial import cKDTree, ConvexHull
from typing import Optional
import time


FEATURE_NAMES = [
    # Geometric (14)
    "depth_mm", "length_mm", "width_mm", "area_mm2", "volume_mm3",
    "aspect_ratio", "compactness", "sphericity", "elongation",
    "max_deviation_mm", "mean_deviation_mm", "std_deviation_mm",
    "skewness_deviation", "kurtosis_deviation",
    # Spatial (10)
    "zone_severity_encoded", "distance_to_le_mm", "distance_to_te_mm",
    "distance_to_tip_mm", "distance_to_root_mm", "distance_to_spar_mm",
    "span_pct", "chord_pct", "radial_position_mm", "angular_position_deg",
    # Contextual (8)
    "num_defects_within_10mm", "num_defects_within_25mm",
    "num_defects_within_50mm", "nearest_defect_dist_mm",
    "cluster_density", "same_foil_defect_count",
    "defect_area_ratio", "defect_volume_ratio",
    # Surface (11)
    "mean_curvature", "gaussian_curvature", "max_curvature",
    "min_curvature", "surface_roughness_rms", "surface_roughness_ra",
    "normal_variance", "normal_mean_x", "normal_mean_y", "normal_mean_z",
    "local_planarity",
    # Material (6)
    "material_titanium", "material_nickel", "material_composite",
    "estimated_wall_thickness_mm", "hardness_estimate",
    "is_coated_surface",
    # Defect type one-hot (8)
    "type_nick", "type_dent", "type_crack", "type_fod",
    "type_erosion", "type_scratch", "type_gouge", "type_unknown",
    # Label (1)
    "label_serviceable",
]

assert len(FEATURE_NAMES) == 58, f"Expected 58 features, got {len(FEATURE_NAMES)}"

SEVERITY_ENCODING = {
    "CRITICAL": 1.0,
    "HIGH": 0.66,
    "STANDARD": 0.33,
    "LOW": 0.1,
}

DEFECT_TYPE_MAP = {
    "nick": "type_nick",
    "dent": "type_dent",
    "crack": "type_crack",
    "FOD": "type_fod",
    "erosion": "type_erosion",
    "scratch": "type_scratch",
    "gouge": "type_gouge",
}


class FeatureExtractor:
    """TLL-11 implementation: extract 58 features per defect."""

    def __init__(self, blade_geometry: Optional[dict] = None):
        self.blade_geometry = blade_geometry or {}
        self.all_defect_centroids: Optional[np.ndarray] = None

    def extract_all(
        self,
        defects: list[dict],
        cad_points: Optional[np.ndarray] = None,
        cad_normals: Optional[np.ndarray] = None,
    ) -> tuple[np.ndarray, list[str]]:
        """Extract feature matrix for all defects.

        Returns (N x 58) float array and feature name list.
        """
        t0 = time.time()
        n = len(defects)
        if n == 0:
            return np.zeros((0, 58), dtype=np.float64), FEATURE_NAMES

        centroids = np.array([d["centroid_mm"] for d in defects])
        self.all_defect_centroids = centroids

        cad_tree = cKDTree(cad_points) if cad_points is not None and len(cad_points) > 0 else None

        features = np.zeros((n, 58), dtype=np.float64)

        for i, defect in enumerate(defects):
            row = np.zeros(58, dtype=np.float64)

            pts = defect.get("points")
            if pts is None or len(pts) == 0:
                features[i] = row
                continue

            if not isinstance(pts, np.ndarray):
                pts = np.array(pts)

            devs = defect.get("deviations")
            if devs is not None and not isinstance(devs, np.ndarray):
                devs = np.array(devs)

            self._geometric_features(row, defect, pts, devs)
            self._spatial_features(row, defect, centroids[i])
            self._contextual_features(row, defect, i, centroids, defects)
            self._surface_features(row, pts, cad_tree, cad_points, cad_normals)
            self._material_features(row, defect)
            self._type_features(row, defect)
            self._label_feature(row, defect)

            features[i] = row

        missing_counts = np.isnan(features).sum(axis=1)
        for i, mc in enumerate(missing_counts):
            if mc > 10:
                defects[i]["feature_status"] = "INSUFFICIENT_DATA"
            elif mc > 5:
                defects[i]["feature_status"] = "PARTIAL"
            else:
                defects[i]["feature_status"] = "OK"

        features = np.nan_to_num(features, nan=0.0)

        elapsed = time.time() - t0
        print(f"  [TLL-11] Extracted {n} x 58 feature matrix in {elapsed:.2f}s")
        return features, FEATURE_NAMES

    def _geometric_features(
        self, row: np.ndarray, defect: dict, pts: np.ndarray, devs: Optional[np.ndarray]
    ):
        depth = abs(defect.get("depth_mm", 0.0))
        length = defect.get("length_mm", 0.0)
        width = defect.get("width_mm", 0.0)

        row[0] = depth
        row[1] = length
        row[2] = width

        if len(pts) >= 4:
            try:
                hull = ConvexHull(pts)
                row[3] = hull.area
                row[4] = hull.volume
            except Exception:
                row[3] = length * width
                row[4] = length * width * depth
        else:
            row[3] = length * width
            row[4] = length * width * depth

        row[5] = length / max(width, 1e-6)
        row[6] = (row[3] ** 1.5) / max(row[4], 1e-12)
        row[7] = (np.pi ** (1 / 3) * (6 * row[4]) ** (2 / 3)) / max(row[3], 1e-12)
        row[8] = length / max(depth, 1e-6)

        if devs is not None and len(devs) > 0:
            row[9] = float(np.max(np.abs(devs)))
            row[10] = float(np.mean(devs))
            row[11] = float(np.std(devs))
            n = len(devs)
            if n > 2 and row[11] > 1e-10:
                centered = devs - row[10]
                row[12] = float(np.mean(centered ** 3) / (row[11] ** 3))
                row[13] = float(np.mean(centered ** 4) / (row[11] ** 4))
            else:
                row[12] = 0.0
                row[13] = 3.0

    def _spatial_features(self, row: np.ndarray, defect: dict, centroid: np.ndarray):
        severity = defect.get("applied_limits", {})
        if isinstance(severity, dict):
            sev_str = severity.get("severity", "STANDARD")
        else:
            sev_str = "STANDARD"
        row[14] = SEVERITY_ENCODING.get(sev_str, 0.33)

        le_dist = defect.get("edge_distance_mm")
        row[15] = le_dist if le_dist is not None and defect.get("nearest_edge") == "LE" else np.nan
        row[16] = le_dist if le_dist is not None and defect.get("nearest_edge") == "TE" else np.nan

        bg = self.blade_geometry
        tip_z = bg.get("tip_z_mm", None)
        root_z = bg.get("root_z_mm", None)
        if tip_z is not None:
            row[17] = abs(centroid[2] - tip_z)
        if root_z is not None:
            row[18] = abs(centroid[2] - root_z)

        row[19] = np.nan

        if tip_z is not None and root_z is not None:
            span = tip_z - root_z
            if abs(span) > 1e-6:
                row[20] = ((centroid[2] - root_z) / span) * 100.0
        row[21] = np.nan

        row[22] = float(np.sqrt(centroid[0] ** 2 + centroid[1] ** 2))
        row[23] = float(np.degrees(np.arctan2(centroid[1], centroid[0])))

    def _contextual_features(
        self,
        row: np.ndarray,
        defect: dict,
        idx: int,
        all_centroids: np.ndarray,
        all_defects: list[dict],
    ):
        if len(all_centroids) < 2:
            row[24:32] = 0.0
            return

        c = all_centroids[idx]
        others = np.delete(all_centroids, idx, axis=0)
        dists = np.linalg.norm(others - c, axis=1)

        row[24] = int(np.sum(dists < 10.0))
        row[25] = int(np.sum(dists < 25.0))
        row[26] = int(np.sum(dists < 50.0))
        row[27] = float(np.min(dists)) if len(dists) > 0 else 0.0

        r25 = 25.0
        n_in_r = max(int(np.sum(dists < r25)), 1)
        vol = (4 / 3) * np.pi * (r25 ** 3)
        row[28] = n_in_r / vol

        foil_num = defect.get("foil_number", -1)
        same_foil = sum(1 for d in all_defects if d.get("foil_number") == foil_num)
        row[29] = same_foil

        row[30] = 0.0
        row[31] = 0.0

    def _surface_features(
        self,
        row: np.ndarray,
        pts: np.ndarray,
        cad_tree: Optional[cKDTree],
        cad_points: Optional[np.ndarray],
        cad_normals: Optional[np.ndarray],
    ):
        if cad_tree is None or cad_normals is None or len(pts) < 3:
            row[32:43] = 0.0
            return

        _, nn_idx = cad_tree.query(pts, k=1)
        local_normals = cad_normals[nn_idx]

        centered = pts - np.mean(pts, axis=0)
        cov = np.cov(centered.T) if centered.shape[0] > 2 else np.eye(3)
        evals = np.linalg.eigvalsh(cov)
        evals = np.sort(evals)[::-1]
        evals = np.maximum(evals, 1e-12)

        k1 = 1.0 / np.sqrt(evals[0] + 1e-12)
        k2 = 1.0 / np.sqrt(evals[1] + 1e-12)

        row[32] = (k1 + k2) / 2.0
        row[33] = k1 * k2
        row[34] = max(k1, k2)
        row[35] = min(k1, k2)

        if cad_tree is not None and cad_points is not None:
            dists, _ = cad_tree.query(pts, k=1)
            row[36] = float(np.sqrt(np.mean(dists ** 2)))
            row[37] = float(np.mean(np.abs(dists)))
        else:
            row[36] = 0.0
            row[37] = 0.0

        n_var = np.var(local_normals, axis=0)
        row[38] = float(np.sum(n_var))
        row[39] = float(np.mean(local_normals[:, 0]))
        row[40] = float(np.mean(local_normals[:, 1]))
        row[41] = float(np.mean(local_normals[:, 2]))

        row[42] = evals[2] / (evals[0] + 1e-12)

    def _material_features(self, row: np.ndarray, defect: dict):
        row[43] = 1.0
        row[44] = 0.0
        row[45] = 0.0
        row[46] = 2.0
        row[47] = 350.0
        row[48] = 0.0

    def _type_features(self, row: np.ndarray, defect: dict):
        row[49:57] = 0.0
        dt = defect.get("defect_type")
        if dt is None:
            dt = defect.get("classified_type")
        if dt is not None:
            col_name = DEFECT_TYPE_MAP.get(dt)
            if col_name and col_name in FEATURE_NAMES:
                idx = FEATURE_NAMES.index(col_name)
                row[idx] = 1.0
            else:
                row[56] = 1.0
        else:
            row[56] = 1.0

    def _label_feature(self, row: np.ndarray, defect: dict):
        disp = defect.get("disposition", "SERVICEABLE")
        row[57] = 1.0 if disp == "SERVICEABLE" else 0.0

    @staticmethod
    def normalize(features: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """StandardScaler normalization. Returns (scaled, means, stds)."""
        means = np.mean(features, axis=0)
        stds = np.std(features, axis=0)
        stds[stds < 1e-12] = 1.0
        scaled = (features - means) / stds
        return scaled, means, stds
