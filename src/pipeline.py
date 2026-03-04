"""IBR Defect Extraction Pipeline — Main Orchestrator.

Runs all 8 phases sequentially:
  Phase 1: Data Preparation
  Phase 2: Registration (RANSAC + ICP)
  Phase 3: Deviation Analysis (KD-tree)
  Phase 4: Foil Segmentation (angular DBSCAN)
  Phase 5: Defect Clustering (spatial DBSCAN)
  Phase 6: Measurement (PCA/OBB)
  Phase 7: Zone Classification + Compliance
  Phase 8: Report Generation (Excel + JSON)
"""

import time
import sys
import os

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


def run_pipeline(ply_path, cad_path, part_number, config_path="config/pipeline_config.yaml"):
    start_time = time.time()
    print("=" * 70)
    print("  IBR DEFECT EXTRACTION PIPELINE v1.0")
    print("  Pratt & Whitney F135 | Hitachi Digital Services")
    print("=" * 70)
    print(f"  Scan:   {ply_path}")
    print(f"  CAD:    {cad_path}")
    print(f"  P/N:    {part_number}")
    print("=" * 70)

    # Phase 1: Data Preparation
    t = time.time()
    print("\n[PHASE 1] Data Preparation")
    phase1 = DataPreparation(config_path)
    scan_pcd = phase1.execute(ply_path)
    print(f"  Phase 1 completed in {time.time() - t:.1f}s\n")

    # Phase 2: Registration
    t = time.time()
    print("[PHASE 2] Registration (RANSAC + ICP)")
    phase2 = Registration(config_path)
    aligned_pcd, cad_pcd, transform, rmse = phase2.execute(scan_pcd, cad_path)
    print(f"  Phase 2 completed in {time.time() - t:.1f}s\n")

    # Phase 4: Foil Segmentation (before per-foil deviation)
    t = time.time()
    print("[PHASE 4] Foil Segmentation")
    phase4 = FoilSegmentation(config_path)
    foils = phase4.execute(aligned_pcd, part_number)
    print(f"  Phase 4 completed in {time.time() - t:.1f}s\n")

    # Per-foil processing: Phases 3, 5, 6, 7
    phase3 = DeviationAnalysis(config_path)
    phase5 = DefectClustering(config_path)
    phase6 = DefectMeasurement(config_path)
    phase7 = ZoneClassification(config_path)

    all_defects = []
    for foil_number, foil_pcd in foils:
        print(f"\n--- Processing Foil {foil_number} ---")

        # Phase 3: Deviation analysis for this foil
        _, _, foil_defect_pts, foil_defect_devs = phase3.execute_vectorized(foil_pcd, cad_pcd)

        # Phase 5: Cluster defects
        foil_defects = phase5.execute(foil_defect_pts, foil_defect_devs, foil_number)

        # Phase 6: Measure each defect
        le_curve = None
        te_curve = None
        for defect in foil_defects:
            phase6.execute(defect, le_curve, te_curve)

        # Phase 7: Zone classification + compliance
        blade_geometry = {}
        foil_defects = phase7.execute(foil_defects, blade_geometry)
        all_defects.extend(foil_defects)

    # Phase 8: Output
    t = time.time()
    print(f"\n[PHASE 8] Report Generation")
    phase8 = OutputGenerator(config_path)
    results = phase8.execute(all_defects, {
        "part_number": part_number,
        "scan_file": ply_path,
        "cad_file": cad_path,
        "alignment_rmse": rmse,
        "foil_count": len(foils),
    })
    print(f"  Phase 8 completed in {time.time() - t:.1f}s\n")

    total = time.time() - start_time
    print("=" * 70)
    print("  PIPELINE COMPLETE")
    print(f"  Total time:          {total:.1f}s")
    print(f"  Foils processed:     {len(foils)}")
    print(f"  Total defects:       {len(all_defects)}")
    print(f"  Overall disposition: {results['overall_disposition']}")
    print("=" * 70)
    return results


if __name__ == "__main__":
    ply_path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_scan.ply"
    cad_path = sys.argv[2] if len(sys.argv) > 2 else "data/cad_reference.ply"
    part_number = sys.argv[3] if len(sys.argv) > 3 else "4134613"
    config_path = sys.argv[4] if len(sys.argv) > 4 else "config/pipeline_config.yaml"
    run_pipeline(ply_path, cad_path, part_number, config_path)
