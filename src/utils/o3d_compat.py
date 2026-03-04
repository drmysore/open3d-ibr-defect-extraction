"""Open3D compatibility layer.

Provides a lightweight point cloud wrapper when Open3D is not available
(e.g. Python 3.14 where Open3D wheels are not yet published).

When Open3D IS available, the real library is used directly.
"""

import numpy as np
from scipy.spatial import cKDTree

try:
    import open3d as o3d
    HAS_OPEN3D = True
except ImportError:
    HAS_OPEN3D = False


class PointCloud:
    """Minimal point cloud container compatible with the pipeline API."""

    def __init__(self, points=None, normals=None):
        self._points = np.empty((0, 3), dtype=np.float64) if points is None else np.asarray(points, dtype=np.float64)
        self._normals = np.empty((0, 3), dtype=np.float64) if normals is None else np.asarray(normals, dtype=np.float64)

    @property
    def points(self):
        return self._points

    @points.setter
    def points(self, val):
        self._points = np.asarray(val, dtype=np.float64)

    @property
    def normals(self):
        return self._normals

    @normals.setter
    def normals(self, val):
        self._normals = np.asarray(val, dtype=np.float64)

    def has_normals(self):
        return self._normals is not None and len(self._normals) == len(self._points)

    def is_empty(self):
        return len(self._points) == 0

    def estimate_normals(self, k=30):
        """Estimate normals using PCA of local neighborhoods."""
        if len(self._points) == 0:
            return
        tree = cKDTree(self._points)
        k_use = min(k, len(self._points))
        _, idx = tree.query(self._points, k=k_use, workers=-1)
        normals = np.zeros_like(self._points)
        for i in range(len(self._points)):
            neighbors = self._points[idx[i]]
            centered = neighbors - neighbors.mean(axis=0)
            cov = centered.T @ centered
            eigvals, eigvecs = np.linalg.eigh(cov)
            normals[i] = eigvecs[:, 0]
        norms = np.linalg.norm(normals, axis=1, keepdims=True)
        norms[norms < 1e-12] = 1.0
        self._normals = normals / norms

    def voxel_down_sample(self, voxel_size):
        """Grid-based voxel downsampling."""
        if len(self._points) == 0:
            return PointCloud()
        indices = np.floor(self._points / voxel_size).astype(np.int64)
        _, unique_idx = np.unique(indices, axis=0, return_index=True)
        new_pts = self._points[unique_idx]
        new_normals = self._normals[unique_idx] if self.has_normals() else None
        return PointCloud(new_pts, new_normals)

    def remove_statistical_outlier(self, nb_neighbors=20, std_ratio=2.0):
        """Statistical outlier removal based on mean neighbor distance."""
        if len(self._points) < nb_neighbors:
            return self, np.arange(len(self._points))
        tree = cKDTree(self._points)
        k = min(nb_neighbors + 1, len(self._points))
        dists, _ = tree.query(self._points, k=k, workers=-1)
        mean_dists = np.mean(dists[:, 1:], axis=1)
        global_mean = np.mean(mean_dists)
        global_std = np.std(mean_dists)
        threshold = global_mean + std_ratio * global_std
        mask = mean_dists < threshold
        inlier_idx = np.where(mask)[0]
        new_pts = self._points[mask]
        new_normals = self._normals[mask] if self.has_normals() else None
        return PointCloud(new_pts, new_normals), inlier_idx

    def transform(self, T):
        """Apply 4x4 transformation matrix."""
        pts_h = np.hstack([self._points, np.ones((len(self._points), 1))])
        transformed = (T @ pts_h.T).T[:, :3]
        new_normals = None
        if self.has_normals():
            R = T[:3, :3]
            new_normals = (R @ self._normals.T).T
        return PointCloud(transformed, new_normals)

    def select_by_index(self, indices):
        """Select a subset of points by indices."""
        new_pts = self._points[indices]
        new_normals = self._normals[indices] if self.has_normals() else None
        return PointCloud(new_pts, new_normals)

    def __len__(self):
        return len(self._points)


def read_point_cloud(path):
    """Read a PLY file. Uses Open3D if available, else a numpy-based PLY reader."""
    if HAS_OPEN3D:
        pcd_o3d = o3d.io.read_point_cloud(path)
        return _from_o3d(pcd_o3d)
    return _read_ply_numpy(path)


def write_point_cloud(path, pcd):
    """Write a PLY file."""
    if HAS_OPEN3D:
        pcd_o3d = _to_o3d(pcd)
        o3d.io.write_point_cloud(path, pcd_o3d)
        return
    _write_ply_numpy(path, pcd)


