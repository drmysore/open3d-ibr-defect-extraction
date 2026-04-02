"""Blade zone template creation and management system.

Maps Pratt & Whitney zone definitions onto blade boundaries for each
stage / part number.  Implements the "Template Creation" work stream
from the Sprint 6 plan.

Author: Supreeth Mysore | Hitachi Digital Services
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import yaml

MM_PER_INCH: float = 25.4

# Stage 5 reference dimensions (from P&W spec)
_STAGE5_TIP_WIDTH_MM: float = 79.1
_STAGE5_SPAN_HEIGHT_MM: float = 138.6
_STAGE5_STAGE_ID: int = 5

# Geometric ratios mirroring generate_all_parts_ply._stage_params
_BLADE_LENGTH_BASE: float = 0.038
_BLADE_LENGTH_TAPER: float = 0.018
_CHORD_BASE: float = 0.014
_CHORD_TAPER: float = 0.005
_CHORD_MIN: float = 0.005

# Tip / fillet / platform band heights as percentage of total span
_TIP_BAND_PCT: float = 8.0
_FILLET_BAND_PCT: float = 6.0
_PLATFORM_HEIGHT_PCT: float = 4.0


# ──────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────

@dataclass
class ZoneBounds:
    """Rectangular boundary of a single inspection zone on the blade."""

    zone_id: str
    name: str
    span_start_pct: float
    span_end_pct: float
    chord_start_pct: float
    chord_end_pct: float
    side: str  # "LE", "TE", "convex", "concave", "tip", "fillet", "platform"

    def area_pct(self) -> float:
        """Fractional area of the zone relative to full blade rectangle."""
        return (
            (self.span_end_pct - self.span_start_pct)
            * (self.chord_end_pct - self.chord_start_pct)
            / 1e4
        )


@dataclass
class BladeTemplate:
    """Complete zone template for a single blade part number."""

    part_number: str
    stage_id: int
    blade_count: int
    tip_width_mm: float
    span_height_mm: float
    le_offset_in: float = 0.080
    te_offset_in: float = 0.080
    zones: dict[str, ZoneBounds] = field(default_factory=dict)

    @property
    def le_offset_mm(self) -> float:
        return self.le_offset_in * MM_PER_INCH

    @property
    def te_offset_mm(self) -> float:
        return self.te_offset_in * MM_PER_INCH

    @property
    def le_strip_pct(self) -> float:
        """LE strip width expressed as % of total chord."""
        if self.tip_width_mm <= 0:
            return 0.0
        return (self.le_offset_mm / self.tip_width_mm) * 100.0

    @property
    def te_strip_pct(self) -> float:
        """TE strip width expressed as % of total chord."""
        if self.tip_width_mm <= 0:
            return 0.0
        return (self.te_offset_mm / self.tip_width_mm) * 100.0


# ──────────────────────────────────────────────────────────────────
# Template Manager
# ──────────────────────────────────────────────────────────────────

class TemplateManager:
    """Creates, validates, adjusts, and persists blade zone templates.

    Loads zone definitions from ``pipeline_config.yaml`` and part
    metadata from ``rotor_configurations.json`` to generate per-part
    zone boundary templates that downstream inspection phases consume.
    """

    def __init__(
        self,
        config_path: str = "config/pipeline_config.yaml",
        rotor_config_path: str = "config/rotor_configurations.json",
    ) -> None:
        base = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(base, os.pardir))

        self._resolve = lambda p: (
            p if os.path.isabs(p) else os.path.join(project_root, p)
        )

        pipeline_cfg_path = self._resolve(config_path)
        if not os.path.isfile(pipeline_cfg_path):
            raise FileNotFoundError(
                f"Pipeline config not found: {pipeline_cfg_path}"
            )
        with open(pipeline_cfg_path, encoding="utf-8") as fh:
            self._pipeline_cfg: dict[str, Any] = yaml.safe_load(fh)

        rotor_cfg_path = self._resolve(rotor_config_path)
        if not os.path.isfile(rotor_cfg_path):
            raise FileNotFoundError(
                f"Rotor config not found: {rotor_cfg_path}"
            )
        with open(rotor_cfg_path, encoding="utf-8") as fh:
            rotor_list: list[dict[str, Any]] = json.load(fh)

        self._parts: dict[str, dict[str, Any]] = {
            entry["part_number"]: entry for entry in rotor_list
        }

        zone_section = self._pipeline_cfg.get("zone_classification", {})
        self._zone_defs: dict[str, dict[str, Any]] = {
            z["id"]: z for z in zone_section.get("zones", [])
        }
        self._edge_threshold_in: float = zone_section.get(
            "edge_distance_threshold_inches", 0.080
        )

    # ── public API ────────────────────────────────────────────────

    def create_template(self, part_number: str) -> BladeTemplate:
        """Generate a :class:`BladeTemplate` for *part_number*.

        Resolves stage, blade count, and physical dimensions from the
        rotor configuration, then lays out all P&W zones.
        """
        part = self._parts.get(part_number)
        if part is None:
            raise KeyError(
                f"Part number '{part_number}' not found in rotor config"
            )

        stage = int(part["stage"])
        blade_count = int(part["blade_count"])
        tip_w, span_h = self._stage_dimensions(stage)

        tmpl = BladeTemplate(
            part_number=part_number,
            stage_id=stage,
            blade_count=blade_count,
            tip_width_mm=round(tip_w, 2),
            span_height_mm=round(span_h, 2),
            le_offset_in=self._edge_threshold_in,
            te_offset_in=self._edge_threshold_in,
        )

        tmpl.zones = self._generate_zones(tmpl)
        return tmpl

    def get_all_templates(self) -> list[BladeTemplate]:
        """Return templates for every part in the rotor configuration."""
        return [self.create_template(pn) for pn in self._parts]

    def compute_delta(
        self,
        as_flown_boundary: dict[str, np.ndarray],
        template_boundary: dict[str, np.ndarray],
    ) -> dict[str, dict[str, Any]]:
        """Compute per-side deltas between as-flown and template boundaries.

        Parameters
        ----------
        as_flown_boundary : dict
            Keys ``"LE"``, ``"TE"``, ``"tip"``, ``"root"`` each mapping to
            an (N, 3) array of boundary points.
        template_boundary : dict
            Same structure as *as_flown_boundary*.

        Returns
        -------
        dict
            Per-side dictionary with keys:
            ``shift_mm``  — mean displacement vector (3,)
            ``max_mm``    — maximum displacement magnitude
            ``rms_mm``    — RMS of displacement magnitudes
        """
        sides = {
            "side_1_LE": "LE",
            "side_2_TE": "TE",
            "side_3_tip": "tip",
            "side_4_root": "root",
        }
        result: dict[str, dict[str, Any]] = {}

        for label, key in sides.items():
            af = np.asarray(as_flown_boundary.get(key, np.empty((0, 3))))
            tb = np.asarray(template_boundary.get(key, np.empty((0, 3))))

            if af.size == 0 or tb.size == 0:
                result[label] = {
                    "shift_mm": np.zeros(3),
                    "max_mm": 0.0,
                    "rms_mm": 0.0,
                }
                continue

            n_pts = min(len(af), len(tb))
            diff = af[:n_pts] - tb[:n_pts]
            mags = np.linalg.norm(diff, axis=1)

            result[label] = {
                "shift_mm": diff.mean(axis=0),
                "max_mm": float(mags.max()),
                "rms_mm": float(np.sqrt(np.mean(mags ** 2))),
            }
        return result

    def adjust_zones(
        self,
        template: BladeTemplate,
        deltas: dict[str, dict[str, Any]],
    ) -> BladeTemplate:
        """Return a copy of *template* with zone bounds shifted by *deltas*.

        Delta mapping — each side's ``shift_mm`` is converted to a
        percentage offset and applied to the zones it affects:

        * side_1_LE  → LE zones' chord boundaries
        * side_2_TE  → TE zones' chord boundaries
        * side_3_tip → tip zones' span boundaries
        * side_4_root → fillet / platform zones' span boundaries
        """
        adjusted = copy.deepcopy(template)

        le_shift_pct = self._mm_to_chord_pct(
            deltas.get("side_1_LE", {}).get("shift_mm", np.zeros(3)),
            template.tip_width_mm,
        )
        te_shift_pct = self._mm_to_chord_pct(
            deltas.get("side_2_TE", {}).get("shift_mm", np.zeros(3)),
            template.tip_width_mm,
        )
        tip_shift_pct = self._mm_to_span_pct(
            deltas.get("side_3_tip", {}).get("shift_mm", np.zeros(3)),
            template.span_height_mm,
        )
        root_shift_pct = self._mm_to_span_pct(
            deltas.get("side_4_root", {}).get("shift_mm", np.zeros(3)),
            template.span_height_mm,
        )

        for zb in adjusted.zones.values():
            if zb.side == "LE":
                zb.chord_start_pct = _clamp(zb.chord_start_pct + le_shift_pct)
                zb.chord_end_pct = _clamp(zb.chord_end_pct + le_shift_pct)
            elif zb.side == "TE":
                zb.chord_start_pct = _clamp(zb.chord_start_pct + te_shift_pct)
                zb.chord_end_pct = _clamp(zb.chord_end_pct + te_shift_pct)
            elif zb.side == "tip":
                zb.span_start_pct = _clamp(zb.span_start_pct + tip_shift_pct)
                zb.span_end_pct = _clamp(zb.span_end_pct + tip_shift_pct)
            elif zb.side in ("fillet", "platform"):
                zb.span_start_pct = _clamp(
                    zb.span_start_pct + root_shift_pct
                )
                zb.span_end_pct = _clamp(zb.span_end_pct + root_shift_pct)

        return adjusted

    def validate_template(self, template: BladeTemplate) -> list[str]:
        """Return a list of validation errors found in *template*.

        Checks performed:
        1. Every zone's start < end for both span and chord.
        2. No two same-side zones overlap by more than 5 % of blade area.
        3. The union of all zones covers at least 90 % of the blade surface.
        4. LE/TE strip widths are consistent with the offset spec.
        """
        errors: list[str] = []

        for zid, zb in template.zones.items():
            if zb.span_start_pct >= zb.span_end_pct:
                errors.append(
                    f"{zid}: span_start ({zb.span_start_pct:.1f}) "
                    f">= span_end ({zb.span_end_pct:.1f})"
                )
            if zb.chord_start_pct >= zb.chord_end_pct:
                errors.append(
                    f"{zid}: chord_start ({zb.chord_start_pct:.1f}) "
                    f">= chord_end ({zb.chord_end_pct:.1f})"
                )

        by_side: dict[str, list[ZoneBounds]] = {}
        for zb in template.zones.values():
            by_side.setdefault(zb.side, []).append(zb)

        for side, zlist in by_side.items():
            for i, a in enumerate(zlist):
                for b in zlist[i + 1 :]:
                    overlap = self._overlap_area_pct(a, b)
                    if overlap > 5.0:
                        errors.append(
                            f"{a.zone_id} & {b.zone_id} ({side}): "
                            f"overlap {overlap:.1f}% of blade area"
                        )

        covered = self._total_coverage_pct(template)
        if covered < 90.0:
            errors.append(
                f"Total coverage {covered:.1f}% is below 90% threshold"
            )

        expected_le_pct = template.le_strip_pct
        for zid, zb in template.zones.items():
            if zb.side == "LE":
                actual_width = zb.chord_end_pct - zb.chord_start_pct
                if abs(actual_width - expected_le_pct) > 1.0:
                    errors.append(
                        f"{zid}: LE strip width {actual_width:.1f}% "
                        f"vs expected {expected_le_pct:.1f}%"
                    )

        expected_te_pct = template.te_strip_pct
        for zid, zb in template.zones.items():
            if zb.side == "TE":
                actual_width = zb.chord_end_pct - zb.chord_start_pct
                if abs(actual_width - expected_te_pct) > 1.0:
                    errors.append(
                        f"{zid}: TE strip width {actual_width:.1f}% "
                        f"vs expected {expected_te_pct:.1f}%"
                    )

        return errors

    def export_template(self, template: BladeTemplate, path: str) -> None:
        """Serialize *template* to a JSON file at *path*."""
        data = _template_to_dict(template)
        resolved = self._resolve(path)
        os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=_json_default)

    def load_template(self, path: str) -> BladeTemplate:
        """Deserialize a :class:`BladeTemplate` from a JSON file."""
        resolved = self._resolve(path)
        with open(resolved, encoding="utf-8") as fh:
            data: dict[str, Any] = json.load(fh)
        return _dict_to_template(data)

    # ── private helpers ───────────────────────────────────────────

    def _stage_dimensions(self, stage: int) -> tuple[float, float]:
        """Scale tip width and span height for *stage*.

        Uses the same geometric ratios as
        ``generate_all_parts_ply._stage_params``: blade length and chord
        are linear functions of ``(stage - 1) / 8``.
        """
        frac = (stage - 1) / 8.0
        ref_frac = (_STAGE5_STAGE_ID - 1) / 8.0

        blade_length = _BLADE_LENGTH_BASE - _BLADE_LENGTH_TAPER * frac
        ref_length = _BLADE_LENGTH_BASE - _BLADE_LENGTH_TAPER * ref_frac

        chord = max(_CHORD_BASE - _CHORD_TAPER * frac, _CHORD_MIN)
        ref_chord = max(_CHORD_BASE - _CHORD_TAPER * ref_frac, _CHORD_MIN)

        span_ratio = blade_length / ref_length if ref_length else 1.0
        chord_ratio = chord / ref_chord if ref_chord else 1.0

        tip_width_mm = _STAGE5_TIP_WIDTH_MM * chord_ratio
        span_height_mm = _STAGE5_SPAN_HEIGHT_MM * span_ratio

        return tip_width_mm, span_height_mm

    def _generate_zones(self, tmpl: BladeTemplate) -> dict[str, ZoneBounds]:
        """Lay out all zone rectangles inside the blade boundary."""
        zones: dict[str, ZoneBounds] = {}

        le_pct = tmpl.le_strip_pct
        te_pct = tmpl.te_strip_pct

        # chord bands (percentages of total chord)
        le_end = le_pct
        te_start = 100.0 - te_pct
        center_mid = (le_end + te_start) / 2.0

        # span bands
        platform_top = _PLATFORM_HEIGHT_PCT
        fillet_top = platform_top + _FILLET_BAND_PCT
        tip_bottom = 100.0 - _TIP_BAND_PCT

        # ----- LE zones A1-A3 -----
        for zdef in self._iter_zone_defs("edge_le"):
            zones[zdef["id"]] = ZoneBounds(
                zone_id=zdef["id"],
                name=zdef["name"],
                span_start_pct=zdef.get("span_start_pct", 0.0),
                span_end_pct=zdef.get("span_end_pct", 100.0),
                chord_start_pct=0.0,
                chord_end_pct=le_end,
                side="LE",
            )

        # ----- TE zones B1-B3 -----
        for zdef in self._iter_zone_defs("edge_te"):
            zones[zdef["id"]] = ZoneBounds(
                zone_id=zdef["id"],
                name=zdef["name"],
                span_start_pct=zdef.get("span_start_pct", 0.0),
                span_end_pct=zdef.get("span_end_pct", 100.0),
                chord_start_pct=te_start,
                chord_end_pct=100.0,
                side="TE",
            )

        # ----- Convex surface C1-C4 (left half of center strip) -----
        c_zones = [z for z in self._iter_zone_defs("surface")
                    if z["id"].startswith("C")]
        n_c = max(len(c_zones), 1)
        span_band = (tip_bottom - fillet_top) / n_c
        for i, zdef in enumerate(c_zones):
            zones[zdef["id"]] = ZoneBounds(
                zone_id=zdef["id"],
                name=zdef["name"],
                span_start_pct=fillet_top + i * span_band,
                span_end_pct=fillet_top + (i + 1) * span_band,
                chord_start_pct=le_end,
                chord_end_pct=center_mid,
                side="convex",
            )

        # ----- Concave surface D1-D4 (right half of center strip) -----
        d_zones = [z for z in self._iter_zone_defs("surface")
                    if z["id"].startswith("D")]
        n_d = max(len(d_zones), 1)
        span_band_d = (tip_bottom - fillet_top) / n_d
        for i, zdef in enumerate(d_zones):
            zones[zdef["id"]] = ZoneBounds(
                zone_id=zdef["id"],
                name=zdef["name"],
                span_start_pct=fillet_top + i * span_band_d,
                span_end_pct=fillet_top + (i + 1) * span_band_d,
                chord_start_pct=center_mid,
                chord_end_pct=te_start,
                side="concave",
            )

        # ----- Tip zone H -----
        tip_def = self._zone_defs.get("H")
        if tip_def:
            zones["H"] = ZoneBounds(
                zone_id="H",
                name=tip_def["name"],
                span_start_pct=tip_bottom,
                span_end_pct=100.0,
                chord_start_pct=le_end,
                chord_end_pct=te_start,
                side="tip",
            )

        # ----- Tip corners G1 (LE corner), G2 (TE corner) -----
        g1_def = self._zone_defs.get("G1")
        if g1_def:
            zones["G1"] = ZoneBounds(
                zone_id="G1",
                name=g1_def["name"],
                span_start_pct=tip_bottom,
                span_end_pct=100.0,
                chord_start_pct=0.0,
                chord_end_pct=le_end,
                side="tip",
            )
        g2_def = self._zone_defs.get("G2")
        if g2_def:
            zones["G2"] = ZoneBounds(
                zone_id="G2",
                name=g2_def["name"],
                span_start_pct=tip_bottom,
                span_end_pct=100.0,
                chord_start_pct=te_start,
                chord_end_pct=100.0,
                side="tip",
            )

        # ----- Fillet zones E1, E2a-E2d, E3 -----
        fillet_defs = sorted(
            self._iter_zone_defs("fillet"),
            key=lambda z: z.get("priority", 99),
        )
        n_f = max(len(fillet_defs), 1)
        chord_band_f = (te_start - le_end) / n_f
        for i, zdef in enumerate(fillet_defs):
            zones[zdef["id"]] = ZoneBounds(
                zone_id=zdef["id"],
                name=zdef["name"],
                span_start_pct=platform_top,
                span_end_pct=fillet_top,
                chord_start_pct=le_end + i * chord_band_f,
                chord_end_pct=le_end + (i + 1) * chord_band_f,
                side="fillet",
            )

        # ----- Platform J -----
        j_def = self._zone_defs.get("J")
        if j_def:
            zones["J"] = ZoneBounds(
                zone_id="J",
                name=j_def["name"],
                span_start_pct=0.0,
                span_end_pct=platform_top,
                chord_start_pct=0.0,
                chord_end_pct=100.0,
                side="platform",
            )

        return zones

    def _iter_zone_defs(self, zone_type: str):
        """Yield zone definitions matching *zone_type*, ordered by priority."""
        return sorted(
            (z for z in self._zone_defs.values() if z.get("type") == zone_type),
            key=lambda z: z.get("priority", 99),
        )

    # ── geometry helpers ──────────────────────────────────────────

    @staticmethod
    def _mm_to_chord_pct(shift: np.ndarray, tip_width_mm: float) -> float:
        """Convert a displacement vector to a chord-wise % offset."""
        if tip_width_mm <= 0:
            return 0.0
        chord_component = float(np.linalg.norm(shift[:2]))
        return (chord_component / tip_width_mm) * 100.0

    @staticmethod
    def _mm_to_span_pct(shift: np.ndarray, span_height_mm: float) -> float:
        """Convert a displacement vector to a span-wise % offset."""
        if span_height_mm <= 0:
            return 0.0
        span_component = abs(float(shift[2])) if len(shift) > 2 else 0.0
        return (span_component / span_height_mm) * 100.0

    @staticmethod
    def _overlap_area_pct(a: ZoneBounds, b: ZoneBounds) -> float:
        """Overlap between two zones as % of total blade area."""
        s_lo = max(a.span_start_pct, b.span_start_pct)
        s_hi = min(a.span_end_pct, b.span_end_pct)
        c_lo = max(a.chord_start_pct, b.chord_start_pct)
        c_hi = min(a.chord_end_pct, b.chord_end_pct)
        if s_lo >= s_hi or c_lo >= c_hi:
            return 0.0
        return (s_hi - s_lo) * (c_hi - c_lo) / 1e4 * 100.0

    @staticmethod
    def _total_coverage_pct(template: BladeTemplate) -> float:
        """Approximate total blade area covered by at least one zone.

        Uses a 100x100 grid sampling to account for overlaps.
        """
        grid = np.zeros((100, 100), dtype=bool)
        for zb in template.zones.values():
            s0 = int(np.clip(zb.span_start_pct, 0, 100))
            s1 = int(np.clip(zb.span_end_pct, 0, 100))
            c0 = int(np.clip(zb.chord_start_pct, 0, 100))
            c1 = int(np.clip(zb.chord_end_pct, 0, 100))
            grid[s0:s1, c0:c1] = True
        return float(grid.sum()) / grid.size * 100.0


# ──────────────────────────────────────────────────────────────────
# Serialization helpers
# ──────────────────────────────────────────────────────────────────

def _json_default(obj: Any) -> Any:
    """Handle numpy types during JSON serialization."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _template_to_dict(template: BladeTemplate) -> dict[str, Any]:
    """Convert a :class:`BladeTemplate` to a plain dict for JSON."""
    d = asdict(template)
    d["zones"] = {
        zid: asdict(zb) for zid, zb in template.zones.items()
    }
    return d


