# Run IBR Defect Extraction on a New Machine (From Scratch)

Use this guide to set up and run the project on another machine **without** copying any existing virtual environment. Always create a **new** venv on the new machine.

---

## 1. What You Need (Source Files)

- **Get the project** — Clone the repo or copy the **entire project folder** to the new machine.
- **Do NOT copy** from the old machine:
  - `venv/` or `.venv/` (virtual environment)
  - `__pycache__/`, `*.pyc`
  - `models/*.joblib` (trained model binaries — optional; pipeline will train new ones if missing)
- **You can copy** (optional, to avoid re-running pipeline immediately):
  - `data/*.ply` (sample scan and CAD)
  - `output/` (existing reports and 2D views)
  - `config/` (all config files)

**Minimum to run from scratch:** the full repo (or project folder) **without** `venv/` or `.venv/`.

---

## 2. Prerequisites

- **Python 3.9 or 3.10, 3.11, 3.12** (3.14 not recommended; Open3D may be unavailable; the project uses a compat layer).
- **Git** (optional, only if you clone).
- **~500 MB** disk for dependencies and data.

---

## 3. One-Time Setup

### Windows (PowerShell or CMD)

```batch
cd path\to\open3d_v1
setup.bat
```

This will:
- Check Python 3.9+
- Create `venv\`
- Activate it and install all packages from `requirements.txt`
- Create `output\`, `output\2d_views\`, `data\`

### Linux / macOS (Bash)

```bash
cd /path/to/open3d_v1
chmod +x setup.sh
./setup.sh
```

Then activate the environment (if your shell is not already using it):

```bash
source venv/bin/activate
```

---

## 4. Using `.venv` Instead of `venv`

If you prefer a `.venv` folder (e.g. to match your IDE or team convention):

**Windows:**

```batch
cd path\to\open3d_v1
python -m venv .venv
.venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
mkdir output output\2d_views data 2>nul
```

**Linux / macOS:**

```bash
cd /path/to/open3d_v1
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p output output/2d_views data
```

Then use the same run commands below (with your activated `.venv`).

---

## 5. Run the Pipeline

Make sure the virtual environment is **activated**:

- **Windows:** `venv\Scripts\activate.bat` (or `.venv\Scripts\activate.bat` if you use `.venv`).
- **Linux/macOS:** `source venv/bin/activate` (or `source .venv/bin/activate`).

| Task | Command |
|------|--------|
| **v1 demo (8-phase)** | `python run_demo.py` |
| **Sprint 4 full pipeline** | `python run_sprint4.py` |
| **Web dashboard** | `python web/app.py` then open http://localhost:8000 |

- `run_demo.py` and `run_sprint4.py` will **generate synthetic data** in `data/` if `data/sample_scan.ply` or `data/cad_reference.ply` are missing.
- Sprint 4 writes to `output/`, `output/2d_views/`, and `models/` (ML models and metrics).

---

## 6. Quick Reference: Activate and Run

**Windows (venv):**

```batch
cd path\to\open3d_v1
venv\Scripts\activate.bat
python run_sprint4.py
python web\app.py
```

**Windows (.venv):**

```batch
cd path\to\open3d_v1
.venv\Scripts\activate.bat
python run_sprint4.py
python web\app.py
```

**Linux/macOS (venv):**

```bash
cd /path/to/open3d_v1
source venv/bin/activate
python run_sprint4.py
python web/app.py
```

**Linux/macOS (.venv):**

```bash
cd /path/to/open3d_v1
source .venv/bin/activate
python run_sprint4.py
python web/app.py
```

---

## 7. Files Summary

| Purpose | Location |
|--------|----------|
| Dependencies list | `requirements.txt` |
| Setup (Windows) | `setup.bat` |
| Setup (Linux/macOS) | `setup.sh` |
| v1 pipeline | `run_demo.py` → `src/pipeline.py` |
| Sprint 4 pipeline | `run_sprint4.py` → `src/pipeline_v2.py` |
| Web app | `web/app.py` |
| Config | `config/pipeline_config.yaml`, `config/reparable_limits.json`, etc. |
| Data (created if missing) | `data/sample_scan.ply`, `data/cad_reference.ply` |
| Outputs | `output/*.json`, `output/*.xlsx`, `output/2d_views/*.png`, `models/` |

You do **not** need to copy or “source” anything from an old `.venv` or `venv` — install everything on the new machine with the steps above.
