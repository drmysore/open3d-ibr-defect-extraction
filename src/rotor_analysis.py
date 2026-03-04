from defect_library import DefectLibrary


class RotorDefectAnalysis:
    """Cross-foil rotor-level analysis aggregating defects from all blades."""

    def __init__(self, defect_libraries: dict[int, DefectLibrary]):
        """
        Args:
            defect_libraries: mapping of foil_number -> DefectLibrary instance
        """
        self.libraries = defect_libraries

    def count_foils_by_disposition(self) -> dict[str, int]:
        """Count how many foils have each worst-case disposition.

        A foil's disposition is the most severe among its defects
        (REPLACE > BLEND > SERVICEABLE).
        """
        severity_order = {"SERVICEABLE": 0, "BLEND": 1, "REPLACE": 2}
        foil_disps: dict[str, int] = {}

        for foil_num, lib in self.libraries.items():
            worst = "SERVICEABLE"
            for defect in lib:
                disp = defect.get("disposition", "SERVICEABLE")
                if severity_order.get(disp, 0) > severity_order.get(worst, 0):
                    worst = disp
            foil_disps[worst] = foil_disps.get(worst, 0) + 1

        return foil_disps

    def detect_clustering(self, window_size: int = 3) -> list[dict]:
        """Detect clusters of adjacent foils that all have defects.

        Scans a sliding window of `window_size` consecutive foil numbers.
        Returns a list of cluster records when all foils in the window
        contain at least one defect.
        """
        foil_numbers = sorted(self.libraries.keys())
        if len(foil_numbers) < window_size:
            return []

        clusters = []
        for i in range(len(foil_numbers) - window_size + 1):
            window_foils = foil_numbers[i : i + window_size]
            all_have_defects = all(
                len(self.libraries[fn]) > 0 for fn in window_foils
            )
            if all_have_defects:
                total_defects = sum(len(self.libraries[fn]) for fn in window_foils)
                clusters.append({
                    "foils": window_foils,
                    "total_defects": total_defects,
                    "severity": "HIGH" if total_defects > window_size * 2 else "MODERATE",
                })

        return clusters

    def get_rotor_summary(self) -> dict:
        """Comprehensive summary of the rotor's defect state."""
        total_defects = sum(len(lib) for lib in self.libraries.values())
        foils_with_defects = sum(
            1 for lib in self.libraries.values() if len(lib) > 0
        )
        foils_clean = len(self.libraries) - foils_with_defects

        all_depths = []
        all_dispositions: dict[str, int] = {}
        for lib in self.libraries.values():
            for defect in lib:
                depth = defect.get("max_depth_mm", defect.get("depth_mm", 0.0))
                all_depths.append(depth)
                disp = defect.get("disposition", "SERVICEABLE")
                all_dispositions[disp] = all_dispositions.get(disp, 0) + 1

        clusters = self.detect_clustering()

        return {
            "total_foils": len(self.libraries),
            "foils_with_defects": foils_with_defects,
            "foils_clean": foils_clean,
            "total_defects": total_defects,
            "disposition_breakdown": all_dispositions,
            "foil_dispositions": self.count_foils_by_disposition(),
            "max_depth_mm": max(all_depths) if all_depths else 0.0,
            "avg_depth_mm": sum(all_depths) / len(all_depths) if all_depths else 0.0,
            "adjacent_clusters": len(clusters),
            "cluster_details": clusters,
            "overall_disposition": self.get_overall_disposition(),
        }

    def get_overall_disposition(self) -> str:
        """Determine rotor-level disposition from worst individual defect.

        Returns REPLACE if any defect requires replacement,
        BLEND if any requires blending, else SERVICEABLE.
        """
        severity_order = {"SERVICEABLE": 0, "BLEND": 1, "REPLACE": 2}
        worst = "SERVICEABLE"

        for lib in self.libraries.values():
            for defect in lib:
                disp = defect.get("disposition", "SERVICEABLE")
                if severity_order.get(disp, 0) > severity_order.get(worst, 0):
                    worst = disp
                if worst == "REPLACE":
                    return worst

        return worst
