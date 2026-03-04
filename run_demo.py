import os
import sys

project_root = os.path.dirname(os.path.abspath(__file__))
os.chdir(project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

from generate_synthetic_data import generate_synthetic_data
from pipeline import run_pipeline

def main():
    print("IBR Defect Extraction System - Demo Run")
    print("=" * 50)

    scan_path = os.path.join("data", "sample_scan.ply")
    cad_path = os.path.join("data", "cad_reference.ply")

    if not os.path.exists(scan_path) or not os.path.exists(cad_path):
        print("\nGenerating synthetic test data...")
        generate_synthetic_data(output_dir="data", n_blades=5, points_per_blade=10000)
        print("Synthetic data generated.\n")

    results = run_pipeline(
        ply_path=scan_path,
        cad_path=cad_path,
        part_number="4134613",
        config_path=os.path.join("config", "pipeline_config.yaml")
    )

    print("\n" + "=" * 50)
    print("DEMO COMPLETE")
    print(f"  Reports generated in: output/")
    print(f"  Overall: {results['overall_disposition']}")
    print("=" * 50)

if __name__ == "__main__":
    main()
