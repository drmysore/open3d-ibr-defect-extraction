import numpy as np

MM_PER_INCH = 25.4


def mm_to_inches(mm):
    """Convert millimeters to inches."""
    return np.asarray(mm) / MM_PER_INCH


def inches_to_mm(inches):
    """Convert inches to millimeters."""
    return np.asarray(inches) * MM_PER_INCH


def cartesian_to_cylindrical(points):
    """Convert Nx3 Cartesian (x, y, z) to cylindrical (r, theta, z).

    Returns (r, theta_radians, z) as separate arrays.
    """
    pts = np.asarray(points)
    if pts.ndim == 1:
        pts = pts.reshape(1, -1)
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    r = np.sqrt(x ** 2 + y ** 2)
    theta = np.arctan2(y, x)
    return r, theta, z


def cylindrical_to_cartesian(r, theta, z):
    """Convert cylindrical (r, theta_radians, z) to Nx3 Cartesian (x, y, z)."""
    r = np.asarray(r)
    theta = np.asarray(theta)
    z = np.asarray(z)
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    return np.column_stack([x, y, z])


def grid_to_metric(row, col, span_mm, chord_mm, grid_rows=64, grid_cols=128):
    """Convert grid indices (row, col) to metric coordinates (x_mm, y_mm).

    row maps to spanwise position (0..grid_rows-1 -> 0..span_mm)
    col maps to chordwise position (0..grid_cols-1 -> 0..chord_mm)
    """
    row = np.asarray(row, dtype=float)
    col = np.asarray(col, dtype=float)
    x_mm = (col / max(grid_cols - 1, 1)) * chord_mm
    y_mm = (row / max(grid_rows - 1, 1)) * span_mm
    return x_mm, y_mm


def metric_to_grid(x_mm, y_mm, span_mm, chord_mm, grid_rows=64, grid_cols=128):
    """Convert metric coordinates (x_mm, y_mm) to grid indices (row, col).

    Inverse of grid_to_metric. Returns floating-point row/col
    (caller can round/clip as needed).
    """
    x_mm = np.asarray(x_mm, dtype=float)
    y_mm = np.asarray(y_mm, dtype=float)
    col = (x_mm / max(chord_mm, 1e-12)) * (grid_cols - 1)
    row = (y_mm / max(span_mm, 1e-12)) * (grid_rows - 1)
    return row, col
