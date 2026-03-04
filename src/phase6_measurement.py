import numpy as np
from scipy.spatial import ConvexHull
import yaml
import os

MM_PER_INCH = 25.4


class DefectMeasurement:
    """Phase 6: Measure defect dimensions using PCA (edge) or OBB (surface)."""

    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config not found: {config_path}")
        with open(config_path) as f:
            full_config = yaml.safe_load(f)
        if "measurement" not in full_config:
            raise KeyError("Missing 'measurement' section in config")
        self.config = full_config["measurement"]

    def execute(
        self,
        defect: dict,
        le_curve: np.ndarray | None = None,
        te_curve: np.ndarray | None = None,
    ) -> dict:
        pts = defect["points"]
        if len(pts) < 3:
            defect.update(self._empty_measurements())
            return defect

        edge_thresh_mm = self.config["edge_distance_threshold_inches"] * MM_PER_INCH

        le_dist = self._min_distance_to_curve(defect["centroid_mm"], le_curve)
        te_dist = self._min_distance_to_curve(defect["centroid_mm"], te_curve)

        is_edge = False
        nearest_edge = None
        edge_distance_mm = None
        edge_curve = None

        if le_dist is not None and le_dist < edge_thresh_mm:
            is_edge = True
            nearest_edge = "LE"
            edge_distance_mm = le_dist
            edge_curve = le_curve
        elif te_dist is not None and te_dist < edge_thresh_mm:
            is_edge = True
            nearest_edge = "TE"
            edge_distance_mm = te_dist
            edge_curve = te_curve

        if is_edge and edge_curve is not None:
            dims = self._measure_pca(pts, edge_curve)
        else:
            dims = self._measure_obb(pts)
            if nearest_edge is None:
                if le_dist is not None and te_dist is not None:
                    nearest_edge = "LE" if le_dist <= te_dist else "TE"
                    edge_distance_mm = min(le_dist, te_dist)
                elif le_dist is not None:
                    nearest_edge = "LE"
                    edge_distance_mm = le_dist
                elif te_dist is not None:
                    nearest_edge = "TE"
                    edge_distance_mm = te_dist

        depth_mm = defect["max_depth_mm"]

        defect["classification"] = "edge" if is_edge else "surface"
        defect["nearest_edge"] = nearest_edge
        defect["edge_distance_mm"] = edge_distance_mm
        defect["length_mm"] = dims["length"]
        defect["width_mm"] = dims["width"]
        defect["depth_mm"] = depth_mm
        defect["length_in"] = dims["length"] / MM_PER_INCH
        defect["width_in"] = dims["width"] / MM_PER_INCH
        defect["depth_in"] = depth_mm / MM_PER_INCH

        print(
            f"  [Phase 6] {defect['defect_id']}: "
            f"{defect['classification']} | "
            f"L={defect['length_in']:.4f}\" W={defect['width_in']:.4f}\" D={defect['depth_in']:.4f}\""
        )
        return defect

    def _measure_pca(
        self, pts: np.ndarray, edge_curve: np.ndarray
    ) -> dict[str, float]:
        """PCA-based measurement aligned to edge tangent direction."""
        if len(pts) < 2:
            return {"length": 0.0, "width": 0.0}

        centroid = np.mean(pts, axis=0)

        diffs = edge_curve[1:] - edge_curve[:-1]
        curve_mids = (edge_curve[1:] + edge_curve[:-1]) / 2.0
        dists = np.linalg.norm(curve_mids - centroid, axis=1)
        nearest_idx = np.argmin(dists)
        tangent = diffs[nearest_idx]
        tangent = tangent / (np.linalg.norm(tangent) + 1e-12)

        centered = pts - centroid
        cov = np.cov(centered.T)
        eigenvalues, eigenvectors = np.linalg.eigh(cov)

        # Align primary axis with edge tangent
        dots = np.abs(eigenvectors.T @ tangent)
        longitudinal_idx = np.argmax(dots)
        longitudinal_axis = eigenvectors[:, longitudinal_idx]

        if longitudinal_axis @ tangent < 0:
            longitudinal_axis = -longitudinal_axis

        proj_long = centered @ longitudinal_axis
        length = float(np.ptp(proj_long))

        remaining = list(range(len(eigenvalues)))
        remaining.remove(longitudinal_idx)
        if remaining:
            widths = []
            for idx in remaining:
                axis = eigenvectors[:, idx]
                proj = centered @ axis
                widths.append(float(np.ptp(proj)))
            width = max(widths)
        else:
            width = 0.0

        return {"length": length, "width": width}

    def _measure_obb(self, pts: np.ndarray) -> dict[str, float]:
        """Oriented Bounding Box via 2D convex hull + rotating calipers."""
        if len(pts) < 3:
            return {"length": 0.0, "width": 0.0}

        centroid = np.mean(pts, axis=0)
        centered = pts - centroid
        cov = np.cov(centered.T)
        eigenvalues, eigenvectors = np.linalg.eigh(cov)

        sorted_idx = np.argsort(eigenvalues)[::-1]
        axes = eigenvectors[:, sorted_idx[:2]]
        pts_2d = centered @ axes

        try:
            hull = ConvexHull(pts_2d)
        except Exception:
            return {
                "length": float(np.ptp(pts_2d[:, 0])),
                "width": float(np.ptp(pts_2d[:, 1])),
            }

        hull_pts = pts_2d[hull.vertices]
        min_area = float("inf")
        best_dims = (0.0, 0.0)

        n = len(hull_pts)
        for i in range(n):
            edge = hull_pts[(i + 1) % n] - hull_pts[i]
            edge_len = np.linalg.norm(edge)
            if edge_len < 1e-12:
                continue
            edge_unit = edge / edge_len
            perp = np.array([-edge_unit[1], edge_unit[0]])

            proj_edge = hull_pts @ edge_unit
            proj_perp = hull_pts @ perp

            extent_edge = np.ptp(proj_edge)
            extent_perp = np.ptp(proj_perp)
            area = extent_edge * extent_perp

            if area < min_area:
                min_area = area
                best_dims = (
                    max(extent_edge, extent_perp),
                    min(extent_edge, extent_perp),
                )

        return {"length": float(best_dims[0]), "width": float(best_dims[1])}

    def _min_distance_to_curve(
        self, point: np.ndarray, curve: np.ndarray | None
    ) -> float | None:
        """Minimum Euclidean distance from a point to the nearest point on a curve."""
        if curve is None or len(curve) == 0:
            return None
        dists = np.linalg.norm(curve - point, axis=1)
        return float(np.min(dists))

    def _empty_measurements(self) -> dict:
        return {
            "classification": "surface",
            "nearest_edge": None,
            "edge_distance_mm": None,
            "length_mm": 0.0,
            "width_mm": 0.0,
            "depth_mm": 0.0,
            "length_in": 0.0,
            "width_in": 0.0,
            "depth_in": 0.0,
        }
