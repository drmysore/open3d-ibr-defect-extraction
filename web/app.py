"""FastAPI web application for IBR Defect Extraction System.

Interactive dashboard with 3D point cloud visualization,
defect reports, zone analysis, and pipeline execution.
"""

import os
import sys
import json
import glob
import time
import threading
import numpy as np
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "utils"))

app = FastAPI(title="IBR Defect Extraction System", version="1.0.0")

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

pipeline_status = {"running": False, "progress": "", "last_result": None}


def _render(request: Request, template_name: str, context: dict = None):
    """Starlette TemplateResponse compat wrapper — works with both old and new API."""
    ctx = context or {}
    try:
        return templates.TemplateResponse(request=request, name=template_name, context=ctx)
    except TypeError:
        ctx["request"] = request
        return templates.TemplateResponse(template_name, ctx)


def _load_latest_report():
    """Load the richest report by scoring defect count + ML + sprint4 data."""
    output_dir = PROJECT_ROOT / "output"
    best, best_score = None, -1
    for f in output_dir.glob("*.json"):
        if f.name.endswith("_features_metadata.json"):
            continue
        if f.parent.name == "visualizations":
            continue
        try:
            with open(f) as fh:
                data = json.load(fh)
            n = len(data.get("defects", []))
            has_ml = any(d.get("classified_type") for d in data.get("defects", [])[:3])
            score = n * 10 + (5 if has_ml else 0) + (3 if data.get("sprint4") else 0)
            if score > best_score:
                best, best_score = data, score
        except Exception:
            continue
    return best


