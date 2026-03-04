"""Generate synthetic IBR point clouds (CAD reference + simulated scan with defects).

Creates realistic test data for pipeline validation when real scanner data
is not available. Generates a rotor disk with N blades and introduces
controlled synthetic defects.

Usage:
    python generate_synthetic_data.py [output_dir] [n_blades] [points_per_blade]
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))
from o3d_compat import PointCloud, write_point_cloud


def _make_disk(inner_radius, outer_radius, height, n_points=5000):
    theta = np.random.uniform(0, 2 * np.pi, n_points)
    r = np.random.uniform(inner_radius, outer_radius, n_points)
    z = np.random.uniform(-height / 2, height / 2, n_points)
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    return np.column_stack([x, y, z])


def _make_blade(base_angle, inner_radius, blade_length, chord, thickness, n_points=10000):
    span_frac = np.random.uniform(0, 1, n_points)
    r = inner_radius + span_frac * blade_length

    taper = 1.0 - 0.4 * span_frac
    local_chord = chord * taper
    local_thickness = thickness * taper

    c = np.random.uniform(-0.5, 0.5, n_points) * local_chord
    z = np.random.uniform(-0.5, 0.5, n_points) * local_thickness

    surface_selector = np.random.randint(0, 6, n_points)

    top = surface_selector == 0
    bot = surface_selector == 1
    z[top] = 0.5 * local_thickness[top]
    z[bot] = -0.5 * local_thickness[bot]

    le = surface_selector == 2
    te = surface_selector == 3
    c[le] = -0.5 * local_chord[le]
    c[te] = 0.5 * local_chord[te]

    tip = surface_selector == 4
    root = surface_selector == 5
    r[tip] = inner_radius + blade_length
    r[root] = inner_radius

    x_local = r
    y_local = c

    cos_a = np.cos(base_angle)
    sin_a = np.sin(base_angle)
    x = x_local * cos_a - y_local * sin_a
    y = x_local * sin_a + y_local * cos_a

    return np.column_stack([x, y, z])


def _add_nick(points, center, radius=0.0005, depth=0.00005, direction=None):
    dists = np.linalg.norm(points - center, axis=1)
    mask = dists < radius
    if direction is None:
        direction = np.array([0.0, 0.0, -1.0])
    direction = direction / (np.linalg.norm(direction) + 1e-12)
    t = 1.0 - (dists[mask] / radius)
    displacement = np.outer(t * depth, direction)
    points[mask] = points[mask] + displacement
    return mask


def _add_dent(points, center, radius=0.002, depth=0.00003, direction=None):
    dists = np.linalg.norm(points - center, axis=1)
    mask = dists < radius * 2
    if direction is None:
        direction = np.array([0.0, 0.0, -1.0])
    direction = direction / (np.linalg.norm(direction) + 1e-12)
    sigma = radius
    profile = np.exp(-0.5 * (dists[mask] / sigma) ** 2) * depth
    displacement = np.outer(profile, direction)
    points[mask] = points[mask] + displacement
    return mask


def _add_gouge(points, center, axis, length=0.003, width=0.001, depth=0.00008, direction=None):
    axis = axis / (np.linalg.norm(axis) + 1e-12)
    if direction is None:
        direction = np.array([0.0, 0.0, -1.0])
    direction = direction / (np.linalg.norm(direction) + 1e-12)

    diff = points - center
    along = np.dot(diff, axis)
    across = diff - np.outer(along, axis)
    cross_dist = np.linalg.norm(across, axis=1)

    mask = (np.abs(along) < length / 2) & (cross_dist < width / 2)
    if not np.any(mask):
        return mask

    along_factor = 1.0 - (2.0 * np.abs(along[mask]) / length) ** 2
    cross_factor = 1.0 - (2.0 * cross_dist[mask] / width) ** 2
    profile = depth * np.maximum(along_factor, 0) * np.maximum(cross_factor, 0)
    displacement = np.outer(profile, direction)
    points[mask] = points[mask] + displacement
    return mask


def generate_synthetic_data(output_dir="data", n_blades=5, points_per_blade=10000):
    """Generate synthetic CAD reference and scan PLY files."""
    os.makedirs(output_dir, exist_ok=True)
    np.random.seed(42)

    inner_radius = 0.050
    outer_radius = 0.065
    disk_height = 0.010
    blade_length = 0.040
    blade_chord = 0.015
    blade_thickness = 0.003

    disk_points = _make_disk(inner_radius, outer_radius, disk_height,
                             n_points=points_per_blade // 2)

    blade_angles = np.linspace(0, 2 * np.pi, n_blades, endpoint=False)

    all_cad_points = [disk_points]
    blade_point_ranges = []

    for i, angle in enumerate(blade_angles):
        blade_pts = _make_blade(
            angle, outer_radius, blade_length, blade_chord, blade_thickness,
            n_points=points_per_blade,
        )
        start_idx = sum(len(p) for p in all_cad_points)
        all_cad_points.append(blade_pts)
        end_idx = start_idx + len(blade_pts)
        blade_point_ranges.append((i + 1, start_idx, end_idx, angle))

    cad_points = np.vstack(all_cad_points)
    print(f"  Generated CAD reference: {len(cad_points):,} points, {n_blades} blades")

    cad_pcd = PointCloud(cad_points)
    cad_pcd.estimate_normals(k=30)
    cad_path = os.path.join(output_dir, "cad_reference.ply")
    write_point_cloud(cad_path, cad_pcd)
    print(f"  Saved: {cad_path}")

    scan_points = cad_points.copy()
    noise_sigma = 0.000003  # 0.003mm in meters
    scan_points += np.random.normal(0, noise_sigma, scan_points.shape)

    defect_log = []

    for blade_num, start, end, angle in blade_point_ranges:
        blade_pts = scan_points[start:end]
        cos_a, sin_a = np.cos(angle), np.sin(angle)

        if blade_num == 1:
            le_center = np.array([
                (outer_radius + blade_length * 0.3) * cos_a - (-blade_chord * 0.45) * sin_a,
                (outer_radius + blade_length * 0.3) * sin_a + (-blade_chord * 0.45) * cos_a,
                0.0,
            ])
            inward = -np.array([cos_a, sin_a, 0.0])
            _add_nick(blade_pts, le_center, radius=0.002, depth=0.00025, direction=inward)
            defect_log.append("  Blade 1: nick on LE (0.25mm deep)")

        elif blade_num == 2:
            mid_radius = outer_radius + blade_length * 0.5
            surf_center = np.array([mid_radius * cos_a, mid_radius * sin_a, 0.001])
            _add_dent(blade_pts, surf_center, radius=0.004, depth=0.00015,
                      direction=np.array([0, 0, -1.0]))
            defect_log.append("  Blade 2: dent on surface (0.15mm deep)")

        elif blade_num == 3:
            defect_log.append("  Blade 3: clean (no defects)")

        elif blade_num == 4:
            mid_radius = outer_radius + blade_length * 0.5
            te_center = np.array([
                mid_radius * cos_a - (blade_chord * 0.45) * sin_a,
                mid_radius * sin_a + (blade_chord * 0.45) * cos_a,
                0.0,
            ])
            tangent = np.array([-sin_a, cos_a, 0.0])
            inward = -np.array([cos_a, sin_a, 0.0])
            _add_gouge(blade_pts, te_center, axis=tangent, length=0.006,
                       width=0.003, depth=0.0004, direction=inward)
            defect_log.append("  Blade 4: gouge on TE (0.40mm deep)")

        elif blade_num == 5:
            for offset_frac in [0.2, 0.5, 0.8]:
                r_pos = outer_radius + blade_length * offset_frac
                nick_center = np.array([r_pos * cos_a, r_pos * sin_a, 0.0])
                inward = -np.array([cos_a, sin_a, 0.0])
                _add_nick(blade_pts, nick_center, radius=0.0015, depth=0.00018,
                          direction=inward)
            defect_log.append("  Blade 5: 3 nicks (0.18mm deep each)")

        scan_points[start:end] = blade_pts

    scan_pcd = PointCloud(scan_points)
    scan_pcd.estimate_normals(k=30)
    scan_path = os.path.join(output_dir, "sample_scan.ply")
    write_point_cloud(scan_path, scan_pcd)
    print(f"  Saved: {scan_path}")

    print(f"\n  Synthetic defects introduced:")
    for line in defect_log:
        print(line)

    return cad_path, scan_path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "data"
    blades = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    ppb = int(sys.argv[3]) if len(sys.argv) > 3 else 10000
    generate_synthetic_data(output_dir=out, n_blades=blades, points_per_blade=ppb)
