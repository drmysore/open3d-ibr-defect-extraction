"""IBR Defect Extraction Pipeline v2.0 — Sprint 4 Enhanced.

Runs the original 8 phases plus Sprint 4 additions:
  Phase 1:  Data Preparation
  Phase 2:  Registration (RANSAC + ICP)
  Phase 4:  Foil Segmentation (angular DBSCAN) — with auto-calibration
  Phase 3:  Deviation Analysis (KD-tree) — per foil
  Phase 5:  Defect Clustering (spatial DBSCAN)
  Phase 6:  Measurement (PCA/OBB) — with LE/TE curves
  Phase 7:  Zone Classification + Compliance
  Phase 9:  Feature Extraction (58 features) — TLL-11
  Phase 10: ML Classification (ensemble) — TLL-12
  Phase 11: 3D-to-2D Conversion — TLL-10
  Phase 8:  Report Generation (Excel + JSON + 2D views)
"""

import time
import sys
import os
import json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))

from phase1_data_preparation import DataPreparation
from phase2_registration import Registration
from phase3_deviation_analysis import DeviationAnalysis
from phase4_foil_segmentation import FoilSegmentation
from phase5_defect_clustering import DefectClustering
from phase6_measurement import DefectMeasurement
from phase7_zone_classification import ZoneClassification
from phase8_output import OutputGenerator
from phase9_feature_extraction import FeatureExtractor, FEATURE_NAMES
from phase10_ml_classification import DefectClassifier, generate_training_data
from phase11_3d_to_2d import Converter3Dto2D
from phase12_edge_extraction import EdgeExtractor, FoilSegmentationTuner


