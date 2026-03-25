"""CLI batch runner for IBR pipeline jobs.

Usage examples:
  # Run single job
  python src/batch_runner.py --stage 3 --part 4134613 --scan data/sample_scan.ply --cad data/cad_reference.ply

  # Run multiple jobs from a CSV/JSON manifest
  python src/batch_runner.py --manifest jobs.json

  # Run all configured rotors with default data
  python src/batch_runner.py --all-stages --scan data/sample_scan.ply --cad data/cad_reference.ply

  # Control parallelism
  python src/batch_runner.py --manifest jobs.json --workers 4

  # Dry run (show what would be queued)
  python src/batch_runner.py --manifest jobs.json --dry-run
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils"))

import cli_errors
from batch_manager import BatchJobManager

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config")
_ROTOR_CONFIG = os.path.join(_CONFIG_DIR, "rotor_configurations.json")

POLL_INTERVAL = 2  # seconds between status refreshes

# ── status symbols ────────────────────────────────────────────────────
_STATUS_STYLE = {
    "queued":   ("QUEUED  ", ""),
    "running":  ("RUNNING ", ""),
    "complete": ("COMPLETE", " ✓"),
    "failed":   ("FAILED  ", " ✗"),
}

_PHASE_LABELS = {
    1: "Data Preparation",
    2: "Registration",
    3: "Deviation Analysis",
    4: "Foil Segmentation",
    5: "Defect Clustering",
    6: "Measurement",
    7: "Zone Classification",
    8: "Report Generation",
}


# ── CLI argument parser ──────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch runner for the IBR defect-extraction pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-s", "--stage",
        type=int,
        metavar="ID",
        help="Stage ID (int) for a single job",
    )
    parser.add_argument(
        "-p", "--part",
        type=str,
        metavar="NUM",
        help="Part number (str) for a single job",
    )
    parser.add_argument(
        "--fin",
        type=str,
        metavar="FIN",
        default=None,
        help="Fin ID (optional)",
    )
    parser.add_argument(
        "--scan",
        type=str,
        metavar="PATH",
        help="Scan PLY file path",
    )
    parser.add_argument(
        "--cad",
        type=str,
        metavar="PATH",
        help="CAD PLY file path",
    )
    parser.add_argument(
        "-m", "--manifest",
        type=str,
        metavar="PATH",
        help="Path to JSON manifest file with an array of job objects",
    )
    parser.add_argument(
        "--all-stages",
        action="store_true",
        help="Run one job per rotor in rotor_configurations.json",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=2,
        metavar="N",
        help="Max parallel workers (default: 2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print job table and exit without running",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        metavar="SEC",
        help="Max seconds per job (default: 900)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output (includes tracebacks on failure)",
    )
    return parser


# ── job building helpers ─────────────────────────────────────────────

def _build_single_job(args) -> list[dict]:
    """Build a one-element list from --stage / --part / --scan / --cad."""
    missing = []
    if args.stage is None:
        missing.append("--stage")
    if not args.part:
        missing.append("--part")
    if not args.scan:
        missing.append("--scan")
    if not args.cad:
        missing.append("--cad")
    if missing:
        cli_errors.fail(
            f"Single-job mode requires {', '.join(missing)}.",
            code=cli_errors.EXIT_CONFIG_ERROR,
            hint="Provide all of --stage, --part, --scan, and --cad.",
        )

    job = {
        "stage_id": args.stage,
        "part_number": args.part,
        "scan_path": os.path.abspath(args.scan),
        "cad_path": os.path.abspath(args.cad),
    }
    if args.fin:
        job["fin_id"] = args.fin
    return [job]


def _load_manifest(path: str, verbose: bool = False) -> list[dict]:
    """Load jobs from a JSON manifest file."""
    if not os.path.isfile(path):
        cli_errors.fail(
            f"Manifest file not found: {path}",
            code=cli_errors.EXIT_MISSING_INPUT,
            hint="Check the path and try again.",
        )

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        cli_errors.fail(
            f"Failed to parse manifest: {path}",
            code=cli_errors.EXIT_CONFIG_ERROR,
            hint="Ensure the file is valid JSON with a top-level 'jobs' array.",
            exc=exc,
            verbose=verbose,
        )

    jobs = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(jobs, list) or len(jobs) == 0:
        cli_errors.fail(
            "Manifest contains no jobs.",
            code=cli_errors.EXIT_CONFIG_ERROR,
            hint='Expected {"jobs": [{...}, ...]} or a bare JSON array.',
        )

    required_keys = {"stage_id", "part_number", "scan_path", "cad_path"}
    for idx, job in enumerate(jobs):
        missing = required_keys - set(job.keys())
        if missing:
            cli_errors.fail(
                f"Manifest job [{idx}] is missing keys: {', '.join(sorted(missing))}",
                code=cli_errors.EXIT_CONFIG_ERROR,
            )
        job["scan_path"] = os.path.abspath(job["scan_path"])
        job["cad_path"] = os.path.abspath(job["cad_path"])

    return jobs


def _build_all_stages(args) -> list[dict]:
    """Generate one job per rotor from rotor_configurations.json."""
    if not args.scan or not args.cad:
        cli_errors.fail(
            "--all-stages requires --scan and --cad to specify the PLY files.",
            code=cli_errors.EXIT_CONFIG_ERROR,
        )

    if not os.path.isfile(_ROTOR_CONFIG):
        cli_errors.fail(
            f"Rotor configuration file not found: {_ROTOR_CONFIG}",
            code=cli_errors.EXIT_MISSING_INPUT,
            hint="Ensure config/rotor_configurations.json exists.",
        )

    try:
        with open(_ROTOR_CONFIG, "r", encoding="utf-8") as fh:
            rotors = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        cli_errors.fail(
            f"Failed to parse rotor config: {_ROTOR_CONFIG}",
            code=cli_errors.EXIT_CONFIG_ERROR,
            exc=exc,
            verbose=args.verbose,
        )

    scan = os.path.abspath(args.scan)
    cad = os.path.abspath(args.cad)

    return [
        {
            "stage_id": r["stage"],
            "part_number": r["part_number"],
            "scan_path": scan,
            "cad_path": cad,
        }
        for r in rotors
    ]


# ── display helpers ──────────────────────────────────────────────────

def _job_label(job: dict) -> str:
    return f"S{job['stage_id']}_{job['part_number']}"


def _print_header(total: int, running: int, complete: int, failed: int) -> None:
    w = 60
    print(f"╔{'═' * w}╗")
    print(f"║  {'IBR Batch Pipeline Runner':<{w - 2}}║")
    stats = f"Jobs: {total} | Running: {running} | Complete: {complete} | Failed: {failed}"
    print(f"║  {stats:<{w - 2}}║")
    print(f"╚{'═' * w}╝")
    print()


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    return f"{seconds:.1f}s"


def _phase_description(status_info: dict) -> str:
    phase = status_info.get("current_phase")
    if phase and phase in _PHASE_LABELS:
        return f"Phase {phase}: {_PHASE_LABELS[phase]}"
    progress = status_info.get("progress", "")
    if progress:
        return str(progress)
    return ""


def _print_status_table(manager: "BatchJobManager") -> None:
    """Print the live status table for all tracked jobs."""
    statuses = manager.get_all_status()

    counts = {"queued": 0, "running": 0, "complete": 0, "failed": 0}
    for s in statuses:
        key = s.get("status", "queued")
        counts[key] = counts.get(key, 0) + 1

    _print_header(
        total=len(statuses),
        running=counts["running"],
        complete=counts["complete"],
        failed=counts["failed"],
    )

    for s in statuses:
        status_key = s.get("status", "queued")
        tag, suffix = _STATUS_STYLE.get(status_key, ("UNKNOWN ", ""))
        label = _job_label(s)
        duration = _format_duration(s.get("elapsed"))

        if status_key == "complete":
            desc = "Done"
        elif status_key == "failed":
            desc = s.get("error", "Error")[:40]
        elif status_key == "queued":
            desc = "Waiting..."
        else:
            desc = _phase_description(s)

        print(f"[{tag}] {label:<18} {desc:<35} {duration:>8}{suffix}")

    print()


def _print_dry_run(jobs: list[dict]) -> None:
    """Show a table of what would be queued."""
    print("╔" + "═" * 60 + "╗")
    print(f"║  {'DRY RUN — jobs that would be queued':<58}║")
    print("╚" + "═" * 60 + "╝")
    print()
    print(f"  {'#':<4} {'Label':<18} {'Scan':<40}")
    print(f"  {'—' * 3} {'—' * 17} {'—' * 39}")

    for i, job in enumerate(jobs, 1):
        label = _job_label(job)
        scan_short = os.path.basename(job["scan_path"])
        fin = job.get("fin_id", "")
        extra = f"  fin={fin}" if fin else ""
        print(f"  {i:<4} {label:<18} {scan_short:<40}{extra}")

    print(f"\n  Total: {len(jobs)} job(s)  (use without --dry-run to execute)\n")


def _print_summary(manager: "BatchJobManager", wall_time: float) -> None:
    statuses = manager.get_all_status()
    total = len(statuses)
    passed = sum(1 for s in statuses if s.get("status") == "complete")
    failed = sum(1 for s in statuses if s.get("status") == "failed")

    print("═" * 62)
    print("  BATCH SUMMARY")
    print("═" * 62)
    print(f"  Total jobs : {total}")
    print(f"  Passed     : {passed}")
    print(f"  Failed     : {failed}")
    print(f"  Wall time  : {wall_time:.1f}s")
    print("═" * 62)

    if failed:
        print("\n  Failed jobs:")
        for s in statuses:
            if s.get("status") == "failed":
                print(f"    {_job_label(s)}: {s.get('error', 'unknown error')}")
        print()


# ── main entry point ─────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ── decide which mode produced the job list ──
    modes = sum([
        args.manifest is not None,
        args.all_stages,
        args.stage is not None or args.part is not None,
    ])
    if modes == 0:
        parser.print_help()
        cli_errors.fail(
            "No jobs specified.",
            code=cli_errors.EXIT_CONFIG_ERROR,
            hint="Use --stage/--part, --manifest, or --all-stages.",
        )
    if modes > 1:
        cli_errors.fail(
            "Specify only one of: --stage/--part, --manifest, or --all-stages.",
            code=cli_errors.EXIT_CONFIG_ERROR,
        )

    if args.manifest:
        jobs = _load_manifest(args.manifest, verbose=args.verbose)
    elif args.all_stages:
        jobs = _build_all_stages(args)
    else:
        jobs = _build_single_job(args)

    # ── validate scan/cad files exist ──
    for job in jobs:
        cli_errors.require_file(job["scan_path"], f"Scan ({_job_label(job)})")
        cli_errors.require_file(job["cad_path"], f"CAD ({_job_label(job)})")

    # ── dry run ──
    if args.dry_run:
        _print_dry_run(jobs)
        return cli_errors.EXIT_OK

    # ── execute ──
    manager = BatchJobManager(max_workers=args.workers, timeout=args.timeout)

    for job in jobs:
        manager.submit(job)

    wall_start = time.time()

    try:
        while not manager.all_done():
            # clear screen on terminals that support ANSI codes
            if sys.stdout.isatty():
                print("\033[2J\033[H", end="", flush=True)
            _print_status_table(manager)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n\n  Interrupted — cancelling remaining jobs...")
        manager.cancel_all()
    finally:
        # one final status print (non-tty or after interrupt)
        _print_status_table(manager)

    wall_time = time.time() - wall_start
    _print_summary(manager, wall_time)

    any_failed = any(
        s.get("status") == "failed" for s in manager.get_all_status()
    )
    return cli_errors.EXIT_PIPELINE_ERROR if any_failed else cli_errors.EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        cli_errors.fail(
            "Unexpected error in batch_runner.",
            code=cli_errors.EXIT_UNKNOWN,
            exc=exc,
            verbose="--verbose" in sys.argv or "-v" in sys.argv,
        )
