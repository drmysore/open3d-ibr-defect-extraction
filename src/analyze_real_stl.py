"""Analyze a large binary STL file without loading it fully into memory.

Reads only the 84-byte header to get triangle count, then samples every
Nth triangle to estimate bounding box, centroid, and dimensions.
"""

import struct
import os
import sys
import numpy as np

STL_PATH = r"C:\Users\mssup\3dpoint\extracted\3DPC Data\models\20230626_77445-4119905_5th_Stage_IBR_Sprayed.stl"

HEADER_SIZE = 80
TRI_COUNT_SIZE = 4
TRIANGLE_SIZE = 50  # 12 (normal) + 36 (3 vertices * 3 floats * 4 bytes) + 2 (attribute)


def read_stl_header(path):
    file_size = os.path.getsize(path)
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
        tri_count_bytes = f.read(TRI_COUNT_SIZE)

    tri_count = struct.unpack("<I", tri_count_bytes)[0]
    expected_size = HEADER_SIZE + TRI_COUNT_SIZE + tri_count * TRIANGLE_SIZE
    header_text = header.decode("ascii", errors="replace").strip("\x00").strip()

    return {
        "header_text": header_text,
        "triangle_count": tri_count,
        "file_size": file_size,
        "expected_size": expected_size,
        "size_match": abs(file_size - expected_size) < 1024,
        "estimated_vertices": tri_count * 3,
    }


def sample_triangles(path, tri_count, sample_every=1000):
    """Read every Nth triangle, collecting 3 vertices per triangle."""
    n_samples = tri_count // sample_every
    vertices = np.empty((n_samples * 3, 3), dtype=np.float32)
    normals = np.empty((n_samples, 3), dtype=np.float32)

    tri_struct = struct.Struct("<12f2x")  # 12 floats (normal + 3 verts) + 2 padding bytes

    idx = 0
    with open(path, "rb") as f:
        f.seek(HEADER_SIZE + TRI_COUNT_SIZE)

        for i in range(n_samples):
            target_tri = i * sample_every
            offset = HEADER_SIZE + TRI_COUNT_SIZE + target_tri * TRIANGLE_SIZE
            f.seek(offset)
            data = f.read(TRIANGLE_SIZE)
            if len(data) < TRIANGLE_SIZE:
                break
            values = tri_struct.unpack(data)
            normals[idx // 3] = values[0:3]
            vertices[idx] = values[3:6]
            vertices[idx + 1] = values[6:9]
            vertices[idx + 2] = values[9:12]
            idx += 3

    vertices = vertices[:idx]
    normals = normals[:idx // 3]
    return vertices, normals


def main():
    print("=" * 60)
    print("  STL HEADER ANALYSIS")
    print(f"  File: {STL_PATH}")
    print("=" * 60)

    info = read_stl_header(STL_PATH)

    print(f"\n  Header text:       {info['header_text'][:60]}")
    print(f"  Triangle count:    {info['triangle_count']:,}")
    print(f"  Estimated verts:   {info['estimated_vertices']:,}")
    print(f"  File size:         {info['file_size']:,} bytes ({info['file_size'] / 1e9:.2f} GB)")
    print(f"  Expected size:     {info['expected_size']:,} bytes")
    print(f"  Size check:        {'PASS' if info['size_match'] else 'FAIL'}")

    tri_count = info["triangle_count"]
    sample_every = 500
    print(f"\n  Sampling every {sample_every:,}th triangle...")

    vertices, normals = sample_triangles(STL_PATH, tri_count, sample_every)
    n_sample_verts = len(vertices)
    n_sample_tris = len(normals)

    print(f"  Sample triangles:  {n_sample_tris:,}")
    print(f"  Sample vertices:   {n_sample_verts:,}")

    bbox_min = vertices.min(axis=0)
    bbox_max = vertices.max(axis=0)
    centroid = vertices.mean(axis=0)
    dimensions = bbox_max - bbox_min

    print(f"\n  Bounding Box (mm):")
    print(f"    X: [{bbox_min[0]:.3f}, {bbox_max[0]:.3f}]  range = {dimensions[0]:.3f}")
    print(f"    Y: [{bbox_min[1]:.3f}, {bbox_max[1]:.3f}]  range = {dimensions[1]:.3f}")
    print(f"    Z: [{bbox_min[2]:.3f}, {bbox_max[2]:.3f}]  range = {dimensions[2]:.3f}")
    print(f"\n  Centroid:  ({centroid[0]:.3f}, {centroid[1]:.3f}, {centroid[2]:.3f})")
    print(f"  Approx dimensions: {dimensions[0]:.1f} x {dimensions[1]:.1f} x {dimensions[2]:.1f} mm")
    print("=" * 60)


if __name__ == "__main__":
    main()
