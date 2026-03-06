"""LE/TE Curve Extraction from CAD Reference.

Extracts leading edge (LE) and trailing edge (TE) curves from the CAD
point cloud using curvature analysis and angular extrema detection.
This enables accurate edge-distance measurement in Phase 6.
"""

import numpy as np
from scipy.spatial import cKDTree
from typing import Optional
import time


class EdgeExtractor:
    """Extract LE/TE curves from CAD reference geometry."""

    def __init__(self, angular_bins: int = 360, k_neighbors: int = 30):
        self.angular_bins = angular_bins
        self.k_neighbors = k_neighbors

    def extract(
        self,
        cad_points: np.ndarray,
        cad_normals: Optional[np.ndarray] = None,
        blade_axis: np.ndarray = np.array([0.0, 0.0, 1.0]),
    ) -> dict:
        """Extract LE and TE curves from CAD geometry.

        Returns dict with 'le_curve' and 'te_curve' as Nx3 arrays,
        plus metadata about the extraction.
        """
        t0 = time.time()
        print("  [Edge Extraction] Extracting LE/TE curves from CAD...")

        pts = cad_points
        if pts.shape[1] != 3:
            raise ValueError(f"Expected Nx3 points, got {pts.shape}")

        centroid_xy = np.mean(pts[:, :2], axis=0)
        centered = pts[:, :2] - centroid_xy

        radii = np.sqrt(centered[:, 0] ** 2 + centered[:, 1] ** 2)
        angles = np.arctan2(centered[:, 1], centered[:, 0])

        height_min, height_max = pts[:, 2].min(), pts[:, 2].max()
        height_range = height_max - height_min
        if height_range < 1e-6:
            height_range = 1.0

        n_slices = max(20, int(height_range / 0.5))
        slice_edges = np.linspace(height_min, height_max, n_slices + 1)

        le_points = []
        te_points = []

        for s in range(n_slices):
            z_lo, z_hi = slice_edges[s], slice_edges[s + 1]
            mask = (pts[:, 2] >= z_lo) & (pts[:, 2] < z_hi)
            if np.sum(mask) < 10:
                continue

            slice_pts = pts[mask]
            slice_centered = centered[mask]
            slice_angles = angles[mask]
            slice_radii = radii[mask]

            n_bins = min(self.angular_bins, max(36, np.sum(mask) // 5))
            bin_edges = np.linspace(-np.pi, np.pi, n_bins + 1)
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0

            le_candidates = []
            te_candidates = []

            for b in range(n_bins):
                in_bin = (slice_angles >= bin_edges[b]) & (slice_angles < bin_edges[b + 1])
                if np.sum(in_bin) < 2:
                    continue

                bin_pts = slice_pts[in_bin]
                bin_radii = slice_radii[in_bin]

                le_idx = np.argmax(bin_radii)
                le_candidates.append(bin_pts[le_idx])

                te_idx = np.argmin(bin_radii)
                te_candidates.append(bin_pts[te_idx])

            if le_candidates:
                le_cands = np.array(le_candidates)
                le_points.append(le_cands[np.argmax(np.linalg.norm(le_cands[:, :2] - centroid_xy, axis=1))])

            if te_candidates:
                te_cands = np.array(te_candidates)
                te_points.append(te_cands[np.argmin(np.linalg.norm(te_cands[:, :2] - centroid_xy, axis=1))])

        le_curve = np.array(le_points) if le_points else np.zeros((0, 3))
        te_curve = np.array(te_points) if te_points else np.zeros((0, 3))

        if len(le_curve) > 3:
            le_curve = self._smooth_curve(le_curve)
        if len(te_curve) > 3:
            te_curve = self._smooth_curve(te_curve)

        if cad_normals is not None and len(cad_normals) > 0:
            le_refined, te_refined = self._refine_with_curvature(
                cad_points, cad_normals, le_curve, te_curve
            )
            if len(le_refined) > 0:
                le_curve = le_refined
            if len(te_refined) > 0:
                te_curve = te_refined

        elapsed = time.time() - t0
        print(f"  [Edge Extraction] LE curve: {len(le_curve)} points")
        print(f"  [Edge Extraction] TE curve: {len(te_curve)} points")
        print(f"  [Edge Extraction] Completed in {elapsed:.2f}s")

        return {
            "le_curve": le_curve,
            "te_curve": te_curve,
            "le_points_count": len(le_curve),
            "te_points_count": len(te_curve),
            "extraction_time_s": round(elapsed, 3),
        }

    def _smooth_curve(self, curve: np.ndarray, window: int = 3) -> np.ndarray:
        """Moving average smoothing along the curve."""
        if len(curve) <= window:
            return curve

        sorted_idx = np.argsort(curve[:, 2])
        curve = curve[sorted_idx]

        smoothed = np.zeros_like(curve)
        half = window // 2
        for i in range(len(curve)):
            lo = max(0, i - half)
            hi = min(len(curve), i + half + 1)
            smoothed[i] = np.mean(curve[lo:hi], axis=0)

        return smoothed

    def _refine_with_curvature(
        self,
        points: np.ndarray,
        normals: np.ndarray,
        le_curve: np.ndarray,
        te_curve: np.ndarray,
        search_radius: float = 2.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Refine edge curves using local curvature maxima."""
        tree = cKDTree(points)

        def _refine_single(curve):
            refined = []
            for pt in curve:
                idx = tree.query_ball_point(pt, search_radius)
                if len(idx) < 5:
                    refined.append(pt)
                    continue

                local_pts = points[idx]
                local_normals = normals[idx]

                normal_var = np.var(local_normals, axis=0).sum()

                if normal_var > 0.01:
                    centroid_local = np.mean(local_pts, axis=0)
                    centered_local = local_pts - centroid_local
                    cov = np.cov(centered_local.T)
                    evals = np.linalg.eigvalsh(cov)
                    evals = np.sort(evals)

                    linearity = (evals[2] - evals[1]) / (evals[2] + 1e-12)
                    if linearity > 0.5:
                        refined.append(centroid_local)
                        continue

                refined.append(pt)

            return np.array(refined) if refined else curve

        le_refined = _refine_single(le_curve)
        te_refined = _refine_single(te_curve)
        return le_refined, te_refined


class FoilSegmentationTuner:
    """Sprint 4: Calibrate DBSCAN parameters for improved segmentation."""

    def __init__(self):
        self.best_params = None
        self.evaluation_results = []

    def auto_calibrate(
        self,
        points: np.ndarray,
        expected_blade_count: int,
        eps_range: tuple[float, float] = (1.0, 5.0),
        min_samples_range: tuple[int, int] = (5, 30),
        n_trials: int = 20,
    ) -> dict:
        """Grid search over DBSCAN parameters to match expected blade count."""
        from sklearn.cluster import DBSCAN
        t0 = time.time()
        print(f"  [Tuner] Auto-calibrating for {expected_blade_count} blades...")

        centered = points[:, :2] - np.mean(points[:, :2], axis=0)
        angles = np.arctan2(centered[:, 1], centered[:, 0])

        best_score = float("inf")
        best_params = {"eps": 2.0, "min_samples": 10}

        eps_values = np.linspace(eps_range[0], eps_range[1], n_trials)
        min_samples_values = np.linspace(min_samples_range[0], min_samples_range[1], min(n_trials, 10)).astype(int)

        for eps in eps_values:
            for ms in min_samples_values:
                angular_features = np.column_stack([np.cos(angles), np.sin(angles)])
                db = DBSCAN(eps=eps / 100.0, min_samples=int(ms))
                labels = db.fit_predict(angular_features)

                n_clusters = len(set(labels) - {-1})
                score = abs(n_clusters - expected_blade_count)

                noise_frac = np.sum(labels == -1) / len(labels) if len(labels) > 0 else 1.0
                score += noise_frac * 5.0

                result = {
                    "eps": float(eps),
                    "min_samples": int(ms),
                    "n_clusters": n_clusters,
                    "noise_fraction": float(noise_frac),
                    "score": float(score),
                }
                self.evaluation_results.append(result)

                if score < best_score:
                    best_score = score
                    best_params = {"eps": float(eps), "min_samples": int(ms)}

        self.best_params = best_params
        elapsed = time.time() - t0

        print(f"  [Tuner] Best params: eps={best_params['eps']:.2f}, "
              f"min_samples={best_params['min_samples']}")
        print(f"  [Tuner] Calibration completed in {elapsed:.2f}s")

        return {
            "best_params": best_params,
            "best_score": float(best_score),
            "n_trials": len(self.evaluation_results),
            "calibration_time_s": round(elapsed, 3),
        }
