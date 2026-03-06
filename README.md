# IBR Defect Extraction System

Pratt & Whitney F135 | Hitachi Digital Services — 3D scan vs CAD deviation analysis and defect classification for integrally bladed rotors (IBR).

## Running the pipeline

- **Demo (8-phase pipeline):**  
  `python run_demo.py`  
  Uses `data/sample_scan.ply` and `data/cad_reference.ply` (generates synthetic data if missing).

- **Sprint 4 (full v2 pipeline):**  
  `python run_sprint4.py`  
  Runs the enhanced pipeline with LE/TE edge extraction, foil tuning, feature extraction, ML classification, and 2D view generation. Outputs: `output/{part}_sprint4_analysis.json`, `output/2d_views/*.png`, `models/`.

## Sprint 4 features

- **TLL-10** — 3D-to-2D conversion: orthographic views, depth maps, defect heatmaps, cross-sections, cylindrical unwrap, defect detail views.
- **TLL-11** — 58-feature defect characterization for ML.
- **TLL-12** — ML ensemble (Random Forest + Gradient Boosting) with cost-aware FN weighting; defect type classification and serviceability prediction.
- **LE/TE extraction** — Leading/trailing edge curve extraction from CAD for edge-distance measurement.
- **Foil segmentation auto-calibration** — DBSCAN parameter tuning for blade segmentation.
- **Pipeline v2** — Single entry point with optional ML, 2D views, and edge extraction; Sprint 4 analysis JSON and 2D views in `output/`.
