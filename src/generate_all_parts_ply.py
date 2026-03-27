"""Generate synthetic scan and CAD PLY files for all rotor parts.

Reads rotor_configurations.json and produces a pair of PLY files
(scan + CAD) for every part that doesn't already have data on disk.
Geometry scales realistically with stage number and blade count.

Usage:
    python generate_all_parts_ply.py
"""

import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))
from o3d_compat import PointCloud, write_point_cloud

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "rotor_configurations.json")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

SKIP_PARTS = {"4119905", "4134613"}


def _seed_for_part(part_number: str) -> int:
    """Deterministic seed derived from part number string."""
    return int("".join(c for c in part_number if c.isdigit())) % (2**31)


# ---------------------------------------------------------------------------
# Stage-dependent geometry parameters
# ---------------------------------------------------------------------------

def _stage_params(stage: int, blade_count: int) -> dict:
    """Return physical dimensions that scale with compressor stage."""
    stage_frac = (stage - 1) / 8.0  # 0.0 for stage 1, 1.0 for stage 9

    bore_radius = 0.028 + 0.022 * stage_frac
    disk_rim_radius = 0.048 + 0.030 * stage_frac
    disk_height = 0.014 + 0.010 * stage_frac

    blade_length = 0.038 - 0.018 * stage_frac
    chord_base = 0.014 - 0.005 * stage_frac
    blade_chord = max(chord_base, 0.005)
    blade_thickness = 0.003 - 0.0012 * stage_frac

    target_total = int(50_000 + 100_000 * stage_frac)
    target_total = min(target_total, 150_000)
    target_total = max(target_total, 50_000)

    disk_frac = 0.25
    n_disk = max(8000, int(target_total * disk_frac))
    ppb = max(300, int((target_total - n_disk) / blade_count))

    return dict(
        bore_radius=bore_radius,
        disk_rim_radius=disk_rim_radius,
        disk_height=disk_height,
        blade_length=blade_length,
        blade_chord=blade_chord,
        blade_thickness=blade_thickness,
        n_disk=n_disk,
        ppb=ppb,
    )


# ---------------------------------------------------------------------------
# Geometry primitives (reuses logic from generate_synthetic_data.py)
# ---------------------------------------------------------------------------

def _make_disk(inner_r, outer_r, height, n_points):
    pts = []

    n_bore = n_points // 5
    theta = np.random.uniform(0, 2 * np.pi, n_bore)
    z = np.random.uniform(-height / 2, height / 2, n_bore)
    pts.append(np.column_stack([inner_r * np.cos(theta),
                                 inner_r * np.sin(theta), z]))

    n_web = n_points // 3
    theta = np.random.uniform(0, 2 * np.pi, n_web)
    r = np.random.uniform(inner_r, outer_r, n_web)
    z = np.random.uniform(-height / 2, height / 2, n_web)
    pts.append(np.column_stack([r * np.cos(theta), r * np.sin(theta), z]))

    n_rim = n_points // 4
    rim_h = height * 1.2
    theta = np.random.uniform(0, 2 * np.pi, n_rim)
    z = np.random.uniform(-rim_h / 2, rim_h / 2, n_rim)
    r = np.random.uniform(outer_r * 0.95, outer_r, n_rim)
    pts.append(np.column_stack([r * np.cos(theta), r * np.sin(theta), z]))

    n_face = n_points // 5
    for z_val in [-height / 2, height / 2]:
        theta = np.random.uniform(0, 2 * np.pi, n_face)
        r = np.random.uniform(inner_r, outer_r, n_face)
        z = np.full(n_face, z_val) + np.random.normal(0, height * 0.01, n_face)
        pts.append(np.column_stack([r * np.cos(theta), r * np.sin(theta), z]))

    return np.vstack(pts)


def _airfoil_profile(t):
    yt = 5 * 0.12 * (
        0.2969 * np.sqrt(np.abs(t))
        - 0.1260 * t
        - 0.3516 * t**2
        + 0.2843 * t**3
        - 0.1015 * t**4
    )
    return yt


