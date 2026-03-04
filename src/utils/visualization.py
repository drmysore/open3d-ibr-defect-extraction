import numpy as np

try:
    import open3d as o3d
    HAS_OPEN3D = True
except ImportError:
    HAS_OPEN3D = False

try:
    import matplotlib.pyplot as plt
    from matplotlib import cm
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def _require_open3d():
    if not HAS_OPEN3D:
        raise ImportError("open3d is required for visualization")


def visualize_point_cloud(pcd, title="Point Cloud"):
    """Display an Open3D point cloud in an interactive viewer."""
    _require_open3d()
    if not pcd.has_colors():
        pcd.paint_uniform_color([0.6, 0.6, 0.6])
    o3d.visualization.draw_geometries([pcd], window_name=title, width=1280, height=720)


def visualize_deviations(pcd, deviations, title="Deviations"):
    """Color points by signed deviation: blue=negative/defect, green=nominal, red=positive/buildup."""
    _require_open3d()

    dev = np.asarray(deviations).flatten()
    if len(dev) != len(pcd.points):
        raise ValueError(
            f"Deviation count ({len(dev)}) != point count ({len(pcd.points)})"
        )

    abs_max = max(np.abs(dev).max(), 1e-12)
    normalized = dev / abs_max  # range [-1, 1]

    colors = np.zeros((len(dev), 3), dtype=np.float64)

    neg_mask = normalized < 0
    pos_mask = normalized > 0
    zero_mask = ~neg_mask & ~pos_mask

    # Negative (defects): green -> blue as magnitude increases
    t = np.abs(normalized[neg_mask])
    colors[neg_mask, 0] = 0.0
    colors[neg_mask, 1] = 1.0 - t
    colors[neg_mask, 2] = t

    # Positive (buildup): green -> red as magnitude increases
    t = normalized[pos_mask]
    colors[pos_mask, 0] = t
    colors[pos_mask, 1] = 1.0 - t
    colors[pos_mask, 2] = 0.0

    colors[zero_mask] = [0.0, 1.0, 0.0]

    vis_pcd = o3d.geometry.PointCloud(pcd)
    vis_pcd.colors = o3d.utility.Vector3dVector(colors)

    o3d.visualization.draw_geometries(
        [vis_pcd], window_name=title, width=1280, height=720
    )


def visualize_defects(pcd, defect_list, title="Defects"):
    """Highlight defect clusters in distinct colors over a gray base cloud."""
    _require_open3d()

    vis_pcd = o3d.geometry.PointCloud(pcd)
    vis_pcd.paint_uniform_color([0.7, 0.7, 0.7])

    base_colors = np.asarray(vis_pcd.colors)
    palette = [
        [1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.5, 0.0],
        [0.5, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 0.0, 0.5],
        [1.0, 1.0, 0.0], [0.0, 0.5, 0.0], [0.5, 0.5, 0.0],
        [0.0, 0.5, 1.0],
    ]

    geometries = [vis_pcd]
    for i, defect in enumerate(defect_list):
        pts = defect.get("points")
        if pts is None or len(pts) == 0:
            continue

        color = palette[i % len(palette)]
        defect_pcd = o3d.geometry.PointCloud()
        defect_pcd.points = o3d.utility.Vector3dVector(np.asarray(pts))
        defect_pcd.paint_uniform_color(color)
        geometries.append(defect_pcd)

    o3d.visualization.draw_geometries(
        geometries, window_name=title, width=1280, height=720
    )


def save_visualization_screenshot(pcd, path, deviations=None):
    """Save a point cloud visualization to an image file.

    Attempts Open3D offscreen rendering first, falls back to matplotlib
    if the offscreen renderer is unavailable.
    """
    if deviations is not None and HAS_OPEN3D:
        vis_pcd = o3d.geometry.PointCloud(pcd)
        dev = np.asarray(deviations).flatten()
        abs_max = max(np.abs(dev).max(), 1e-12)
        normalized = (dev / abs_max + 1.0) / 2.0
        if HAS_MPL:
            cmap = cm.get_cmap("coolwarm")
            colors = cmap(normalized)[:, :3]
        else:
            colors = np.column_stack([normalized, 1.0 - np.abs(dev / abs_max), 1.0 - normalized])
        vis_pcd.colors = o3d.utility.Vector3dVector(colors)
    elif HAS_OPEN3D:
        vis_pcd = o3d.geometry.PointCloud(pcd)
        if not vis_pcd.has_colors():
            vis_pcd.paint_uniform_color([0.6, 0.6, 0.6])
    else:
        vis_pcd = None

    if HAS_OPEN3D:
        try:
            vis = o3d.visualization.Visualizer()
            vis.create_window(visible=False, width=1280, height=720)
            vis.add_geometry(vis_pcd)
            vis.update_geometry(vis_pcd)
            vis.poll_events()
            vis.update_renderer()
            vis.capture_screen_image(path, do_render=True)
            vis.destroy_window()
            print(f"  Saved screenshot: {path}")
            return
        except Exception:
            pass

    if HAS_MPL and vis_pcd is not None:
        pts = np.asarray(vis_pcd.points)
        colors_arr = np.asarray(vis_pcd.colors) if vis_pcd.has_colors() else None

        fig = plt.figure(figsize=(12, 8))
        ax = fig.add_subplot(111, projection="3d")
        ax.scatter(
            pts[:, 0], pts[:, 1], pts[:, 2],
            c=colors_arr, s=0.5, alpha=0.6,
        )
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved matplotlib screenshot: {path}")
    else:
        print(f"  WARNING: Cannot save screenshot — install open3d or matplotlib")
