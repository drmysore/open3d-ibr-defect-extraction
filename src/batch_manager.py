"""Batch job queue and management system for the IBR Defect Extraction pipeline.

Supports processing multiple IBR parts (MRO shop jobs) in parallel or
sequentially with compound identifiers.  Thread-safe job tracking, lifecycle
logging, and graceful shutdown.

Usage::

    from batch_manager import get_manager
    mgr = get_manager()
    job = mgr.submit_job(
        part_id=CompoundPartID(stage_id=1, part_number="4134613"),
        scan_path="data/sample_scan.ply",
        cad_path="data/cad_reference.ply",
    )
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
_UTILS_DIR = os.path.join(_SRC_DIR, "utils")
if _UTILS_DIR not in sys.path:
    sys.path.insert(0, _UTILS_DIR)


# ---------------------------------------------------------------------------
# Pipeline imports — resolved lazily to avoid hard startup failures
# ---------------------------------------------------------------------------

_pipeline_v2_run = None
_pipeline_v1_run = None


def _ensure_pipeline_imports() -> None:
    """Attempt to import pipeline runner functions once, caching the result."""
    global _pipeline_v2_run, _pipeline_v1_run  # noqa: PLW0603

    if _pipeline_v2_run is not None or _pipeline_v1_run is not None:
        return

    try:
        from pipeline_v2 import run_pipeline_v2
        _pipeline_v2_run = run_pipeline_v2
        logger.info("pipeline_v2.run_pipeline_v2 imported successfully")
    except Exception as exc:
        logger.warning("Could not import pipeline_v2: %s", exc)

    try:
        from pipeline import run_pipeline
        _pipeline_v1_run = run_pipeline
        logger.info("pipeline.run_pipeline imported successfully")
    except Exception as exc:
        logger.warning("Could not import pipeline (v1): %s", exc)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _read_max_workers() -> int:
    """Derive worker count from ``pipeline_config.yaml`` performance section.

    If ``performance.parallel_processing`` is true, returns
    ``max(cpu_count // 2, 2)``; otherwise returns ``1``.
    """
    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not available — defaulting to 2 workers")
        return 2

    for candidate in (
        os.path.join(_SRC_DIR, "..", "config", "pipeline_config.yaml"),
        os.path.join(os.getcwd(), "config", "pipeline_config.yaml"),
    ):
        candidate = os.path.normpath(candidate)
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r") as fh:
                    cfg = yaml.safe_load(fh)
                perf = cfg.get("performance", {})
                if perf.get("parallel_processing", False):
                    return max(os.cpu_count() // 2, 2)
                return 1
            except Exception as exc:
                logger.warning("Error reading config %s: %s", candidate, exc)

    return 2


def _read_timeout() -> float:
    """Return ``performance.max_time_per_ibr_seconds`` from config, or 900."""
    try:
        import yaml
    except ImportError:
        return 900.0

    for candidate in (
        os.path.join(_SRC_DIR, "..", "config", "pipeline_config.yaml"),
        os.path.join(os.getcwd(), "config", "pipeline_config.yaml"),
    ):
        candidate = os.path.normpath(candidate)
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r") as fh:
                    cfg = yaml.safe_load(fh)
                return float(
                    cfg.get("performance", {}).get("max_time_per_ibr_seconds", 900)
                )
            except Exception:
                pass
    return 900.0


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CompoundPartID:
    """Identifies an IBR part within an MRO shop job.

    The ``job_key`` property produces a filesystem-safe string suitable for
    prefixing output filenames.
    """

    stage_id: int
    part_number: str
    fin_id: Optional[str] = None

    @property
    def job_key(self) -> str:
        base = f"S{self.stage_id}_{self.part_number}"
        if self.fin_id:
            return f"{base}_{self.fin_id}"
        return base


class JobStatus(Enum):
    """Lifecycle states of a batch job."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class BatchJob:
    """Represents a single pipeline execution for one IBR part."""

    job_id: str
    part_id: CompoundPartID
    status: JobStatus
    created_at: datetime
    scan_path: str
    cad_path: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: str = "Queued"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None
    config_path: str = "config/pipeline_config.yaml"
    pipeline_version: str = "v2"
    _future: Any = field(default=None, repr=False, compare=False)


# ---------------------------------------------------------------------------
# BatchJobManager
# ---------------------------------------------------------------------------

class BatchJobManager:
    """Thread-safe job queue manager backed by a :class:`ThreadPoolExecutor`.

    Parameters
    ----------
    max_workers:
        Maximum concurrent pipeline executions.
    output_dir:
        Base directory for pipeline output artefacts.
    """

    def __init__(self, max_workers: int = 2, output_dir: str = "output") -> None:
        self._max_workers = max_workers
        self._output_dir = output_dir
        self._lock = threading.Lock()
        self._jobs: Dict[str, BatchJob] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ibr-batch"
        )
        self._timeout_s = _read_timeout()
        logger.info(
            "BatchJobManager initialised — workers=%d, output=%s, timeout=%.0fs",
            max_workers,
            output_dir,
            self._timeout_s,
        )

    # -- submission -----------------------------------------------------------

    def submit_job(
        self,
        part_id: CompoundPartID,
        scan_path: str,
        cad_path: str,
        config_path: Optional[str] = None,
        pipeline_version: str = "v2",
    ) -> BatchJob:
        """Queue a single pipeline job.  Returns the ``BatchJob`` immediately."""
        job = BatchJob(
            job_id=str(uuid.uuid4()),
            part_id=part_id,
            status=JobStatus.QUEUED,
            created_at=datetime.utcnow(),
            scan_path=scan_path,
            cad_path=cad_path,
            config_path=config_path or "config/pipeline_config.yaml",
            pipeline_version=pipeline_version,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        logger.info("Job %s queued for %s", job.job_id, part_id.job_key)
        job._future = self._executor.submit(self._run_job, job)
        return job

    def submit_batch(self, jobs_list: List[Dict[str, Any]]) -> List[BatchJob]:
        """Submit multiple jobs at once.

        Each dict in *jobs_list* must contain ``stage_id``, ``part_number``,
        ``scan_path``, ``cad_path`` and optionally ``fin_id``, ``config_path``,
        ``pipeline_version``.
        """
        submitted: List[BatchJob] = []
        for entry in jobs_list:
            stage = entry.get("stage_id") or entry.get("stage") or entry.get("id") or 0
            part = entry.get("part_number") or entry.get("part") or "unknown"
            scan = entry.get("scan_path") or entry.get("scan_ply") or "data/sample_scan.ply"
            cad = entry.get("cad_path") or entry.get("cad_ply") or "data/cad_reference.ply"
            part_id = CompoundPartID(
                stage_id=int(stage) if str(stage).isdigit() else stage,
                part_number=str(part),
                fin_id=entry.get("fin_id"),
            )
            job = self.submit_job(
                part_id=part_id,
                scan_path=str(scan),
                cad_path=str(cad),
                config_path=entry.get("config_path"),
                pipeline_version=entry.get("pipeline_version", "v2"),
            )
            submitted.append(job)
        return submitted

    # -- queries --------------------------------------------------------------

    def get_job(self, job_id: str) -> BatchJob:
        """Return a job by its UUID.

        Raises :class:`KeyError` if not found.
        """
        with self._lock:
            return self._jobs[job_id]

    def get_all_jobs(self) -> List[BatchJob]:
        """Return every tracked job, newest first."""
        with self._lock:
            return sorted(
                self._jobs.values(), key=lambda j: j.created_at, reverse=True
            )

    def get_batch_summary(self) -> Dict[str, int]:
        """Aggregate counts by status."""
        summary: Dict[str, int] = {s.value: 0 for s in JobStatus}
        summary["total"] = 0
        with self._lock:
            for job in self._jobs.values():
                summary[job.status.value] += 1
                summary["total"] += 1
        return summary

    # -- mutation -------------------------------------------------------------

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued or running job.

        Returns ``True`` if the job was successfully cancelled.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                return False
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.utcnow()
            if job._future is not None:
                job._future.cancel()
        logger.info("Job %s cancelled", job_id)
        return True

    def retry_job(self, job_id: str) -> BatchJob:
        """Re-queue a previously failed job.

        Raises :class:`ValueError` if the job is not in ``FAILED`` state.
        """
        with self._lock:
            old = self._jobs.get(job_id)
            if old is None:
                raise KeyError(f"Unknown job: {job_id}")
            if old.status != JobStatus.FAILED:
                raise ValueError(
                    f"Only FAILED jobs can be retried (current: {old.status.value})"
                )

        return self.submit_job(
            part_id=old.part_id,
            scan_path=old.scan_path,
            cad_path=old.cad_path,
            config_path=old.config_path,
            pipeline_version=old.pipeline_version,
        )

    def clear_completed(self) -> int:
        """Remove all terminal-state jobs.  Returns the count removed."""
        terminal = {JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED}
        removed = 0
        with self._lock:
            to_remove = [
                jid for jid, j in self._jobs.items() if j.status in terminal
            ]
            for jid in to_remove:
                del self._jobs[jid]
                removed += 1
        if removed:
            logger.info("Cleared %d completed job(s)", removed)
        return removed

    # -- execution (runs inside thread pool) ----------------------------------

    def _run_job(self, job: BatchJob) -> None:
        """Execute the pipeline for a single job.  Called by the executor."""
        with self._lock:
            if job.status == JobStatus.CANCELLED:
                return
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            job.progress = "Preparing..."

        logger.info(
            "Job %s RUNNING — part=%s scan=%s",
            job.job_id,
            job.part_id.job_key,
            job.scan_path,
        )
        start_ts = time.monotonic()

        try:
            _ensure_pipeline_imports()

            runner = None
            if job.pipeline_version == "v2" and _pipeline_v2_run is not None:
                runner = _pipeline_v2_run
            elif _pipeline_v1_run is not None:
                runner = _pipeline_v1_run
            elif _pipeline_v2_run is not None:
                runner = _pipeline_v2_run
            else:
                raise RuntimeError("No pipeline runner available (v1 or v2)")

            self._update_progress(job, "Phase 1: Data Preparation")
            self._update_progress(job, "Phase 2: Registration")
            self._update_progress(job, "Phase 3: Deviation Analysis")

            os.makedirs(self._output_dir, exist_ok=True)

            result = runner(
                ply_path=job.scan_path,
                cad_path=job.cad_path,
                part_number=job.part_id.job_key,
                config_path=job.config_path,
            )

            elapsed = time.monotonic() - start_ts
            if elapsed > self._timeout_s:
                logger.warning(
                    "Job %s exceeded timeout (%.1fs > %.1fs) but completed",
                    job.job_id,
                    elapsed,
                    self._timeout_s,
                )

            with self._lock:
                job.status = JobStatus.COMPLETE
                job.result = result
                job.completed_at = datetime.utcnow()
                job.duration_s = round(elapsed, 2)
                job.progress = "Complete"

            logger.info(
                "Job %s COMPLETE in %.1fs — disposition=%s",
                job.job_id,
                elapsed,
                result.get("overall_disposition", "N/A") if isinstance(result, dict) else "N/A",
            )

        except Exception as exc:
            elapsed = time.monotonic() - start_ts
            with self._lock:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                job.completed_at = datetime.utcnow()
                job.duration_s = round(elapsed, 2)
                job.progress = "Failed"

            logger.error(
                "Job %s FAILED after %.1fs: %s", job.job_id, elapsed, exc, exc_info=True
            )

    def _update_progress(self, job: BatchJob, phase: str) -> None:
        with self._lock:
            if job.status == JobStatus.CANCELLED:
                return
            job.progress = phase
        logger.debug("Job %s progress: %s", job.job_id, phase)

    # -- lifecycle ------------------------------------------------------------

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the thread pool.

        Parameters
        ----------
        wait:
            If ``True`` (default), block until running jobs finish.
        """
        logger.info("BatchJobManager shutting down (wait=%s)", wait)
        self._executor.shutdown(wait=wait)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_manager: Optional[BatchJobManager] = None
_manager_lock = threading.Lock()


def get_manager() -> BatchJobManager:
    """Return the process-wide :class:`BatchJobManager` singleton.

    On first call the manager is initialised with worker count derived from
    ``pipeline_config.yaml``.
    """
    global _manager  # noqa: PLW0603
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                workers = _read_max_workers()
                _manager = BatchJobManager(max_workers=workers)
    return _manager