def run_pipeline_v2(
    ply_path: str,
    cad_path: str,
    part_number: str,
    config_path: str = "config/pipeline_config.yaml",
    enable_ml: bool = True,
    enable_2d: bool = True,
    enable_edge_extraction: bool = True,
    enable_foil_tuning: bool = True,
):
    start_time = time.time()
    print("=" * 70)
    print("  IBR DEFECT EXTRACTION PIPELINE v2.0 — Sprint 4")
    print("  Pratt & Whitney F135 | Hitachi Digital Services")
    print("=" * 70)
    print(f"  Scan:   {ply_path}")
    print(f"  CAD:    {cad_path}")
    print(f"  P/N:    {part_number}")
    print(f"  ML:     {'ON' if enable_ml else 'OFF'}")
    print(f"  2D:     {'ON' if enable_2d else 'OFF'}")
    print(f"  Edge:   {'ON' if enable_edge_extraction else 'OFF'}")
    print("=" * 70)

    # ── Phase 1: Data Preparation ──
    t = time.time()
    print("\n[PHASE 1] Data Preparation")
    phase1 = DataPreparation(config_path)
    scan_pcd = phase1.execute(ply_path)
    scan_points = scan_pcd.points
    scan_normals = scan_pcd.normals
    print(f"  Phase 1 completed in {time.time() - t:.1f}s\n")

    # ── Phase 2: Registration ──
    t = time.time()
    print("[PHASE 2] Registration (RANSAC + ICP)")
    phase2 = Registration(config_path)
    aligned_pcd, cad_pcd, transform, rmse = phase2.execute(scan_pcd, cad_path)
    cad_points = cad_pcd.points
    cad_normals = cad_pcd.normals if hasattr(cad_pcd, 'normals') and len(cad_pcd.normals) > 0 else None
    print(f"  Phase 2 completed in {time.time() - t:.1f}s\n")

    # ── LE/TE Edge Extraction (Sprint 4) ──
    le_curve = None
    te_curve = None
    edge_metadata = {}
    if enable_edge_extraction:
        t = time.time()
        print("[SPRINT 4] LE/TE Edge Extraction")
        edge_extractor = EdgeExtractor()
        cad_pts_mm = cad_points * 1000.0
        cad_nrm = cad_normals if cad_normals is not None else None
        edge_result = edge_extractor.extract(cad_pts_mm, cad_nrm)
        le_curve = edge_result["le_curve"]
        te_curve = edge_result["te_curve"]
        edge_metadata = {
            "le_points": edge_result["le_points_count"],
            "te_points": edge_result["te_points_count"],
            "extraction_time_s": edge_result["extraction_time_s"],
        }
        print(f"  Edge extraction completed in {time.time() - t:.1f}s\n")

    # ── Foil Segmentation Tuning (Sprint 4) ──
    tuning_result = {}
    if enable_foil_tuning:
        t = time.time()
        print("[SPRINT 4] Foil Segmentation Auto-Calibration")
        tuner = FoilSegmentationTuner()
        aligned_pts = aligned_pcd.points * 1000.0
        tuning_result = tuner.auto_calibrate(
            aligned_pts, expected_blade_count=5, n_trials=10
        )
        print(f"  Foil tuning completed in {time.time() - t:.1f}s\n")

    # ── Phase 4: Foil Segmentation ──
    t = time.time()
    print("[PHASE 4] Foil Segmentation")
    phase4 = FoilSegmentation(config_path)
    foils = phase4.execute(aligned_pcd, part_number)
    print(f"  Phase 4 completed in {time.time() - t:.1f}s\n")

    # ── Per-foil processing ──
    phase3 = DeviationAnalysis(config_path)
    phase5 = DefectClustering(config_path)
    phase6 = DefectMeasurement(config_path)
    phase7 = ZoneClassification(config_path)

    all_defects = []
    all_scan_pts_mm = []
    all_deviations = []
    all_foil_labels = []

    for foil_number, foil_pcd in foils:
        print(f"\n--- Processing Foil {foil_number} ---")

        # Phase 3: Deviation analysis
        _, _, foil_defect_pts, foil_defect_devs = phase3.execute_vectorized(foil_pcd, cad_pcd)

        foil_pts_mm = foil_pcd.points * 1000.0
        from scipy.spatial import cKDTree
        cad_tree = cKDTree(cad_points * 1000.0)
        _, nn_idx = cad_tree.query(foil_pts_mm, k=1)
        cad_pts_mm_full = cad_points * 1000.0
        if cad_normals is not None:
            diff_v = foil_pts_mm - cad_pts_mm_full[nn_idx]
            signed_devs = np.sum(diff_v * cad_normals[nn_idx], axis=1)
        else:
            signed_devs = np.linalg.norm(foil_pts_mm - cad_pts_mm_full[nn_idx], axis=1)

        all_scan_pts_mm.append(foil_pts_mm)
        all_deviations.append(signed_devs)
        all_foil_labels.append(np.full(len(foil_pts_mm), foil_number))

        # Phase 5: Cluster defects
        foil_defects = phase5.execute(foil_defect_pts, foil_defect_devs, foil_number)

        # Phase 6: Measure each defect (now with LE/TE curves)
        for defect in foil_defects:
            phase6.execute(defect, le_curve, te_curve)

        # Phase 7: Zone classification + compliance
        blade_geometry = {}
        foil_defects = phase7.execute(foil_defects, blade_geometry)
        all_defects.extend(foil_defects)

    combined_pts = np.vstack(all_scan_pts_mm) if all_scan_pts_mm else np.zeros((0, 3))
    combined_devs = np.concatenate(all_deviations) if all_deviations else np.zeros(0)

    combined_foil_labels = np.concatenate(all_foil_labels) if all_foil_labels else None

    viz_result = {}
    try:
        _src_dir = os.path.dirname(os.path.abspath(__file__))
        if sys.path[0] != _src_dir:
            sys.path.insert(0, _src_dir)
        from visualization.python.generate_phase_figures import generate_and_export_all
        viz_result = generate_and_export_all(
            scan_points_mm=combined_pts,
            deviations_mm=combined_devs,
            foil_labels=combined_foil_labels,
            all_defects=all_defects,
            output_dir=os.path.join("output", "visualizations"),
            part_number=part_number,
            threshold_mm=-0.01,
            expected_blades=len(foils),
        )
        print("  [Viz] Plotly phase figures exported to output/visualizations/")
    except Exception as e:
        print(f"  [Viz] Skip phase figures: {e}")

    # ── Phase 9: Feature Extraction (Sprint 4 — TLL-11) ──
    feature_matrix = None
    if all_defects:
        t = time.time()
        print(f"\n[PHASE 9] Feature Extraction (TLL-11)")
        feature_extractor = FeatureExtractor()
        cad_pts_mm_arr = cad_points * 1000.0
        feature_matrix, feature_names = feature_extractor.extract_all(
            all_defects, cad_pts_mm_arr, cad_normals
        )

        feature_path = os.path.join("output", f"{part_number}_features.npy")
        np.save(feature_path, feature_matrix)
        feature_meta = {
            "feature_names": feature_names,
            "n_defects": len(all_defects),
            "n_features": len(feature_names),
            "feature_status": [d.get("feature_status", "OK") for d in all_defects],
        }
        with open(feature_path.replace(".npy", "_metadata.json"), "w") as f:
            json.dump(feature_meta, f, indent=2)
        print(f"  Phase 9 completed in {time.time() - t:.1f}s\n")

    # ── Phase 10: ML Classification (Sprint 4 — TLL-12) ──
    ml_metrics = {}
    if enable_ml and all_defects and feature_matrix is not None:
        t = time.time()
        print("[PHASE 10] ML Classification (TLL-12)")

        model_dir = os.path.join("models")
        classifier = DefectClassifier(model_dir=model_dir)

        X_train, y_train = generate_training_data(all_defects, augment_factor=50)
        ml_metrics = classifier.train(X_train, y_train, FEATURE_NAMES)

        all_defects = classifier.predict_defect_types(feature_matrix, all_defects)

        print(f"  Phase 10 completed in {time.time() - t:.1f}s\n")

    # ── Phase 11: 3D-to-2D Conversion (Sprint 4 — TLL-10) ──
    view_paths = {}
    if enable_2d and len(combined_pts) > 0:
        t = time.time()
        print("[PHASE 11] 3D-to-2D Conversion (TLL-10)")
        converter = Converter3Dto2D(output_dir="output/2d_views")
        view_paths = converter.generate_all_views(
            scan_points=combined_pts,
            cad_points=cad_points * 1000.0 if cad_points is not None else None,
            deviations=combined_devs,
            defects=all_defects,
            resolution=1024,
        )
        print(f"  Phase 11 completed in {time.time() - t:.1f}s\n")

    # ── Phase 8: Report Generation (enhanced) ──
    t = time.time()
    print(f"\n[PHASE 8] Report Generation (Enhanced)")
    phase8 = OutputGenerator(config_path)
    results = phase8.execute(all_defects, {
        "part_number": part_number,
        "scan_file": ply_path,
        "cad_file": cad_path,
        "alignment_rmse": rmse,
        "foil_count": len(foils),
    })

    # views_2d: defect_details is a list of paths; other keys are single path strings
    def _view_value(v):
        if isinstance(v, list):
            return v
        return str(v)

    results["sprint4"] = {
        "edge_extraction": edge_metadata,
        "foil_tuning": tuning_result,
        "ml_metrics": _sanitize_for_json(ml_metrics),
        "feature_extraction": {
            "n_features": 58,
            "feature_names": FEATURE_NAMES,
        },
        "views_2d": {k: _view_value(v) for k, v in view_paths.items()},
    }

    sprint4_path = os.path.join("output", f"{part_number}_sprint4_analysis.json")
    with open(sprint4_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Sprint 4 analysis saved: {sprint4_path}")

    print(f"  Phase 8 completed in {time.time() - t:.1f}s\n")

    total = time.time() - start_time
    print("=" * 70)
    print("  PIPELINE v2.0 COMPLETE (Sprint 4)")
    print(f"  Total time:          {total:.1f}s")
    print(f"  Foils processed:     {len(foils)}")
    print(f"  Total defects:       {len(all_defects)}")
    print(f"  Features extracted:  {feature_matrix.shape if feature_matrix is not None else 'N/A'}")
    print(f"  ML trained:          {'Yes' if ml_metrics else 'No'}")
    print(f"  2D views generated:  {len(view_paths)}")
    print(f"  LE/TE curves:        LE={edge_metadata.get('le_points', 0)}, TE={edge_metadata.get('te_points', 0)}")
    print(f"  Overall disposition: {results['overall_disposition']}")
    print("=" * 70)
    return results


def _sanitize_for_json(obj):
    """Convert numpy types to JSON-serializable Python types."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    return obj


if __name__ == "__main__":
    ply_path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_scan.ply"
    cad_path = sys.argv[2] if len(sys.argv) > 2 else "data/cad_reference.ply"
    part_number = sys.argv[3] if len(sys.argv) > 3 else "4134613"
    config_path = sys.argv[4] if len(sys.argv) > 4 else "config/pipeline_config.yaml"
    run_pipeline_v2(ply_path, cad_path, part_number, config_path)
