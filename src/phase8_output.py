import json
import os
import datetime
import numpy as np
import yaml

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

MM_PER_INCH = 25.4


class OutputGenerator:
    """Phase 8: Generate Excel/JSON reports and determine overall disposition."""

    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config not found: {config_path}")
        with open(config_path) as f:
            full_config = yaml.safe_load(f)
        if "output" not in full_config:
            raise KeyError("Missing 'output' section in config")
        self.config = full_config["output"]
        self.output_dir = "output"
        os.makedirs(self.output_dir, exist_ok=True)

    def execute(self, defects: list[dict], metadata: dict) -> dict:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        part_number = metadata.get("part_number", "unknown")

        overall_disposition = self._compute_overall_disposition(defects)

        summary = {
            "timestamp": timestamp,
            "part_number": part_number,
            "scan_file": metadata.get("scan_file", ""),
            "cad_file": metadata.get("cad_file", ""),
            "alignment_rmse_mm": metadata.get("alignment_rmse", 0.0),
            "foil_count": metadata.get("foil_count", 0),
            "total_defects": len(defects),
            "overall_disposition": overall_disposition,
            "disposition_breakdown": self._disposition_breakdown(defects),
            "defects": [self._serialize_defect(d) for d in defects],
        }

        if self.config.get("include_json", True):
            json_path = os.path.join(
                self.output_dir, f"{part_number}_{timestamp}.json"
            )
            with open(json_path, "w") as f:
                json.dump(summary, f, indent=2, default=str)
            print(f"  [Phase 8] JSON report: {json_path}")

        if self.config.get("format") == "excel" and HAS_OPENPYXL:
            xlsx_path = os.path.join(
                self.output_dir, f"{part_number}_{timestamp}.xlsx"
            )
            self._write_excel(summary, defects, xlsx_path)
            print(f"  [Phase 8] Excel report: {xlsx_path}")
        elif self.config.get("format") == "excel":
            print("  [Phase 8] WARNING: openpyxl not installed, skipping Excel output")

        print(f"  [Phase 8] Overall disposition: {overall_disposition}")
        return {"overall_disposition": overall_disposition, **summary}

    def _compute_overall_disposition(self, defects: list[dict]) -> str:
        tiers = self.config.get("disposition_tiers", ["SERVICEABLE", "BLEND", "REPLACE"])
        if not defects:
            return tiers[0] if tiers else "SERVICEABLE"

        dispositions = [d.get("disposition", "SERVICEABLE") for d in defects]

        for tier in reversed(tiers):
            if tier in dispositions:
                return tier
        return tiers[0]

    def _disposition_breakdown(self, defects: list[dict]) -> dict[str, int]:
        breakdown: dict[str, int] = {}
        for d in defects:
            disp = d.get("disposition", "SERVICEABLE")
            breakdown[disp] = breakdown.get(disp, 0) + 1
        return breakdown

    def _serialize_defect(self, defect: dict) -> dict:
        serialized = {}
        for key, value in defect.items():
            if isinstance(value, np.ndarray):
                serialized[key] = value.tolist()
            elif isinstance(value, (np.float32, np.float64)):
                serialized[key] = float(value)
            elif isinstance(value, (np.int32, np.int64)):
                serialized[key] = int(value)
            else:
                serialized[key] = value
        return serialized

    def _write_excel(self, summary: dict, defects: list[dict], path: str):
        wb = openpyxl.Workbook()

        ws_summary = wb.active
        ws_summary.title = "Summary"
        summary_rows = [
            ("Part Number", summary["part_number"]),
            ("Timestamp", summary["timestamp"]),
            ("Scan File", summary["scan_file"]),
            ("CAD File", summary["cad_file"]),
            ("Alignment RMSE (mm)", summary["alignment_rmse_mm"]),
            ("Foil Count", summary["foil_count"]),
            ("Total Defects", summary["total_defects"]),
            ("Overall Disposition", summary["overall_disposition"]),
        ]
        for disp, count in summary.get("disposition_breakdown", {}).items():
            summary_rows.append((f"  {disp}", count))

        for row in summary_rows:
            ws_summary.append(row)

        ws_defects = wb.create_sheet("Defects")
        headers = [
            "Defect ID", "Foil", "Zone(s)", "Classification",
            "Depth (in)", "Length (in)", "Width (in)",
            "Depth (mm)", "Length (mm)", "Width (mm)",
            "Nearest Edge", "Edge Dist (mm)",
            "Disposition", "Rule Applied",
        ]
        ws_defects.append(headers)

        for d in defects:
            zones = d.get("zone_ids", d.get("zone_names", []))
            zone_str = ", ".join(str(z) for z in zones) if zones else ""
            ws_defects.append([
                d.get("defect_id", ""),
                d.get("foil_number", ""),
                zone_str,
                d.get("classification", ""),
                d.get("depth_in", 0.0),
                d.get("length_in", 0.0),
                d.get("width_in", 0.0),
                d.get("depth_mm", d.get("max_depth_mm", 0.0)),
                d.get("length_mm", 0.0),
                d.get("width_mm", 0.0),
                d.get("nearest_edge", ""),
                d.get("edge_distance_mm", ""),
                d.get("disposition", ""),
                d.get("rule_applied", ""),
            ])

        for ws in [ws_summary, ws_defects]:
            for col in ws.columns:
                max_len = 0
                col_letter = col[0].column_letter
                for cell in col:
                    if cell.value:
                        max_len = max(max_len, len(str(cell.value)))
                ws.column_dimensions[col_letter].width = min(max_len + 2, 40)

        wb.save(path)