def _read_ply_numpy(path):
    """Parse a PLY file using only numpy."""
    with open(path, "rb") as f:
        header_lines = []
        while True:
            line = f.readline().decode("ascii", errors="replace").strip()
            header_lines.append(line)
            if line == "end_header":
                break

        n_vertices = 0
        properties = []
        for line in header_lines:
            if line.startswith("element vertex"):
                n_vertices = int(line.split()[-1])
            elif line.startswith("property"):
                parts = line.split()
                properties.append((parts[1], parts[2]))

        is_binary = any("binary" in h for h in header_lines)

        if is_binary:
            dtype_map = {"float": np.float32, "double": np.float64,
                         "uchar": np.uint8, "int": np.int32}
            dt = np.dtype([(name, dtype_map.get(t, np.float32)) for t, name in properties])
            raw = np.frombuffer(f.read(n_vertices * dt.itemsize), dtype=dt)
        else:
            raw_data = np.loadtxt(f, max_rows=n_vertices)
            if raw_data.ndim == 1:
                raw_data = raw_data.reshape(1, -1)
            prop_names = [name for _, name in properties]
            raw = {prop_names[i]: raw_data[:, i] for i in range(min(len(prop_names), raw_data.shape[1]))}

    prop_names = [name for _, name in properties]
    has_x = "x" in (prop_names if isinstance(raw, dict) else raw.dtype.names)

    if has_x:
        if isinstance(raw, dict):
            points = np.column_stack([raw["x"], raw["y"], raw["z"]])
        else:
            points = np.column_stack([raw["x"], raw["y"], raw["z"]])
    else:
        points = np.zeros((n_vertices, 3))

    normals = None
    has_nx = "nx" in (prop_names if isinstance(raw, dict) else (raw.dtype.names or []))
    if has_nx:
        if isinstance(raw, dict):
            normals = np.column_stack([raw["nx"], raw["ny"], raw["nz"]])
        else:
            normals = np.column_stack([raw["nx"], raw["ny"], raw["nz"]])

    return PointCloud(points.astype(np.float64), normals.astype(np.float64) if normals is not None else None)


def _write_ply_numpy(path, pcd):
    """Write a PLY file in ASCII format."""
    pts = pcd.points
    has_n = pcd.has_normals()
    with open(path, "w") as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {len(pts)}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        if has_n:
            f.write("property float nx\nproperty float ny\nproperty float nz\n")
        f.write("end_header\n")
        normals = pcd.normals if has_n else None
        for i in range(len(pts)):
            line = f"{pts[i, 0]:.8f} {pts[i, 1]:.8f} {pts[i, 2]:.8f}"
            if has_n:
                line += f" {normals[i, 0]:.8f} {normals[i, 1]:.8f} {normals[i, 2]:.8f}"
            f.write(line + "\n")


def _from_o3d(pcd_o3d):
    """Convert Open3D PointCloud to our PointCloud."""
    pts = np.asarray(pcd_o3d.points)
    normals = np.asarray(pcd_o3d.normals) if pcd_o3d.has_normals() else None
    return PointCloud(pts, normals)


def _to_o3d(pcd):
    """Convert our PointCloud to Open3D PointCloud."""
    pcd_o3d = o3d.geometry.PointCloud()
    pcd_o3d.points = o3d.utility.Vector3dVector(pcd.points)
    if pcd.has_normals():
        pcd_o3d.normals = o3d.utility.Vector3dVector(pcd.normals)
    return pcd_o3d


def icp_registration(source, target, max_dist=0.001, init_transform=None, max_iter=200):
    """Simple ICP implementation using scipy KD-tree."""
    src_pts = source.points.copy()
    tgt_pts = target.points.copy()
    T = init_transform if init_transform is not None else np.eye(4)

    for iteration in range(max_iter):
        pts_h = np.hstack([src_pts, np.ones((len(src_pts), 1))])
        transformed = (T @ pts_h.T).T[:, :3]

        tree = cKDTree(tgt_pts)
        dists, indices = tree.query(transformed, k=1, workers=-1)

        mask = dists < max_dist
        if np.sum(mask) < 3:
            break

        src_matched = transformed[mask]
        tgt_matched = tgt_pts[indices[mask]]

        src_centroid = src_matched.mean(axis=0)
        tgt_centroid = tgt_matched.mean(axis=0)

        H = (src_matched - src_centroid).T @ (tgt_matched - tgt_centroid)
        U, S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1, :] *= -1
            R = Vt.T @ U.T

        t = tgt_centroid - R @ src_centroid

        T_step = np.eye(4)
        T_step[:3, :3] = R
        T_step[:3, 3] = t
        T = T_step @ T

        rmse = np.sqrt(np.mean(dists[mask] ** 2))
        if rmse < 1e-8:
            break

    pts_h = np.hstack([src_pts, np.ones((len(src_pts), 1))])
    final_pts = (T @ pts_h.T).T[:, :3]
    tree = cKDTree(tgt_pts)
    dists, _ = tree.query(final_pts, k=1, workers=-1)
    inlier_mask = dists < max_dist
    fitness = np.mean(inlier_mask)
    inlier_rmse = np.sqrt(np.mean(dists[inlier_mask] ** 2)) if np.any(inlier_mask) else float("inf")

    return T, fitness, inlier_rmse
