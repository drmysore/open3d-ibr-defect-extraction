"""Convert a large binary STL to PLY using triangle subsampling + voxel deduplication.

Strategy for 156M-triangle (7.8 GB) file:
  1. Sample every Nth triangle via seek (no full file read)
  2. Collect vertices + normals from sampled triangles
  3. Vectorized voxel deduplication (numpy unique on grid keys)
  4. Target ~500K output points
  5. Save via o3d_compat.write_point_cloud
"""

import struct
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))

from o3d_compat import PointCloud, write_point_cloud

STL_PATH = r"C:\Users\mssup\3dpoint\extracted\3DPC Data\models\20230626_77445-4119905_5th_Stage_IBR_Sprayed.stl"
OUTPUT_SCAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "real_scan_4119905.ply")
OUTPUT_CAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "real_cad_4119905.ply")

HEADER_SIZE = 80
TRI_COUNT_SIZE = 4
TRIANGLE_SIZE = 50
VOXEL_SIZE = 0.0005  # 0.5 mm dedup grid


def read_triangle_count(path):
    with open(path, "rb") as f:
        f.seek(HEADER_SIZE)
        return struct.unpack("<I", f.read(TRI_COUNT_SIZE))[0]


def sample_triangles_chunked(path, tri_count, sample_every):
    """Read every Nth triangle by seeking, return vertices + normals."""
    n_samples = tri_count // sample_every
    print(f"  Will sample {n_samples:,} triangles (every {sample_every:,}th)")

    tri_dtype = np.dtype([
        ('normal', np.float32, (3,)),
        ('v1', np.float32, (3,)),
        ('v2', np.float32, (3,)),
        ('v3', np.float32, (3,)),
        ('attr', np.uint16),
    ])

    data_start = HEADER_SIZE + TRI_COUNT_SIZE
    batch_size = 10_000
    all_verts = []
    all_normals = []

    t0 = time.time()
    with open(path, "rb") as f:
        for batch_start in range(0, n_samples, batch_size):
            batch_end = min(batch_start + batch_size, n_samples)
            batch_n = batch_end - batch_start
            buf = bytearray(batch_n * TRIANGLE_SIZE)

            for j in range(batch_n):
                tri_idx = (batch_start + j) * sample_every
                offset = data_start + tri_idx * TRIANGLE_SIZE
                f.seek(offset)
                chunk = f.read(TRIANGLE_SIZE)
                buf[j * TRIANGLE_SIZE:(j + 1) * TRIANGLE_SIZE] = chunk

            triangles = np.frombuffer(bytes(buf), dtype=tri_dtype)
            verts = np.vstack([triangles['v1'], triangles['v2'], triangles['v3']])
            norms = np.vstack([triangles['normal'], triangles['normal'], triangles['normal']])
            all_verts.append(verts)
            all_normals.append(norms)

            if (batch_start // batch_size) % 5 == 0:
                elapsed = time.time() - t0
                pct = batch_end / n_samples * 100
                print(f"\r  Reading: {pct:5.1f}%  ({batch_end:,}/{n_samples:,} sampled tris, {elapsed:.0f}s)", end="", flush=True)

    print()
    vertices = np.vstack(all_verts).astype(np.float64)
    normals = np.vstack(all_normals).astype(np.float64)
    return vertices, normals


def voxel_deduplicate(vertices, normals, voxel_size):
    """Vectorized voxel deduplication using numpy unique."""
    voxel_keys = np.floor(vertices / voxel_size).astype(np.int64)

    # Pack 3 int64 keys into a single structured array for unique
    key_dtype = np.dtype([('x', np.int64), ('y', np.int64), ('z', np.int64)])
    packed = np.empty(len(voxel_keys), dtype=key_dtype)
    packed['x'] = voxel_keys[:, 0]
    packed['y'] = voxel_keys[:, 1]
    packed['z'] = voxel_keys[:, 2]

    _, unique_idx = np.unique(packed, return_index=True)
    unique_idx.sort()

    return vertices[unique_idx], normals[unique_idx]


def main():
    print("=" * 60)
    print("  STL -> PLY CONVERTER (Sampled + Voxel Dedup)")
    print(f"  Input:  {STL_PATH}")
    print(f"  Voxel:  {VOXEL_SIZE * 1000:.1f} mm")
    print("=" * 60)

    tri_count = read_triangle_count(STL_PATH)
    print(f"\n  Triangle count: {tri_count:,}")

    # Compute sampling rate: target ~700K vertices before dedup -> ~500K after
    # Each sampled tri gives 3 vertices, so need ~233K sampled tris
    # sample_every = tri_count / 233K
    target_pre_dedup = 700_000
    sample_every = max(1, tri_count // (target_pre_dedup // 3))
    n_sampled = tri_count // sample_every
    print(f"  Sample every: {sample_every:,} (yields ~{n_sampled * 3:,} vertices)")

    t_total = time.time()

    vertices, normals = sample_triangles_chunked(STL_PATH, tri_count, sample_every)
    print(f"  Raw sampled vertices: {len(vertices):,}")

    print(f"\n  Voxel deduplication ({VOXEL_SIZE * 1000:.1f} mm grid)...")
    t0 = time.time()
    unique_pts, unique_norms = voxel_deduplicate(vertices, normals, VOXEL_SIZE)
    print(f"  Unique points: {len(unique_pts):,}  ({time.time() - t0:.1f}s)")

    # Normalize normals
    n_len = np.linalg.norm(unique_norms, axis=1, keepdims=True)
    n_len[n_len < 1e-12] = 1.0
    unique_norms = unique_norms / n_len

    pcd = PointCloud(unique_pts, unique_norms)

    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_SCAN)), exist_ok=True)

    print(f"\n  Saving scan PLY: {OUTPUT_SCAN}")
    write_point_cloud(OUTPUT_SCAN, pcd)

    print(f"  Saving CAD PLY:  {OUTPUT_CAD}")
    write_point_cloud(OUTPUT_CAD, pcd)

    scan_size = os.path.getsize(OUTPUT_SCAN)
    cad_size = os.path.getsize(OUTPUT_CAD)
    total_time = time.time() - t_total
    print(f"\n  Scan PLY size: {scan_size:,} bytes ({scan_size / 1e6:.1f} MB)")
    print(f"  CAD PLY size:  {cad_size:,} bytes ({cad_size / 1e6:.1f} MB)")
    print(f"  Total time: {total_time:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
