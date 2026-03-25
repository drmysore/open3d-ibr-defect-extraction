import numpy as np
import yaml
import os

MM_PER_INCH = 25.4


class ZoneClassification:
    """Phase 7: Map defects to P&W's 13-zone system and check compliance."""

    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config not found: {config_path}")
        with open(config_path) as f:
            full_config = yaml.safe_load(f)
        if "zone_classification" not in full_config:
            raise KeyError("Missing 'zone_classification' section in config")
        self.config = full_config["zone_classification"]

        self.zones = {z["id"]: z for z in self.config["zones"]}
        self.multi_zone_rule = self.config.get("multi_zone_rule", "most_restrictive")

    def execute(
        self, defects: list[dict], blade_geometry: dict | None = None
    ) -> list[dict]:
        for defect in defects:
            zone_ids = self._classify_zone(defect, blade_geometry)
            defect["zone_ids"] = zone_ids
            defect["zone_names"] = [
                self.zones[zid]["name"] for zid in zone_ids if zid in self.zones
            ]

            if zone_ids:
                limits = self._get_most_restrictive_limits(zone_ids)
                defect["applied_limits"] = limits
                defect["disposition"] = self._check_compliance(defect, limits)
                defect["rule_applied"] = self._format_rule(limits)
            else:
                defect["applied_limits"] = None
                defect["disposition"] = "SERVICEABLE"
                defect["rule_applied"] = "No zone matched — default pass"

            print(
                f"  [Phase 7] {defect['defect_id']}: "
                f"zones={zone_ids} -> {defect['disposition']}"
            )

        summary = self._disposition_summary(defects)
        print(
            f"  [Phase 7] Summary: "
            f"{summary.get('SERVICEABLE', 0)} serviceable, "
            f"{summary.get('BLEND', 0)} blend, "
            f"{summary.get('REPLACE', 0)} replace"
        )
        return defects

    def _classify_zone(
        self, defect: dict, blade_geometry: dict | None
    ) -> list[str]:
        classification = defect.get("classification", "surface")
        nearest_edge = defect.get("nearest_edge")

        height_pct = self._compute_span_pct(defect, blade_geometry)

        matched = []

        if classification == "edge" and nearest_edge == "LE":
            matched = self._match_edge_zones("edge_le", "LE", height_pct)
        elif classification == "edge" and nearest_edge == "TE":
            matched = self._match_edge_zones("edge_te", "TE", height_pct)
        else:
            matched = self._match_surface_zones(defect, blade_geometry)

        # Always check tip zones regardless of classification
        tip_zones = self._match_tip_zones(height_pct)
        for tz in tip_zones:
            if tz not in matched:
                matched.append(tz)

        if not matched:
            matched = ["C1"]

        return matched

    def _match_edge_zones(
        self, zone_type: str, edge: str, height_pct: float
    ) -> list[str]:
        matched = []
        for zid, zone in self.zones.items():
            ztype = zone.get("type", "")
            zedge = zone.get("edge")
            if ztype == zone_type or (zedge == edge and "edge" in ztype):
                pass
            else:
                continue
            span_start = zone.get("span_start_pct", 0.0)
            span_end = zone.get("span_end_pct", 100.0)
            if span_start <= height_pct <= span_end:
                matched.append(zid)
        return matched

    def _match_surface_zones(
        self, defect: dict, blade_geometry: dict | None
    ) -> list[str]:
        """Surface defects default to C1 unless geometry data classifies them."""
        if blade_geometry is None:
            return ["C1"]

        centroid = defect.get("centroid_mm")
        if centroid is None:
            return ["C1"]

        surface_type = blade_geometry.get("surface_type")
        if surface_type == "concave":
            return ["C2"]
        elif surface_type == "convex":
            return ["C1"]

        return ["C1"]

    def _match_tip_zones(self, height_pct: float) -> list[str]:
        matched = []
        for zid, zone in self.zones.items():
            if zone.get("type") not in ("tip", "tip_corner"):
                continue
            span_start = zone.get("span_start_pct", 0.0)
            span_end = zone.get("span_end_pct", 100.0)
            if span_start <= height_pct <= span_end:
                matched.append(zid)
        return matched

    def _compute_span_pct(
        self, defect: dict, blade_geometry: dict | None
    ) -> float:
        """Compute spanwise position as percentage of blade height."""
        if blade_geometry is None:
            return 50.0

        centroid = defect.get("centroid_mm")
        if centroid is None:
            return 50.0

        root_z = blade_geometry.get("root_z_mm", 0.0)
        tip_z = blade_geometry.get("tip_z_mm", 100.0)
        span = tip_z - root_z
        if abs(span) < 1e-6:
            return 50.0

        height = centroid[2] - root_z
        pct = (height / span) * 100.0
        return float(np.clip(pct, 0.0, 100.0))

    def _get_zone_limits(self, zone_id: str) -> dict | None:
        zone = self.zones.get(zone_id)
        if zone is None:
            return None
        return {
            "zone_id": zone_id,
            "max_depth_in": zone.get("max_depth_in", float("inf")),
            "max_length_in": zone.get("max_length_in", float("inf")),
            "severity": zone.get("severity", "STANDARD"),
        }

    def _get_most_restrictive_limits(self, zone_ids: list[str]) -> dict:
        limits_list = [
            self._get_zone_limits(zid) for zid in zone_ids
        ]
        limits_list = [lim for lim in limits_list if lim is not None]

        if not limits_list:
            return {
                "zone_id": "NONE",
                "max_depth_in": float("inf"),
                "max_length_in": float("inf"),
                "severity": "STANDARD",
            }

        most_restrictive = min(
            limits_list,
            key=lambda lim: (lim["max_depth_in"], lim["max_length_in"]),
        )
        most_restrictive["source_zones"] = zone_ids
        return most_restrictive

    def _check_compliance(self, defect: dict, limits: dict) -> str:
        depth_in = defect.get("depth_in", 0.0)
        length_in = defect.get("length_in", 0.0)

        max_depth = limits.get("max_depth_in", float("inf"))
        max_length = limits.get("max_length_in", float("inf"))

        if depth_in <= max_depth and length_in <= max_length:
            return "SERVICEABLE"

        blend_depth = max_depth * 1.5
        blend_length = max_length * 1.5

        if depth_in <= blend_depth and length_in <= blend_length:
            return "BLEND"

        return "REPLACE"

    def _format_rule(self, limits: dict) -> str:
        zone_id = limits.get("zone_id", "?")
        max_d = limits.get("max_depth_in", 0)
        max_l = limits.get("max_length_in", 0)
        return f"{zone_id}: depth<={max_d:.4f}\" length<={max_l:.4f}\""

    def _disposition_summary(self, defects: list[dict]) -> dict[str, int]:
        summary: dict[str, int] = {}
        for d in defects:
            disp = d.get("disposition", "UNKNOWN")
            summary[disp] = summary.get(disp, 0) + 1
        return summary
