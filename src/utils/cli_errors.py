"""CLI exit codes and user-facing error messages for pipeline scripts.

Use consistent codes so automation and CI can interpret failures.
"""

import sys
import traceback
from typing import Optional

# Exit codes (documented in README)
EXIT_OK = 0
EXIT_MISSING_INPUT = 2
EXIT_PIPELINE_ERROR = 3
EXIT_CONFIG_ERROR = 4
EXIT_DEPENDENCY_ERROR = 5
EXIT_UNKNOWN = 1


def fail(
    message: str,
    *,
    code: int = EXIT_UNKNOWN,
    hint: Optional[str] = None,
    exc: Optional[BaseException] = None,
    verbose: bool = False,
) -> None:
    """Print error, optional hint and traceback, then sys.exit(code)."""
    print("\n" + "=" * 60, file=sys.stderr)
    print("  ERROR", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  {message}", file=sys.stderr)
    if hint:
        print(f"\n  How to fix:", file=sys.stderr)
        for line in hint.strip().split("\n"):
            print(f"    {line}", file=sys.stderr)
    if exc and verbose:
        print(f"\n  Exception: {exc!r}", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)
    sys.exit(code)


def require_file(path: str, label: str) -> None:
    """Exit with EXIT_MISSING_INPUT if path is not a readable file."""
    import os

    if not path or not os.path.isfile(path):
        fail(
            f"{label} file not found or not a file:\n  {path}",
            code=EXIT_MISSING_INPUT,
            hint=(
                "For real data, ensure data/real_scan_4119905.ply and data/real_cad_4119905.ply exist "
                "(clone branch inferno_j4 or run src/stl_to_ply_sampled.py with --stl-path).\n"
                "Set REAL_STL_PATH or use: python src/stl_to_ply_sampled.py --stl-path <path>"
            ),
        )