def _make_blade(angle, rim_r, length, chord, thickness, n_points):
    span_frac = np.random.uniform(0, 1, n_points)
    r = rim_r + span_frac * length

    taper = 1.0 - 0.35 * span_frac
    twist = np.radians(15.0 * span_frac)
    local_chord = chord * taper
    local_thick = thickness * taper

    c_frac = np.random.uniform(0.0, 1.0, n_points)
    thick_profile = _airfoil_profile(c_frac)
    side = np.random.choice([-1, 1], n_points)
    z_local = side * thick_profile * local_thick

    c_pos = (c_frac - 0.5) * local_chord
    camber = 0.04 * local_chord * np.sin(np.pi * c_frac)
    z_local += camber

    le_mask = np.random.random(n_points) < 0.08
    te_mask = np.random.random(n_points) < 0.08
    c_pos[le_mask] = -0.5 * local_chord[le_mask]
    c_pos[te_mask] = 0.5 * local_chord[te_mask]
    z_local[le_mask] = 0.0
    z_local[te_mask] = 0.0

    x_tw = c_pos * np.cos(twist) - z_local * np.sin(twist)
    z_tw = c_pos * np.sin(twist) + z_local * np.cos(twist)

    cos_a, sin_a = np.cos(angle), np.sin(angle)
    x = r * cos_a - x_tw * sin_a
    y = r * sin_a + x_tw * cos_a
    return np.column_stack([x, y, z_tw])


# ---------------------------------------------------------------------------
# Defect injection
# ---------------------------------------------------------------------------

def _add_nick(pts, center, radius, depth, direction):
    d = np.linalg.norm(pts - center, axis=1)
    mask = d < radius
    direction = direction / (np.linalg.norm(direction) + 1e-12)
    t = 1.0 - d[mask] / radius
    pts[mask] += np.outer(t * depth, direction)
    return int(mask.sum())


def _add_dent(pts, center, radius, depth, direction):
    d = np.linalg.norm(pts - center, axis=1)
    mask = d < radius * 2
    direction = direction / (np.linalg.norm(direction) + 1e-12)
    profile = np.exp(-0.5 * (d[mask] / radius) ** 2) * depth
    pts[mask] += np.outer(profile, direction)
    return int(mask.sum())


def _inject_defects(scan_pts, blade_ranges, params, rng):
    """Place 2-4 random defects on randomly chosen blades."""
    n_defects = rng.integers(2, 5)
    chosen = rng.choice(len(blade_ranges), size=min(n_defects, len(blade_ranges)), replace=False)
    defect_log = []

    for idx in chosen:
        blade_num, start, end, angle = blade_ranges[idx]
        blade_pts = scan_pts[start:end]
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        inward = -np.array([cos_a, sin_a, 0.0])

        mid_r = params["disk_rim_radius"] + params["blade_length"] * rng.uniform(0.2, 0.8)
        center = np.array([mid_r * cos_a, mid_r * sin_a, rng.uniform(-0.001, 0.001)])

        kind = rng.choice(["nick", "dent"])
        if kind == "nick":
            r = rng.uniform(0.001, 0.003)
            dep = rng.uniform(0.0001, 0.0004)
            n_aff = _add_nick(blade_pts, center, r, dep, inward)
            defect_log.append(f"    blade {blade_num}: nick ({dep*1000:.2f}mm deep, {n_aff} pts)")
        else:
            r = rng.uniform(0.002, 0.005)
            dep = rng.uniform(0.00005, 0.0002)
            n_aff = _add_dent(blade_pts, center, r, dep, inward)
            defect_log.append(f"    blade {blade_num}: dent ({dep*1000:.2f}mm deep, {n_aff} pts)")

        scan_pts[start:end] = blade_pts

    return defect_log