def _load_latest_sprint4_report():
    """Return latest report that has sprint4 key (e.g. {part}_sprint4_analysis.json)."""
    output_dir = PROJECT_ROOT / "output"
    sprint4_files = sorted(
        output_dir.glob("*_sprint4_analysis.json"),
        key=os.path.getmtime,
        reverse=True,
    )
    if sprint4_files:
        with open(sprint4_files[0]) as f:
            return json.load(f)
    # Fallback: latest report with "sprint4" key
    for f in sorted(output_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
        with open(f) as fh:
            data = json.load(fh)
        if data.get("sprint4"):
            return data
    return None


def _load_ply_points(ply_path, max_points=50000):
    """Load points from PLY file using the compat layer."""
    from o3d_compat import read_point_cloud
    pcd = read_point_cloud(str(ply_path))
    pts = pcd.points
    if len(pts) > max_points:
        idx = np.random.choice(len(pts), max_points, replace=False)
        pts = pts[idx]
    return (pts * 1000.0).tolist()


def _compute_deviations_for_viz(scan_path, cad_path, max_points=30000):
    """Compute deviations between scan and CAD for visualization."""
    from o3d_compat import read_point_cloud
    from scipy.spatial import cKDTree

    scan_pcd = read_point_cloud(str(scan_path))
    cad_pcd = read_point_cloud(str(cad_path))

    scan_pts = scan_pcd.points * 1000.0
    cad_pts = cad_pcd.points * 1000.0

    if len(scan_pts) > max_points:
        idx = np.random.choice(len(scan_pts), max_points, replace=False)
        scan_pts = scan_pts[idx]

    cad_normals = cad_pcd.normals
    if len(cad_normals) == 0:
        cad_pcd.estimate_normals(k=30)
        cad_normals = cad_pcd.normals

    tree = cKDTree(cad_pts)
    _, indices = tree.query(scan_pts, k=1, workers=-1)
    diff = scan_pts - cad_pts[indices]
    signed_dists = np.sum(diff * cad_normals[indices], axis=1)

    return scan_pts.tolist(), signed_dists.tolist()


# ----- HTML Pages -----

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    report = _load_latest_report()
    return _render(request, "dashboard.html", {
        "report": report,
        "has_report": report is not None,
    })


@app.get("/viewer3d", response_class=HTMLResponse)
async def viewer_3d(request: Request):
    return _render(request, "viewer3d.html")


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    output_dir = PROJECT_ROOT / "output"
    reports = []
    for f in sorted(output_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
        with open(f) as fh:
            data = json.load(fh)
        xlsx_path = f.with_suffix(".xlsx")
        reports.append({
            "filename": f.name,
            "xlsx_exists": xlsx_path.exists(),
            "xlsx_name": xlsx_path.name if xlsx_path.exists() else None,
            "timestamp": data.get("timestamp", ""),
            "part_number": data.get("part_number", ""),
            "disposition": data.get("overall_disposition", ""),
            "total_defects": data.get("total_defects", 0),
        })
    return _render(request, "reports.html", {"reports": reports})


@app.get("/inferno-viewer", response_class=HTMLResponse)
async def inferno_viewer(request: Request):
    return _render(request, "inferno_viewer.html")


@app.get("/comparison", response_class=HTMLResponse)
async def comparison_page(request: Request):
    return _render(request, "comparison.html")


@app.get("/gallery", response_class=HTMLResponse)
async def gallery_page(request: Request):
    """Visual gallery for generated 2D PNG views."""
    return _render(request, "image_gallery.html")


@app.get("/maintenance", response_class=HTMLResponse)
async def maintenance_page(request: Request):
    """Maintenance technician view with foil-by-foil inspection and defect-type toggles."""
    return _render(request, "maintenance.html")


@app.get("/quality-audits", response_class=HTMLResponse)
async def quality_audits_page(request: Request):
    return _render(request, "quality_audits.html")


@app.get("/defect-library", response_class=HTMLResponse)
async def defect_library_page(request: Request):
    return _render(request, "defect_library.html")


# ----- API Endpoints -----

@app.get("/api/report/latest")
async def api_latest_report():
    report = _load_latest_report()
    if not report:
        raise HTTPException(404, "No reports found")
    return report


@app.get("/api/reports")
async def api_list_reports():
    output_dir = PROJECT_ROOT / "output"
    reports = []
    for f in sorted(output_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
        with open(f) as fh:
            data = json.load(fh)
        reports.append({
            "filename": f.name,
            "part_number": data.get("part_number"),
            "disposition": data.get("overall_disposition"),
            "total_defects": data.get("total_defects"),
            "timestamp": data.get("timestamp"),
        })
    return reports


@app.get("/api/report/{filename}")
async def api_get_report(filename: str):
    filepath = PROJECT_ROOT / "output" / filename
    if not filepath.exists():
        raise HTTPException(404, f"Report not found: {filename}")
    with open(filepath) as f:
        return json.load(f)


@app.get("/api/download/{filename}")
async def api_download_file(filename: str):
    filepath = PROJECT_ROOT / "output" / filename
    if not filepath.exists():
        raise HTTPException(404, f"File not found: {filename}")
    return FileResponse(str(filepath), filename=filename)


@app.get("/api/pointcloud/scan")
async def api_scan_points():
    scan_path = PROJECT_ROOT / "data" / "sample_scan.ply"
    if not scan_path.exists():
        raise HTTPException(404, "Scan file not found")
    points = _load_ply_points(scan_path, max_points=40000)
    return {"points": points, "count": len(points)}


@app.get("/api/pointcloud/cad")
async def api_cad_points():
    cad_path = PROJECT_ROOT / "data" / "cad_reference.ply"
    if not cad_path.exists():
        raise HTTPException(404, "CAD file not found")
    points = _load_ply_points(cad_path, max_points=40000)
    return {"points": points, "count": len(points)}


@app.get("/api/pointcloud/deviations")
async def api_deviations():
    scan_path = PROJECT_ROOT / "data" / "sample_scan.ply"
    cad_path = PROJECT_ROOT / "data" / "cad_reference.ply"
    if not scan_path.exists() or not cad_path.exists():
        raise HTTPException(404, "Data files not found")
    points, deviations = _compute_deviations_for_viz(scan_path, cad_path, max_points=30000)
    return {"points": points, "deviations": deviations, "count": len(points)}


@app.get("/api/config")
async def api_config():
    config_path = PROJECT_ROOT / "config" / "pipeline_config.yaml"
    import yaml
    with open(config_path) as f:
        return yaml.safe_load(f)


@app.get("/api/rotor-configs")
async def api_rotor_configs():
    path = PROJECT_ROOT / "config" / "rotor_configurations.json"
    with open(path) as f:
        return json.load(f)


@app.post("/api/pipeline/run")
async def api_run_pipeline(background_tasks: BackgroundTasks):
    if pipeline_status["running"]:
        return {"status": "already_running", "progress": pipeline_status["progress"]}

    def _run():
        pipeline_status["running"] = True
        pipeline_status["progress"] = "Starting pipeline..."
        try:
            os.chdir(str(PROJECT_ROOT))
            from pipeline import run_pipeline
            pipeline_status["progress"] = "Running 8-phase pipeline..."
            result = run_pipeline(
                ply_path="data/sample_scan.ply",
                cad_path="data/cad_reference.ply",
                part_number="4134613",
                config_path="config/pipeline_config.yaml",
            )
            pipeline_status["last_result"] = result
            pipeline_status["progress"] = "Complete"
        except Exception as e:
            pipeline_status["progress"] = f"Error: {e}"
        finally:
            pipeline_status["running"] = False

    background_tasks.add_task(_run)
    return {"status": "started"}


@app.get("/api/pipeline/status")
async def api_pipeline_status():
    return pipeline_status


# ----- Batch Pipeline Endpoints -----

@app.get("/batch-jobs", response_class=HTMLResponse)
async def batch_jobs_page(request: Request):
    """Batch job monitoring and submission UI."""
    return _render(request, "batch_jobs.html")


def _get_batch_manager():
    from batch_manager import get_manager
    return get_manager()


@app.post("/api/pipeline/batch")
async def api_batch_submit(request: Request):
    """Submit one or more pipeline jobs.
    Body: {"jobs": [{"stage_id": 3, "part_number": "4134613", "scan_path": "...", "cad_path": "..."}]}
    """
    body = await request.json()
    mgr = _get_batch_manager()
    jobs_input = body.get("jobs", [])
    if not jobs_input:
        raise HTTPException(400, "No jobs provided. Send {\"jobs\": [...]}")
    submitted = mgr.submit_batch(jobs_input)
    return {
        "submitted": len(submitted),
        "jobs": [
            {"job_id": j.job_id, "part": j.part_id.job_key, "status": j.status.value}
            for j in submitted
        ],
    }


@app.get("/api/pipeline/jobs")
async def api_list_jobs():
    """Return all batch jobs with current status."""
    mgr = _get_batch_manager()
    jobs = mgr.get_all_jobs()
    summary = mgr.get_batch_summary()
    return {
        "summary": summary,
        "jobs": [
            {
                "job_id": j.job_id,
                "stage_id": j.part_id.stage_id,
                "part_number": j.part_id.part_number,
                "fin_id": j.part_id.fin_id,
                "job_key": j.part_id.job_key,
                "status": j.status.value,
                "progress": j.progress,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "duration_s": j.duration_s,
                "error": j.error,
                "scan_path": j.scan_path,
                "cad_path": j.cad_path,
            }
            for j in jobs
        ],
    }


@app.get("/api/pipeline/jobs/{job_id}")
async def api_get_job(job_id: str):
    """Return a single job's status and details."""
    mgr = _get_batch_manager()
    j = mgr.get_job(job_id)
    if not j:
        raise HTTPException(404, f"Job not found: {job_id}")
    return {
        "job_id": j.job_id,
        "stage_id": j.part_id.stage_id,
        "part_number": j.part_id.part_number,
        "fin_id": j.part_id.fin_id,
        "job_key": j.part_id.job_key,
        "status": j.status.value,
        "progress": j.progress,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "duration_s": j.duration_s,
        "error": j.error,
        "result_summary": {
            "total_defects": j.result.get("total_defects"),
            "overall_disposition": j.result.get("overall_disposition"),
        } if j.result else None,
    }


@app.post("/api/pipeline/jobs/{job_id}/cancel")
async def api_cancel_job(job_id: str):
    mgr = _get_batch_manager()
    ok = mgr.cancel_job(job_id)
    if not ok:
        raise HTTPException(400, "Job cannot be cancelled (not queued)")
    return {"status": "cancelled", "job_id": job_id}


@app.post("/api/pipeline/jobs/{job_id}/retry")
async def api_retry_job(job_id: str):
    mgr = _get_batch_manager()
    j = mgr.retry_job(job_id)
    if not j:
        raise HTTPException(400, "Job cannot be retried (not failed)")
    return {"status": "requeued", "job_id": j.job_id}


@app.delete("/api/pipeline/jobs/completed")
async def api_clear_completed():
    mgr = _get_batch_manager()
    mgr.clear_completed()
    return {"status": "cleared"}


@app.get("/api/sprint4/report")
async def api_sprint4_report():
    """Return the latest Sprint 4 analysis JSON."""
    report = _load_latest_sprint4_report()
    if not report:
        raise HTTPException(404, "No Sprint 4 report found")
    return report


@app.get("/api/maintenance/data")
async def api_maintenance_data():
    """Lightweight payload for the maintenance view: summary + defects (no raw points).
    Tries all reports and picks the one with the most defects so that a fresh
    git-pull (where all mtimes are identical) still surfaces real data."""
    output_dir = PROJECT_ROOT / "output"
    best, best_count = None, -1
    for f in output_dir.glob("*.json"):
        if f.name.endswith("_features_metadata.json"):
            continue
        try:
            with open(f) as fh:
                data = json.load(fh)
            n = len(data.get("defects", []))
            has_ml = any(d.get("classified_type") for d in data.get("defects", [])[:3])
            score = n * 10 + (5 if has_ml else 0) + (3 if data.get("sprint4") else 0)
            if score > best_count:
                best, best_count = data, score
        except Exception:
            continue
    report = best
    if not report:
        raise HTTPException(404, "No inspection report available. Run the pipeline first.")
    stripped_defects = []
    for d in report.get("defects", []):
        stripped_defects.append({
            "defect_id": d.get("defect_id"),
            "foil_number": d.get("foil_number"),
            "classified_type": d.get("classified_type") or d.get("defect_type") or d.get("classification", "unknown"),
            "zone_ids": d.get("zone_ids", []),
            "zone_names": d.get("zone_names", []),
            "depth_in": d.get("depth_in", 0),
            "length_in": d.get("length_in", 0),
            "width_in": d.get("width_in", 0),
            "disposition": d.get("disposition", "N/A"),
            "ml_prediction": d.get("ml_prediction"),
            "ml_confidence": d.get("ml_confidence"),
            "classification": d.get("classification"),
            "nearest_edge": d.get("nearest_edge"),
            "edge_distance_mm": d.get("edge_distance_mm"),
        })
    return {
        "part_number": report.get("part_number"),
        "total_defects": report.get("total_defects", len(stripped_defects)),
        "foil_count": report.get("foil_count", 0),
        "overall_disposition": report.get("overall_disposition", "N/A"),
        "timestamp": report.get("timestamp"),
        "scan_file": report.get("scan_file"),
        "disposition_breakdown": report.get("disposition_breakdown", {}),
        "defects": stripped_defects,
    }


@app.get("/api/zone-map/data")
async def api_zone_map_data():
    """Per-zone defect aggregation for the blade zone map visualization."""
    report = _load_latest_report()
    if not report:
        raise HTTPException(404, "No report available")
    zone_agg = {}
    for d in report.get("defects", []):
        dtype = d.get("classified_type") or d.get("classification", "unknown")
        disp = d.get("disposition", "N/A")
        depth = d.get("depth_in", 0)
        for zid in (d.get("zone_ids") or d.get("zones") or []):
            if zid not in zone_agg:
                zone_agg[zid] = {"zone_id": zid, "count": 0, "types": {}, "dispositions": {}, "max_depth_in": 0, "defect_ids": []}
            z = zone_agg[zid]
            z["count"] += 1
            z["types"][dtype] = z["types"].get(dtype, 0) + 1
            z["dispositions"][disp] = z["dispositions"].get(disp, 0) + 1
            z["max_depth_in"] = max(z["max_depth_in"], depth or 0)
            z["defect_ids"].append(d.get("defect_id"))
    return {
        "part_number": report.get("part_number"),
        "total_defects": report.get("total_defects", 0),
        "foil_count": report.get("foil_count", 0),
        "zones": zone_agg,
    }


@app.get("/api/2d-views")
async def api_2d_views_list():
    """Return list of generated 2D view filenames/paths under output/2d_views."""
    views_dir = PROJECT_ROOT / "output" / "2d_views"
    if not views_dir.exists():
        return {"files": [], "base_path": str(views_dir)}
    files = [f.name for f in views_dir.iterdir() if f.is_file()]
    return {"files": sorted(files), "base_path": str(views_dir)}


@app.get("/api/2d-views/{filename}")
async def api_2d_view_file(filename: str):
    """Serve image file from output/2d_views."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")
    views_dir = PROJECT_ROOT / "output" / "2d_views"
    filepath = views_dir / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(404, f"2D view not found: {filename}")
    return FileResponse(str(filepath), filename=filename)


@app.get("/api/ml/metrics")
async def api_ml_metrics():
    """Return ML training metrics from models/training_metrics.json if it exists."""
    metrics_path = PROJECT_ROOT / "models" / "training_metrics.json"
    if not metrics_path.exists():
        raise HTTPException(404, "Training metrics not found")
    with open(metrics_path) as f:
        return json.load(f)


@app.get("/api/features/metadata")
async def api_features_metadata():
    """Return feature metadata JSON for latest inspection if exists."""
    output_dir = PROJECT_ROOT / "output"
    meta_files = sorted(
        output_dir.glob("*_features_metadata.json"),
        key=os.path.getmtime,
        reverse=True,
    )
    if not meta_files:
        raise HTTPException(404, "No feature metadata found")
    with open(meta_files[0]) as f:
        return json.load(f)


# ----- Phase Figure Endpoints -----

@app.get("/phase-viewer", response_class=HTMLResponse)
async def phase_viewer(request: Request):
    return _render(request, "phase_viewer.html")


@app.get("/api/phases")
async def api_phases_list():
    viz_dir = PROJECT_ROOT / "output" / "visualizations"
    if not viz_dir.exists():
        return {"files": []}
    files = sorted(f.name for f in viz_dir.iterdir() if f.suffix == ".json")
    return {"files": files}


@app.get("/api/phases/{phase}/figure")
async def api_phase_figure(phase: int):
    viz_dir = PROJECT_ROOT / "output" / "visualizations"
    prefix = f"phase{phase}_"
    for f in viz_dir.iterdir():
        if f.name.startswith(prefix) and f.suffix == ".json":
            with open(f) as fh:
                return json.load(fh)
    raise HTTPException(404, f"Phase {phase} figure JSON not found")


@app.get("/api/phases/{phase}/html")
async def api_phase_html(phase: int):
    viz_dir = PROJECT_ROOT / "output" / "visualizations"
    prefix = f"phase{phase}_"
    for f in viz_dir.iterdir():
        if f.name.startswith(prefix) and f.suffix == ".html":
            return FileResponse(str(f), media_type="text/html", filename=f.name)
    raise HTTPException(404, f"Phase {phase} HTML not found")


if __name__ == "__main__":
    import uvicorn
    os.chdir(str(PROJECT_ROOT))
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
