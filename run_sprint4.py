"""Sprint 4 Demo Runner.

Generates synthetic data (if needed), runs the full v2.0 pipeline
with all Sprint 4 features, and produces analysis summary.
"""

import os
import sys
import json

project_root = os.path.dirname(os.path.abspath(__file__))
os.chdir(project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

from generate_synthetic_data import generate_synthetic_data
from pipeline_v2 import run_pipeline_v2


def main():
    print("=" * 70)
    print("  IBR Defect Extraction System — Sprint 4 Demo")
    print("  Pratt & Whitney F135 | Hitachi Digital Services")
    print("=" * 70)

    scan_path = os.path.join("data", "sample_scan.ply")
    cad_path = os.path.join("data", "cad_reference.ply")

    # Always regenerate to pick up latest geometry improvements
    print("\nGenerating synthetic test data (37-blade IBR)...")
    generate_synthetic_data(output_dir="data", n_blades=37, points_per_blade=5000)
    print("Synthetic data generated.\n")

    results = run_pipeline_v2(
        ply_path=scan_path,
        cad_path=cad_path,
        part_number="4134613",
        config_path=os.path.join("config", "pipeline_config.yaml"),
        enable_ml=True,
        enable_2d=True,
        enable_edge_extraction=True,
        enable_foil_tuning=True,
    )

    print("\n" + "=" * 70)
    print("  SPRINT 4 ANALYSIS SUMMARY")
    print("=" * 70)

    s4 = results.get("sprint4", {})

    edge = s4.get("edge_extraction", {})
    print(f"\n  LE/TE Edge Extraction:")
    print(f"    Leading Edge points:  {edge.get('le_points', 0)}")
    print(f"    Trailing Edge points: {edge.get('te_points', 0)}")
    print(f"    Extraction time:      {edge.get('extraction_time_s', 0)}s")

    tuning = s4.get("foil_tuning", {})
    if tuning:
        bp = tuning.get("best_params", {})
        print(f"\n  Foil Segmentation Calibration:")
        print(f"    Best eps:          {bp.get('eps', 'N/A')}")
        print(f"    Best min_samples:  {bp.get('min_samples', 'N/A')}")
        print(f"    Calibration time:  {tuning.get('calibration_time_s', 0)}s")

    ml = s4.get("ml_metrics", {})
    if ml:
        ens = ml.get("ensemble", {})
        print(f"\n  ML Classification (TLL-12):")
        print(f"    Ensemble accuracy:       {ens.get('accuracy', 0):.4f}")
        print(f"    Ensemble AUC-ROC:        {ens.get('auc_roc', 0):.4f}")
        print(f"    False Negative Rate:     {ens.get('false_negative_rate', 0):.4f}")
        print(f"    Training time:           {ml.get('training_time_s', 0)}s")

        top = ml.get("top_features", [])
        if top:
            print(f"\n    Top-5 Feature Importances:")
            for i, feat in enumerate(top[:5]):
                print(f"      {i+1}. {feat['name']}: {feat['importance']:.4f}")

    views = s4.get("views_2d", {})
    if views:
        print(f"\n  2D Views Generated (TLL-10):")
        for name, path in views.items():
            if isinstance(path, list):
                print(f"    {name}: {len(path)} images")
            else:
                print(f"    {name}: {path}")

    defects = results.get("defects", [])
    if defects:
        print(f"\n  Defect Classification Results:")
        for d in defects:
            did = d.get("defect_id", "?")
            dtype = d.get("classified_type", d.get("defect_type", "unknown"))
            disp = d.get("disposition", "?")
            ml_pred = d.get("ml_prediction", "N/A")
            ml_conf = d.get("ml_confidence", 0)
            depth = d.get("depth_mm", 0)
            length = d.get("length_mm", 0)
            print(f"    {did}: type={dtype}, disposition={disp}, "
                  f"ML={ml_pred} ({ml_conf:.2f}), "
                  f"depth={depth:.3f}mm, length={length:.3f}mm")

    print(f"\n  Reports:")
    print(f"    JSON:   output/4134613_sprint4_analysis.json")
    print(f"    2D:     output/2d_views/")
    print(f"    Models: models/")
    print("=" * 70)


if __name__ == "__main__":
    main()
