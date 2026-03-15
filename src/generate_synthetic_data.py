"""Generate synthetic IBR point clouds (CAD reference + simulated scan with defects).

Creates realistic test data matching real F135 compressor IBR geometry:
  - Dense, tightly-packed blades (37+ per stage, matching NX convergent bodies)
  - Thick rotor disk with inner bore and rim
  - Airfoil-shaped blade cross-sections (cambered, tapered)
  - Controlled synthetic defects on selected blades

Usage:
    python generate_synthetic_data.py [output_dir] [n_blades] [points_per_blade]
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))
from o3d_compat import PointCloud, write_point_cloud


def _make_disk(inner_radius, outer_radius, height, n_points=15000):
    """Thick rotor disk with bore, web, and rim — matching real IBR proportions."""
    pts = []

    # Bore inner surface (cylindrical)
    n_bore = n_points // 5
    theta = np.random.uniform(0, 2 * np.pi, n_bore)
    z = np.random.uniform(-height / 2, height / 2, n_bore)
    x = inner_radius * np.cos(theta)
    y = inner_radius * np.sin(theta)
    pts.append(np.column_stack([x, y, z]))

    # Web (radial surface between bore and rim)
    n_web = n_points // 3
    theta = np.random.uniform(0, 2 * np.pi, n_web)
    r = np.random.uniform(inner_radius, outer_radius, n_web)
    z = np.random.uniform(-height / 2, height / 2, n_web)
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    pts.append(np.column_stack([x, y, z]))

    # Rim (outer edge of disk, thicker)
    n_rim = n_points // 4
    rim_height = height * 1.2
    theta = np.random.uniform(0, 2 * np.pi, n_rim)
    z = np.random.uniform(-rim_height / 2, rim_height / 2, n_rim)
    r = np.random.uniform(outer_radius * 0.95, outer_radius, n_rim)
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    pts.append(np.column_stack([x, y, z]))

    # Front and back faces
    n_face = n_points // 5
    for z_val in [-height / 2, height / 2]:
        theta = np.random.uniform(0, 2 * np.pi, n_face)
        r = np.random.uniform(inner_radius, outer_radius, n_face)
        x = r * np.cos(theta)
        y = r * np.sin(theta)
        z = np.full(n_face, z_val) + np.random.normal(0, height * 0.01, n_face)
        pts.append(np.column_stack([x, y, z]))

    return np.vstack(pts)


def _airfoil_profile(c_frac):
    """NACA-like airfoil thickness distribution (normalized chord 0..1)."""
    t = c_frac
    # Simplified NACA 4-digit thickness
    yt = 5 * 0.12 * (0.2969 * np.sqrt(np.abs(t)) - 0.1260 * t - 0.3516 * t**2 + 0.2843 * t**3 - 0.1015 * t**4)
    return yt


def _make_blade(base_angle, inner_radius, blade_length, chord, max_thickness, n_points=6000):
    """Airfoil-shaped blade with camber, twist, and taper — matching real IBR blades."""
    span_frac = np.random.uniform(0, 1, n_points)
    r = inner_radius + span_frac * blade_length

    taper = 1.0 - 0.35 * span_frac
    twist = np.radians(15.0 * span_frac)  # 15 deg twist root to tip
    local_chord = chord * taper
    local_thickness = max_thickness * taper

    # Chord-wise position (0=LE, 1=TE)
    c_frac = np.random.uniform(0.0, 1.0, n_points)

    # Airfoil thickness profile
    thickness_profile = _airfoil_profile(c_frac)

    # Surface selection: upper or lower
    side = np.random.choice([-1, 1], n_points)
    z_local = side * thickness_profile * local_thickness

    # Chord position in local frame (centered)
    c_pos = (c_frac - 0.5) * local_chord

    # Add camber (slight arc)
    camber = 0.04 * local_chord * np.sin(np.pi * c_frac)
    z_local += camber

    # Add LE/TE edge points (concentrated sampling)
    le_mask = np.random.random(n_points) < 0.08
    te_mask = np.random.random(n_points) < 0.08
    tip_mask = span_frac > 0.97
    root_mask = span_frac < 0.03

    c_pos[le_mask] = -0.5 * local_chord[le_mask]
    c_pos[te_mask] = 0.5 * local_chord[te_mask]
    z_local[le_mask] = 0.0
    z_local[te_mask] = 0.0

    # Apply twist
    x_twisted = c_pos * np.cos(twist) - z_local * np.sin(twist)
    z_twisted = c_pos * np.sin(twist) + z_local * np.cos(twist)

    # Transform to global coords (radial + angular)
    x_local = r
    y_local = x_twisted

    cos_a = np.cos(base_angle)
    sin_a = np.sin(base_angle)
    x = x_local * cos_a - y_local * sin_a
    y = x_local * sin_a + y_local * cos_a
    z = z_twisted

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


def generate_synthetic_data(output_dir="data", n_blades=37, points_per_blade=5000):
    """Generate synthetic CAD reference and scan PLY files.
    
    Default 37 blades matches the real 5th-stage IBR visible in NX
    (37 convergent bodies). Geometry uses airfoil profiles, twist,
    taper, and a thick disk to approximate real IBR proportions.
    """
    os.makedirs(output_dir, exist_ok=True)
    np.random.seed(42)

    # Proportions matched to real F135 compressor IBR
    inner_radius = 0.035    # bore radius
    outer_radius = 0.060    # disk rim where blades attach
    disk_height = 0.018     # thicker disk (real IBRs have substantial web)
    blade_length = 0.032    # shorter blades relative to disk (compressor stage)
    blade_chord = 0.012     # chord width
    blade_thickness = 0.0025  # max airfoil thickness

    disk_points = _make_disk(inner_radius, outer_radius, disk_height,
                             n_points=max(20000, n_blades * 500))

    blade_angles = np.linspace(0, 2 * np.pi, n_blades, endpoint=False)
    # Add slight stagger angle (real blades are not perfectly radial)
    stagger = np.radians(25.0)  # 25 deg stagger angle
    blade_angles += stagger

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
    noise_sigma = 0.000003
    scan_points += np.random.normal(0, noise_sigma, scan_points.shape)

    defect_log = []

    # Introduce defects on specific blades (spread across the rotor)
    defect_blades = {
        3: "nick_le",
        10: "dent",
        18: "clean",
        25: "gouge_te",
        33: "multi_nick",
    }

    for blade_num, start, end, angle in blade_point_ranges:
        if blade_num not in defect_blades:
            continue

        blade_pts = scan_points[start:end]
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        dtype = defect_blades[blade_num]

        if dtype == "nick_le":
            le_center = np.array([
                (outer_radius + blade_length * 0.3) * cos_a - (-blade_chord * 0.45) * sin_a,
                (outer_radius + blade_length * 0.3) * sin_a + (-blade_chord * 0.45) * cos_a,
                0.0,
            ])
            inward = -np.array([cos_a, sin_a, 0.0])
            _add_nick(blade_pts, le_center, radius=0.002, depth=0.00025, direction=inward)
            defect_log.append(f"  Blade {blade_num}: nick on LE (0.25mm deep)")

        elif dtype == "dent":
            mid_radius = outer_radius + blade_length * 0.5
            surf_center = np.array([mid_radius * cos_a, mid_radius * sin_a, 0.001])
            _add_dent(blade_pts, surf_center, radius=0.004, depth=0.00015,
                      direction=np.array([0, 0, -1.0]))
            defect_log.append(f"  Blade {blade_num}: dent on surface (0.15mm deep)")

        elif dtype == "clean":
            defect_log.append(f"  Blade {blade_num}: clean (no defects)")

        elif dtype == "gouge_te":
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
            defect_log.append(f"  Blade {blade_num}: gouge on TE (0.40mm deep)")

        elif dtype == "multi_nick":
            for offset_frac in [0.2, 0.5, 0.8]:
                r_pos = outer_radius + blade_length * offset_frac
                nick_center = np.array([r_pos * cos_a, r_pos * sin_a, 0.0])
                inward = -np.array([cos_a, sin_a, 0.0])
                _add_nick(blade_pts, nick_center, radius=0.0015, depth=0.00018,
                          direction=inward)
            defect_log.append(f"  Blade {blade_num}: 3 nicks (0.18mm deep each)")

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
    blades = int(sys.argv[2]) if len(sys.argv) > 2 else 37
    ppb = int(sys.argv[3]) if len(sys.argv) > 3 else 5000
    generate_synthetic_data(output_dir=out, n_blades=blades, points_per_blade=ppb)
