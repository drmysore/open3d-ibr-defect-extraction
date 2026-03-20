# IBR Defect Extraction System

Pratt & Whitney F135 | Hitachi Digital Services — 3D scan vs CAD deviation analysis and defect classification for integrally bladed rotors (IBR).

**Maintainer:** Supreeth Mysore

---

## Table of contents

1. [Quick start](#quick-start)
2. [Branches & recommended checkout](#branches--recommended-checkout)
3. [Running the pipeline](#running-the-pipeline)
4. [Web UI & API](#web-ui--api)
5. [Real data (4119905) & environment variables](#real-data-4119905--environment-variables)
6. [Error handling & exit codes](#error-handling--exit-codes)
7. [Troubleshooting](#troubleshooting)
8. [CI, required checks & auto-merge](#ci-required-checks--auto-merge)
9. [Sprint 4 features](#sprint-4-features)
10. [Further reading](#further-reading)

---

## Quick start

- **Do not copy** `venv/` or `.venv/` between machines — create a new virtual environment on each host.
- **Full step-by-step:** [SETUP_FROM_SCRATCH.md](SETUP_FROM_SCRATCH.md) (Windows, Linux, macOS).
- **Automated setup:** `setup.bat` (Windows) or `./setup.sh` (Linux/macOS), then run the pipeline and server as below.

```bash
# From repository root (after venv + pip install -r requirements.txt)
python run_sprint4.py
python -m uvicorn web.app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/** — use **Gallery** in the top nav for 2D views at **/gallery**.

---

## Branches & recommended checkout

Active integration branch for gallery, STL path overrides, one-click scripts, and docs updates:

| Branch       | Notes                                      |
|-------------|---------------------------------------------|
| **`inferno_j4`** | **Recommended** — gallery, `REAL_STL_PATH`, README/CI |
| `inferno_j3`, `inferno_v2` | Earlier integration points                |
| `master`    | Default branch; align with your team policy |

```bash
git fetch origin
git checkout inferno_j4
git pull
```

---

## Running the pipeline

| Command | Purpose |
|--------|---------|
| `python run_demo.py` | 8-phase demo on `data/sample_scan.ply` + `data/cad_reference.ply` (synthetic fallback if missing). |
| `python run_sprint4.py` | Full v2 pipeline: LE/TE edges, foil tuning, ML, 2D views, Sprint 4 JSON under `output/`. |
| `python src/run_real_data.py` | Real PLY pair for part **4119905** (see [Real data](#real-data-4119905--environment-variables)). |

**One-click (Linux/macOS / Git Bash):**

```bash
export REAL_STL_PATH="/path/to/model.stl"   # optional
bash one_click_real_run.sh
```

**One-click (Windows CMD):**

```cmd
set REAL_STL_PATH=C:\path\to\model.stl
one_click_real_run.bat
```

---

## Web UI & API

Start the app from repo root:

```bash
python -m uvicorn web.app:app --host 127.0.0.1 --port 8000
```

| URL / route | Description |
|-------------|-------------|
| `/` | Dashboard |
| `/viewer3d` | 3D Plotly viewer |
| `/reports` | Reports |
| `/phase-viewer` | Phase viewer |
| `/inferno-viewer` | Inferno 3D |
| `/comparison` | Viewer comparison |
| **`/gallery`** | **2D views gallery** (PNGs under `output/2d_views/`) |
| `GET /api/2d-views` | JSON list of generated 2D view filenames |
| `GET /api/2d-views/{filename}` | Serve a single image |

If `/gallery` is missing, confirm you are on **`inferno_j4`**, restart Uvicorn, and hard-refresh the browser.

---

## Real data (4119905) & environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `REAL_STL_PATH` | `analyze_real_stl.py`, `stl_to_ply_sampled.py`, one-click scripts | Path to STL when defaults are wrong for your machine. |
| `REAL_SCAN_PLY` | `run_real_data.py` | Override scan PLY path. |
| `REAL_CAD_PLY` | `run_real_data.py` | Override CAD PLY path. |

Default PLY locations (after conversion or from repo):

- `data/real_scan_4119905.ply`
- `data/real_cad_4119905.ply`

**Large ZIP (Deflate64):** standard library `zipfile` may fail. Use `pip install zipfile-deflate64` or extract with 7-Zip, then point `--stl-path` / `REAL_STL_PATH` at the extracted STL.

**STL → PLY sampling:**

```bash
python src/stl_to_ply_sampled.py --stl-path "C:\path\to\file.stl"
```

---

## Error handling & exit codes

### Application

- **FastAPI:** routes use `HTTPException` for bad inputs; static/template routes return 404 when assets are missing.
- **CLI:** `src/utils/cli_errors.py` centralizes formatted stderr messages, optional hints, and **`--verbose`** tracebacks for pipeline scripts.

### `run_real_data.py` exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Unexpected error |
| 2 | Missing input files |
| 3 | Pipeline failure |
| 4 | Invalid configuration (reserved) |
| 5 | Missing dependency (`ImportError`) |

**Examples:**

```bash
python src/run_real_data.py
python src/run_real_data.py --scan "D:\data\scan.ply" --cad "D:\data\cad.ply"
python src/run_real_data.py --verbose
```

---

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| **Port 8000 in use** | Stop the other process or: `python -m uvicorn web.app:app --port 8001` |
| **Gallery 404 / missing** | Checkout `inferno_j4`, pull, restart Uvicorn, open `/gallery` directly |
| **PLY not found** | Run `stl_to_ply_sampled.py` with `--stl-path` or set `REAL_SCAN_PLY` / `REAL_CAD_PLY` |
| **0 defects on real run** | If scan and CAD are identical sources, deviation-based defects may be empty; use distinct scan vs nominal CAD for defect studies |
| **ZIP / STL open errors** | Deflate64: `zipfile-deflate64` or 7-Zip; ensure enough disk RAM for multi-GB meshes |
| **Import / Open3D errors** | `pip install -r requirements.txt` in a clean venv; Python 3.9+ |

---

## CI, required checks & auto-merge

The workflow **`.github/workflows/ci.yml`** runs on push/PR (see file for branch list): install dependencies, `compileall`, and import smoke tests.

**You cannot “auto-approve” merges from this repository alone** — GitHub repo/org settings control that. Recommended setup:

1. **GitHub → Settings → Rules → Rulesets** (or branch protection on `master` / `inferno_j4`):
   - Require pull request before merging.
   - Require status checks to pass → add job **`verify`** (workflow **CI**).
2. **Optional — auto-merge:**  
   **Settings → General → Pull Requests → Allow auto-merge**  
   Then on each PR: enable **Auto-merge** so GitHub merges when required checks pass (and reviews, if any, are satisfied).

This gives you **automated verification** and **optional automatic merge** once policies are satisfied — not bypass of review unless your org allows it.

---

## Sprint 4 features

- **TLL-10** — 3D-to-2D conversion: orthographic views, depth maps, defect heatmaps, cross-sections, cylindrical unwrap, defect detail views.
- **TLL-11** — 58-feature defect characterization for ML.
- **TLL-12** — ML ensemble (Random Forest + Gradient Boosting) with cost-aware FN weighting; defect type classification and serviceability prediction.
- **LE/TE extraction** — Leading/trailing edge curve extraction from CAD for edge-distance measurement.
- **Foil segmentation auto-calibration** — DBSCAN parameter tuning for blade segmentation.
- **Pipeline v2** — Single entry point with optional ML, 2D views, and edge extraction; Sprint 4 analysis JSON and 2D views in `output/`.

---

## Further reading

- [SETUP_FROM_SCRATCH.md](SETUP_FROM_SCRATCH.md) — new machine setup, venv paths, Windows vs Unix.
- `src/utils/cli_errors.py` — CLI error helpers and exit codes.
- `one_click_real_run.sh` / `one_click_real_run.bat` — end-to-end real-data path + server.
