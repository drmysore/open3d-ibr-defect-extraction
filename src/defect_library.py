import numpy as np
from collections import defaultdict
from scipy.spatial import cKDTree


class DefectLibrary:
    """Hybrid Grid+Metric defect storage with secondary indices for fast lookup."""

    def __init__(self):
        self._defects: dict[str, dict] = {}
        self._by_foil: dict[int, list[str]] = defaultdict(list)
        self._by_zone: dict[str, list[str]] = defaultdict(list)
        self._centroids: dict[str, np.ndarray] = {}
        self._kdtree = None
        self._tree_ids: list[str] = []
        self._tree_dirty = True

    def add_defect(self, defect: dict):
        """Add a defect dict to the library and update all indices."""
        defect_id = defect["defect_id"]
        self._defects[defect_id] = defect

        foil = defect.get("foil_number")
        if foil is not None:
            self._by_foil[foil].append(defect_id)

        for zone_id in defect.get("zone_ids", []):
            self._by_zone[zone_id].append(defect_id)

        centroid = defect.get("centroid_mm")
        if centroid is not None:
            self._centroids[defect_id] = np.asarray(centroid)

        self._tree_dirty = True

    def get_defect(self, defect_id: str) -> dict | None:
        """Retrieve a single defect by ID."""
        return self._defects.get(defect_id)

    def get_defects_by_foil(self, foil_number: int) -> list[dict]:
        """Return all defects for a given foil number."""
        ids = self._by_foil.get(foil_number, [])
        return [self._defects[did] for did in ids if did in self._defects]

    def get_defects_by_zone(self, zone_id: str) -> list[dict]:
        """Return all defects assigned to a particular zone."""
        ids = self._by_zone.get(zone_id, [])
        return [self._defects[did] for did in ids if did in self._defects]

    def find_adjacent_defects(self, defect_id: str, threshold_mm: float = 5.0) -> list[dict]:
        """Find all defects whose centroid is within threshold_mm of the given defect."""
        if defect_id not in self._centroids:
            return []

        self._rebuild_kdtree()

        center = self._centroids[defect_id]
        if self._kdtree is None:
            return []

        indices = self._kdtree.query_ball_point(center, r=threshold_mm)
        adjacent = []
        for idx in indices:
            neighbor_id = self._tree_ids[idx]
            if neighbor_id != defect_id:
                adjacent.append(self._defects[neighbor_id])
        return adjacent

    def check_cross_zone_limit(
        self, zone_list: list[str], defect_type: str, max_count: int
    ) -> bool:
        """Return True if the count of defects matching defect_type across
        the given zones exceeds max_count."""
        seen_ids = set()
        for zone_id in zone_list:
            for defect in self.get_defects_by_zone(zone_id):
                did = defect["defect_id"]
                if did in seen_ids:
                    continue
                dtype = defect.get("defect_type", defect.get("classification", ""))
                if dtype == defect_type:
                    seen_ids.add(did)
        return len(seen_ids) > max_count

    def get_statistics(self) -> dict:
        """Aggregate statistics across the entire library."""
        total = len(self._defects)
        if total == 0:
            return {
                "total_defects": 0,
                "foils_with_defects": 0,
                "zones_with_defects": 0,
                "disposition_counts": {},
                "avg_depth_mm": 0.0,
                "max_depth_mm": 0.0,
            }

        dispositions: dict[str, int] = {}
        depths = []
        for d in self._defects.values():
            disp = d.get("disposition", "UNKNOWN")
            dispositions[disp] = dispositions.get(disp, 0) + 1
            depth = d.get("max_depth_mm", d.get("depth_mm", 0.0))
            depths.append(depth)

        depths_arr = np.array(depths)
        return {
            "total_defects": total,
            "foils_with_defects": len(self._by_foil),
            "zones_with_defects": len(self._by_zone),
            "disposition_counts": dispositions,
            "avg_depth_mm": float(depths_arr.mean()),
            "max_depth_mm": float(depths_arr.max()),
        }

    def _rebuild_kdtree(self):
        if not self._tree_dirty:
            return
        if not self._centroids:
            self._kdtree = None
            self._tree_ids = []
            self._tree_dirty = False
            return
        self._tree_ids = list(self._centroids.keys())
        points = np.array([self._centroids[did] for did in self._tree_ids])
        self._kdtree = cKDTree(points)
        self._tree_dirty = False

    def __len__(self):
        return len(self._defects)

    def __iter__(self):
        return iter(self._defects.values())