def _dict_to_template(data: dict[str, Any]) -> BladeTemplate:
    """Reconstruct a :class:`BladeTemplate` from a deserialized dict."""
    zones_raw = data.pop("zones", {})
    tmpl = BladeTemplate(**data)
    for zid, zb_dict in zones_raw.items():
        tmpl.zones[zid] = ZoneBounds(**zb_dict)
    return tmpl


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to [*lo*, *hi*]."""
    return max(lo, min(hi, value))


# ──────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────

def main() -> None:
    """Generate and validate templates for all configured rotor parts."""
    mgr = TemplateManager()
    templates = mgr.get_all_templates()

    print(f"Generated {len(templates)} blade templates\n")
    for tmpl in templates:
        errors = mgr.validate_template(tmpl)
        status = "OK" if not errors else f"{len(errors)} error(s)"
        print(
            f"  {tmpl.part_number:>12s}  stage={tmpl.stage_id}  "
            f"blades={tmpl.blade_count:>3d}  "
            f"tip={tmpl.tip_width_mm:>6.1f}mm  "
            f"span={tmpl.span_height_mm:>6.1f}mm  "
            f"zones={len(tmpl.zones):>2d}  [{status}]"
        )
        for err in errors:
            print(f"        ! {err}")

    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        os.pardir,
        "output",
        "templates",
    )
    os.makedirs(out_dir, exist_ok=True)
    for tmpl in templates:
        path = os.path.join(out_dir, f"template_{tmpl.part_number}.json")
        mgr.export_template(tmpl, path)
    print(f"\nExported {len(templates)} templates to {os.path.abspath(out_dir)}")


if __name__ == "__main__":
    main()
