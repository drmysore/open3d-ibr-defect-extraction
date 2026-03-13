"""Export Plotly figures to JSON, HTML, and PNG for dashboard and offline review."""

import json
import os
from pathlib import Path
from typing import Optional

import plotly.graph_objects as go


def export_figure(
    fig: go.Figure,
    output_dir: str,
    filename: str,
    formats: Optional[list] = None,
) -> dict:
    """
    Export Plotly figure to JSON, HTML, and optionally PNG.

    Args:
        fig: Plotly Figure object
        output_dir: Target directory
        filename: Base filename (no extension)
        formats: List of 'json', 'html', 'png'. Default: ['json', 'html']

    Returns:
        Dict of format -> path for each exported file.
    """
    if formats is None:
        formats = ["json", "html"]

    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    result = {}

    if "json" in formats:
        out = path / f"{filename}.json"
        with open(out, "w") as f:
            f.write(fig.to_json())
        result["json"] = str(out)

    if "html" in formats:
        out = path / f"{filename}.html"
        fig.write_html(
            str(out),
            include_plotlyjs="cdn",
            full_html=True,
            config=dict(displayModeBar=True, displaylogo=False),
        )
        result["html"] = str(out)

    if "png" in formats:
        try:
            out = path / f"{filename}.png"
            fig.write_image(str(out), width=1920, height=1080, scale=2)
            result["png"] = str(out)
        except Exception as e:
            result["png_error"] = str(e)

    return result
