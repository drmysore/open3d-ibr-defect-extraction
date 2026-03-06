"""TLL-10: 3D-to-2D Conversion Pipeline.

Generates multiple 2D views from 3D point cloud data:
  - Orthographic projections (top, side, front)
  - Depth maps with colormaps
  - Defect heatmap overlays
  - Cross-sectional slice views
  - Cylindrical surface unwrap
  - Annotated exports (PNG, TIFF)
"""

import numpy as np
import os
import time
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import Normalize


class Converter3Dto2D:
    """TLL-10 implementation: project 3D point clouds into 2D image representations."""

    def __init__(self, output_dir: str = "output/2d_views"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_all_views(
        self,
        scan_points: np.ndarray,
        cad_points: Optional[np.ndarray] = None,
        deviations: Optional[np.ndarray] = None,
        defects: Optional[list[dict]] = None,
        resolution: int = 1024,
    ) -> dict:
        """Generate all 2D views and return paths."""
        t0 = time.time()
        results = {}

        for direction in ["top", "side", "front"]:
            path = self._orthographic_projection(
                scan_points, deviations, direction, resolution
            )
            results[f"ortho_{direction}"] = path

        if deviations is not None:
            path = self._depth_map(scan_points, deviations, resolution)
            results["depth_map"] = path

        if defects:
            path = self._defect_heatmap(scan_points, defects, resolution)
            results["defect_heatmap"] = path

        for plane, pos in [("xy", 0.0), ("xz", 0.0), ("yz", 0.0)]:
            path = self._cross_section(
                scan_points, deviations, plane, pos, thickness=2.0, resolution=resolution
            )
            if path:
                results[f"cross_{plane}_{pos}"] = path

        path = self._cylindrical_unwrap(scan_points, deviations, resolution)
        if path:
            results["cylindrical_unwrap"] = path

        if defects:
            path = self._defect_detail_views(scan_points, defects, deviations, resolution // 2)
            results["defect_details"] = path

        elapsed = time.time() - t0
        print(f"  [TLL-10] Generated {len(results)} 2D views in {elapsed:.1f}s")
        return results

    def _orthographic_projection(
        self,
        points: np.ndarray,
        deviations: Optional[np.ndarray],
        direction: str,
        resolution: int,
    ) -> str:
        axis_map = {
            "top": (0, 1, 2),
            "side": (1, 2, 0),
            "front": (0, 2, 1),
        }
        x_idx, y_idx, z_idx = axis_map.get(direction, (0, 1, 2))

        x = points[:, x_idx]
        y = points[:, y_idx]

        fig, ax = plt.subplots(figsize=(10, 10), dpi=100)

        if deviations is not None:
            vmax = max(abs(np.percentile(deviations, 5)), abs(np.percentile(deviations, 95)))
            scatter = ax.scatter(
                x, y, c=deviations, cmap="RdYlGn_r", s=0.5,
                vmin=-vmax, vmax=vmax, alpha=0.8,
            )
            plt.colorbar(scatter, ax=ax, label="Deviation (mm)", shrink=0.8)
        else:
            ax.scatter(x, y, c="steelblue", s=0.3, alpha=0.5)

        axis_labels = ["X", "Y", "Z"]
        ax.set_xlabel(f"{axis_labels[x_idx]} (mm)")
        ax.set_ylabel(f"{axis_labels[y_idx]} (mm)")
        ax.set_title(f"Orthographic Projection — {direction.upper()} view")
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)

        path = os.path.join(self.output_dir, f"ortho_{direction}.png")
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return path

    def _depth_map(
        self,
        points: np.ndarray,
        deviations: np.ndarray,
        resolution: int,
    ) -> str:
        x, y = points[:, 0], points[:, 1]
        x_min, x_max = x.min(), x.max()
        y_min, y_max = y.min(), y.max()

        x_range = x_max - x_min
        y_range = y_max - y_min
        scale = max(x_range, y_range)
        if scale < 1e-6:
            scale = 1.0

        xi = ((x - x_min) / scale * (resolution - 1)).astype(int)
        yi = ((y - y_min) / scale * (resolution - 1)).astype(int)
        xi = np.clip(xi, 0, resolution - 1)
        yi = np.clip(yi, 0, resolution - 1)

        depth_grid = np.full((resolution, resolution), np.nan)
        count_grid = np.zeros((resolution, resolution))

        for k in range(len(points)):
            old = depth_grid[yi[k], xi[k]]
            val = deviations[k]
            if np.isnan(old):
                depth_grid[yi[k], xi[k]] = val
            else:
                depth_grid[yi[k], xi[k]] = (old * count_grid[yi[k], xi[k]] + val) / (count_grid[yi[k], xi[k]] + 1)
            count_grid[yi[k], xi[k]] += 1

        fig, ax = plt.subplots(figsize=(10, 10), dpi=100)
        vmax = np.nanmax(np.abs(depth_grid[~np.isnan(depth_grid)])) if np.any(~np.isnan(depth_grid)) else 1.0
        im = ax.imshow(
            depth_grid, cmap="RdYlGn_r", origin="lower",
            vmin=-vmax, vmax=vmax, interpolation="nearest",
        )
        plt.colorbar(im, ax=ax, label="Deviation (mm)", shrink=0.8)
        ax.set_title("Deviation Depth Map")
        ax.set_xlabel("X pixel")
        ax.set_ylabel("Y pixel")

        path = os.path.join(self.output_dir, "depth_map.png")
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return path

    def _defect_heatmap(
        self,
        points: np.ndarray,
        defects: list[dict],
        resolution: int,
    ) -> str:
        x, y = points[:, 0], points[:, 1]

        fig, ax = plt.subplots(figsize=(12, 10), dpi=100)
        ax.scatter(x, y, c="lightgray", s=0.2, alpha=0.3)

        disp_colors = {
            "SERVICEABLE": "#2ecc71",
            "BLEND": "#f39c12",
            "REPLACE": "#e74c3c",
        }

        for i, defect in enumerate(defects):
            centroid = defect.get("centroid_mm")
            if centroid is None:
                continue

            disp = defect.get("disposition", "SERVICEABLE")
            color = disp_colors.get(disp, "#3498db")

            pts_d = defect.get("points")
            if pts_d is not None and len(pts_d) > 0:
                if not isinstance(pts_d, np.ndarray):
                    pts_d = np.array(pts_d)
                ax.scatter(pts_d[:, 0], pts_d[:, 1], c=color, s=8, alpha=0.7, zorder=5)

            depth = defect.get("depth_mm", 0)
            radius = max(abs(depth) * 20, 1.0)
            circle = plt.Circle(
                (centroid[0], centroid[1]), radius,
                color=color, fill=False, linewidth=2, zorder=6,
            )
            ax.add_patch(circle)

            label = f"D{i + 1}: {defect.get('classified_type', defect.get('defect_type', '?'))}"
            ax.annotate(
                label, (centroid[0], centroid[1]),
                textcoords="offset points", xytext=(10, 10),
                fontsize=8, fontweight="bold", color=color,
                arrowprops=dict(arrowstyle="->", color=color, lw=1),
                zorder=7,
            )

        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor=c, label=l)
            for l, c in disp_colors.items()
        ]
        ax.legend(handles=legend_elements, loc="upper right")
        ax.set_title("Defect Heatmap Overlay")
        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.2)

        path = os.path.join(self.output_dir, "defect_heatmap.png")
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return path

    def _cross_section(
        self,
        points: np.ndarray,
        deviations: Optional[np.ndarray],
        plane: str,
        position: float,
        thickness: float,
        resolution: int,
    ) -> Optional[str]:
        axis_map = {"xy": 2, "xz": 1, "yz": 0}
        plane_axes_map = {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2)}

        perp = axis_map[plane]
        pa = plane_axes_map[plane]

        dist = np.abs(points[:, perp] - position)
        mask = dist <= thickness / 2.0

        if np.sum(mask) < 10:
            return None

        slice_pts = points[mask]

        fig, ax = plt.subplots(figsize=(10, 8), dpi=100)

        if deviations is not None:
            slice_devs = deviations[mask]
            vmax = max(abs(np.percentile(slice_devs, 5)), abs(np.percentile(slice_devs, 95)), 0.01)
            scatter = ax.scatter(
                slice_pts[:, pa[0]], slice_pts[:, pa[1]],
                c=slice_devs, cmap="RdYlGn_r", s=2, vmin=-vmax, vmax=vmax,
            )
            plt.colorbar(scatter, ax=ax, label="Deviation (mm)")
        else:
            ax.scatter(slice_pts[:, pa[0]], slice_pts[:, pa[1]], s=2, c="steelblue")

        axis_labels = ["X", "Y", "Z"]
        ax.set_xlabel(f"{axis_labels[pa[0]]} (mm)")
        ax.set_ylabel(f"{axis_labels[pa[1]]} (mm)")
        ax.set_title(f"Cross-Section: {plane.upper()} plane at {axis_labels[perp]}={position:.1f}mm")
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)

        path = os.path.join(self.output_dir, f"cross_{plane}_{position:.0f}.png")
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return path

    def _cylindrical_unwrap(
        self,
        points: np.ndarray,
        deviations: Optional[np.ndarray],
        resolution: int,
    ) -> Optional[str]:
        x, y, z = points[:, 0], points[:, 1], points[:, 2]
        theta = np.arctan2(y, x)
        height = z

        if np.ptp(theta) < 0.01 or np.ptp(height) < 0.01:
            return None

        fig, ax = plt.subplots(figsize=(14, 6), dpi=100)

        theta_deg = np.degrees(theta)

        if deviations is not None:
            vmax = max(abs(np.percentile(deviations, 5)), abs(np.percentile(deviations, 95)), 0.01)
            scatter = ax.scatter(
                theta_deg, height, c=deviations, cmap="RdYlGn_r",
                s=0.5, vmin=-vmax, vmax=vmax, alpha=0.7,
            )
            plt.colorbar(scatter, ax=ax, label="Deviation (mm)", shrink=0.8)
        else:
            ax.scatter(theta_deg, height, s=0.3, c="steelblue", alpha=0.5)

        ax.set_xlabel("Angular Position (degrees)")
        ax.set_ylabel("Axial Height (mm)")
        ax.set_title("Cylindrical Unwrap — Full Rotor Surface")
        ax.grid(True, alpha=0.3)

        path = os.path.join(self.output_dir, "cylindrical_unwrap.png")
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return path

    def _defect_detail_views(
        self,
        scan_points: np.ndarray,
        defects: list[dict],
        deviations: Optional[np.ndarray],
        resolution: int,
    ) -> list[str]:
        paths = []
        for i, defect in enumerate(defects):
            centroid = defect.get("centroid_mm")
            if centroid is None:
                continue

            margin = max(defect.get("length_mm", 2.0), defect.get("width_mm", 2.0), 2.0) * 3

            dists = np.linalg.norm(scan_points - centroid, axis=1)
            mask = dists < margin

            if np.sum(mask) < 5:
                continue

            local_pts = scan_points[mask]
            local_devs = deviations[mask] if deviations is not None else None

            fig, axes = plt.subplots(1, 3, figsize=(18, 5), dpi=100)

            for ax, (xi, yi, title) in zip(axes, [
                (0, 1, "Top (XY)"),
                (0, 2, "Front (XZ)"),
                (1, 2, "Side (YZ)"),
            ]):
                if local_devs is not None:
                    vmax = max(abs(np.percentile(local_devs, 5)), abs(np.percentile(local_devs, 95)), 0.01)
                    sc = ax.scatter(
                        local_pts[:, xi], local_pts[:, yi],
                        c=local_devs, cmap="RdYlGn_r", s=5, vmin=-vmax, vmax=vmax,
                    )
                else:
                    ax.scatter(local_pts[:, xi], local_pts[:, yi], s=5, c="steelblue")

                ax.set_title(title)
                ax.set_aspect("equal")
                ax.grid(True, alpha=0.3)
                ax.axhline(centroid[yi], color="red", linewidth=0.5, linestyle="--")
                ax.axvline(centroid[xi], color="red", linewidth=0.5, linestyle="--")

            defect_id = defect.get("defect_id", f"D{i + 1}")
            dtype = defect.get("classified_type", defect.get("defect_type", "unknown"))
            disp = defect.get("disposition", "?")
            fig.suptitle(
                f"Defect {defect_id}: {dtype} — {disp} | "
                f"Depth={defect.get('depth_mm', 0):.3f}mm "
                f"L={defect.get('length_mm', 0):.3f}mm W={defect.get('width_mm', 0):.3f}mm",
                fontsize=11, fontweight="bold",
            )

            path = os.path.join(self.output_dir, f"defect_{defect_id}_detail.png")
            fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
            plt.close(fig)
            paths.append(path)

        return paths