# ---------------------------------------------------------------------------
# Per-part generation
# ---------------------------------------------------------------------------

def _generate_part(part_cfg, data_dir):
    part_num = part_cfg["part_number"]
    stage = part_cfg["stage"]
    blade_count = part_cfg["blade_count"]
    desc = part_cfg["description"]

    rng = np.random.default_rng(_seed_for_part(part_num))
    np.random.seed(_seed_for_part(part_num))

    params = _stage_params(stage, blade_count)

    print(f"  [{desc}] part={part_num}  stage={stage}  blades={blade_count}")
    print(f"    disk R={params['disk_rim_radius']*1000:.1f}mm  "
          f"blade L={params['blade_length']*1000:.1f}mm  "
          f"chord={params['blade_chord']*1000:.1f}mm  "
          f"disk pts={params['n_disk']}  ppb={params['ppb']}")

    disk_pts = _make_disk(
        params["bore_radius"], params["disk_rim_radius"],
        params["disk_height"], params["n_disk"],
    )

    angles = np.linspace(0, 2 * np.pi, blade_count, endpoint=False)
    angles += np.radians(25.0)

    all_pts = [disk_pts]
    blade_ranges = []
    for i, a in enumerate(angles):
        bp = _make_blade(
            a, params["disk_rim_radius"], params["blade_length"],
            params["blade_chord"], params["blade_thickness"], params["ppb"],
        )
        start = sum(len(p) for p in all_pts)
        all_pts.append(bp)
        blade_ranges.append((i + 1, start, start + len(bp), a))

    cad_pts = np.vstack(all_pts)

    cad_pcd = PointCloud(cad_pts)
    cad_path = os.path.join(data_dir, f"cad_{part_num}.ply")
    write_point_cloud(cad_path, cad_pcd)
    cad_size = os.path.getsize(cad_path)
    print(f"    CAD: {len(cad_pts):>7,} pts  ({cad_size / 1024:.0f} KB) -> {os.path.basename(cad_path)}")

    scan_pts = cad_pts.copy()
    noise_sigma = 0.00005  # 0.05 mm
    scan_pts += rng.normal(0, noise_sigma, scan_pts.shape)

    defect_log = _inject_defects(scan_pts, blade_ranges, params, rng)

    scan_pcd = PointCloud(scan_pts)
    scan_path = os.path.join(data_dir, f"scan_{part_num}.ply")
    write_point_cloud(scan_path, scan_pcd)
    scan_size = os.path.getsize(scan_path)
    print(f"    Scan: {len(scan_pts):>7,} pts  ({scan_size / 1024:.0f} KB) -> {os.path.basename(scan_path)}")

    if defect_log:
        print("    Defects injected:")
        for line in defect_log:
            print(line)

    return cad_path, scan_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 65)
    print("  Generate All Parts PLY — Synthetic IBR Point Clouds")
    print("=" * 65)

    with open(CONFIG_PATH) as f:
        parts = json.load(f)

    os.makedirs(DATA_DIR, exist_ok=True)

    to_generate = [p for p in parts if p["part_number"] not in SKIP_PARTS]
    print(f"\n  Config loaded: {len(parts)} total parts, "
          f"skipping {len(SKIP_PARTS)} ({', '.join(sorted(SKIP_PARTS))})")
    print(f"  Generating {len(to_generate)} part pairs into {DATA_DIR}\n")

    t0 = time.perf_counter()
    generated = []

    for i, part_cfg in enumerate(to_generate, 1):
        print(f"\n[{i}/{len(to_generate)}] -----------------------------------------")
        pair = _generate_part(part_cfg, DATA_DIR)
        generated.append(pair)

    elapsed = time.perf_counter() - t0
    print(f"\n{'=' * 65}")
    print(f"  Done. Generated {len(generated)} pairs ({len(generated) * 2} files)")
    print(f"  Total time: {elapsed:.1f}s")
    print(f"{'=' * 65}")


if __name__ == "__main__":
    main()
