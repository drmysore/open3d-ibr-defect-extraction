"""Hierarchical IBR defect disposition engine.

Loads defect-disposition rules from ``config/ibr_rules.json`` and evaluates
every defect against area-specific rule sets, shared count pools, merge/ignore
filters, and dimensional limit checks to produce a final disposition of
**SERVICEABLE**, **BLEND**, or **REPLACE**.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from typing import Any, Sequence

import numpy as np
from scipy.spatial.distance import cdist

logger = logging.getLogger(__name__)

MM_PER_INCH = 25.4

_DISPOSITION_RANK = {"SERVICEABLE": 0, "BLEND": 1, "REPLACE": 2}


def _worst(a: str, b: str) -> str:
    """Return the more severe of two dispositions."""
    return a if _DISPOSITION_RANK.get(a, 2) >= _DISPOSITION_RANK.get(b, 2) else b


def _get(d: dict, key: str, default=None):
    """Retrieve *key* from *d*, treating ``None`` values as *default*."""
    v = d.get(key, default)
    return default if v is None else v


class RuleEngine:
    """Evaluate IBR defect dispositions against a hierarchical rule set.

    Parameters
    ----------
    rules_path : str
        Path to ``ibr_rules.json``.  Relative paths are resolved from the
        current working directory.
    blend_multiplier : float
        Dimensional limits are multiplied by this factor to determine the
        BLEND threshold.  Defects that exceed a limit but fall within
        ``limit * blend_multiplier`` receive a BLEND disposition instead of
        REPLACE.
    """

    def __init__(
        self,
        rules_path: str = "config/ibr_rules.json",
        blend_multiplier: float = 1.5,
    ) -> None:
        rules_path = os.path.abspath(rules_path)
        if not os.path.isfile(rules_path):
            raise FileNotFoundError(f"Rules file not found: {rules_path}")
        with open(rules_path, encoding="utf-8") as fh:
            self._raw: dict[str, Any] = json.load(fh)

        self.version: str = self._raw.get("version", "unknown")
        self.program: str = self._raw.get("program", "unknown")
        self.areas: dict[str, dict] = self._raw.get("areas", {})
        self.rule_sets: list[dict] = self._raw.get("rule_sets", [])
        self.shared_pools: dict[str, dict] = self._raw.get("shared_count_pools", {})
        self.blend_multiplier = blend_multiplier

        self._area_index: dict[str, list[dict]] = defaultdict(list)
        for rs in self.rule_sets:
            for block in rs.get("rule_blocks", []):
                for rule in block.get("rules", []):
                    for area in rule.get("areas", []):
                        self._area_index[area].append(
                            {"rule_set": rs, "block": block, "rule": rule}
                        )

        logger.info(
            "RuleEngine loaded %s v%s – %d rule_sets, %d shared pools",
            self.program,
            self.version,
            len(self.rule_sets),
            len(self.shared_pools),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_defect(
        self,
        defect: dict,
        all_defects_on_foil: list[dict],
        all_defects_all_foils: list[dict],
    ) -> str:
        """Determine disposition for a single defect.

        Parameters
        ----------
        defect : dict
            The defect under evaluation.  Must contain at least ``defect_id``,
            ``classified_type``, and ``zone_ids``.
        all_defects_on_foil : list[dict]
            Every defect on the same foil (used for local counts / separation).
        all_defects_all_foils : list[dict]
            Every defect across all foils (used for global counts).

        Returns
        -------
        str
            One of ``SERVICEABLE``, ``BLEND``, or ``REPLACE``.
        """
        defect_type = _get(defect, "classified_type", "unknown")
        zone_ids: list[str] = _get(defect, "zone_ids", [])
        disposition = "SERVICEABLE"
        applied_rules: list[str] = []

        candidate_entries = self._find_matching_entries(zone_ids, defect_type)

        if not candidate_entries:
            defect["disposition"] = "SERVICEABLE"
            defect["rule_applied"] = "No matching rule — default SERVICEABLE"
            logger.debug(
                "%s: no matching rules for type=%s zones=%s",
                defect.get("defect_id"),
                defect_type,
                zone_ids,
            )
            return "SERVICEABLE"

        priority_entries = [e for e in candidate_entries if e["block"].get("priority")]
        normal_entries = [e for e in candidate_entries if not e["block"].get("priority")]
        ordered = priority_entries + normal_entries

        for entry in ordered:
            rule = entry["rule"]
            rule_id = rule.get("rule_id", "?")

            result = self._evaluate_rule(
                rule, defect, all_defects_on_foil, all_defects_all_foils
            )

            if result != "SERVICEABLE":
                applied_rules.append(f"{rule_id}→{result}")

            disposition = _worst(disposition, result)

            if disposition == "REPLACE":
                applied_rules.append(f"{rule_id}→REPLACE (terminal)")
                break

        defect["disposition"] = disposition
        defect["rule_applied"] = "; ".join(applied_rules) if applied_rules else "All rules passed"
        logger.info(
            "%s: %s  [%s]",
            defect.get("defect_id"),
            disposition,
            defect["rule_applied"],
        )
        return disposition

    def evaluate_all(
        self,
        defects_by_foil: dict[int | str, list[dict]],
    ) -> dict[int | str, list[dict]]:
        """Evaluate every defect across all foils.

        Parameters
        ----------
        defects_by_foil : dict
            Mapping of ``foil_number`` → list of defect dicts.

        Returns
        -------
        dict
            Same structure with ``disposition`` and ``rule_applied`` set on
            each defect.
        """
        all_defects: list[dict] = []
        for foil_defects in defects_by_foil.values():
            all_defects.extend(foil_defects)

        self._apply_merge_rules(all_defects)

        pool_counts = self._init_pool_counters(defects_by_foil)

        for foil_number, foil_defects in defects_by_foil.items():
            for defect in foil_defects:
                disp = self.evaluate_defect(defect, foil_defects, all_defects)
                self._update_pool_counters(pool_counts, defect, foil_number)
                pool_disp = self._check_pool_limits(
                    pool_counts, defect, foil_number, defects_by_foil
                )
                final = _worst(disp, pool_disp)
                defect["disposition"] = final
                if pool_disp != "SERVICEABLE":
                    existing = defect.get("rule_applied", "")
                    defect["rule_applied"] = (
                        f"{existing}; pool→{pool_disp}" if existing else f"pool→{pool_disp}"
                    )

        summary = self._disposition_summary(all_defects)
        logger.info(
            "evaluate_all complete – %d SERVICEABLE, %d BLEND, %d REPLACE",
            summary.get("SERVICEABLE", 0),
            summary.get("BLEND", 0),
            summary.get("REPLACE", 0),
        )
        return defects_by_foil

    def get_rules_summary(self) -> dict[str, Any]:
        """Return a simplified dict of all rules suitable for UI display.

        Returns
        -------
        dict
            Keys: ``version``, ``program``, ``areas``, ``rule_sets``
            (with nested blocks/rules trimmed to essential fields), and
            ``shared_pools``.
        """
        summary_sets = []
        for rs in self.rule_sets:
            blocks = []
            for block in rs.get("rule_blocks", []):
                rules_short = []
                for r in block.get("rules", []):
                    rules_short.append(
                        {
                            "rule_id": r.get("rule_id"),
                            "description": r.get("description"),
                            "areas": r.get("areas"),
                            "defect_types": r.get("defect_types"),
                            "max_depth_in": r.get("max_depth_in"),
                            "max_length_in": r.get("max_length_in"),
                            "local_max": r.get("local_max"),
                            "global_max": r.get("global_max"),
                            "sharp_bottom_serviceable": r.get("sharp_bottom_serviceable"),
                        }
                    )
                blocks.append(
                    {
                        "block_id": block.get("block_id"),
                        "priority": block.get("priority", False),
                        "description": block.get("description"),
                        "rules": rules_short,
                    }
                )
            summary_sets.append(
                {
                    "rule_set_id": rs.get("rule_set_id"),
                    "title": rs.get("title"),
                    "primary_area": rs.get("primary_area"),
                    "defect_types": rs.get("defect_types"),
                    "blocks": blocks,
                }
            )
        return {
            "version": self.version,
            "program": self.program,
            "areas": {
                aid: {"name": a.get("name"), "severity": a.get("severity")}
                for aid, a in self.areas.items()
            },
            "rule_sets": summary_sets,
            "shared_pools": {
                pid: {
                    "description": p.get("description"),
                    "areas": p.get("areas"),
                    "local_max": p.get("local_max"),
                    "global_max": p.get("global_max"),
                }
                for pid, p in self.shared_pools.items()
            },
        }

    # ------------------------------------------------------------------
    # Rule matching
    # ------------------------------------------------------------------

    def _find_matching_entries(
        self, zone_ids: list[str], defect_type: str
    ) -> list[dict]:
        """Return rule entries whose areas overlap *zone_ids* and whose
        ``defect_types`` include *defect_type*."""
        seen_rule_ids: set[str] = set()
        entries: list[dict] = []
        for zid in zone_ids:
            for entry in self._area_index.get(zid, []):
                rid = entry["rule"].get("rule_id")
                if rid in seen_rule_ids:
                    continue
                if defect_type in entry["rule"].get("defect_types", []):
                    entries.append(entry)
                    seen_rule_ids.add(rid)
        return entries

    # ------------------------------------------------------------------
    # Single-rule evaluation
    # ------------------------------------------------------------------

    def _evaluate_rule(
        self,
        rule: dict,
        defect: dict,
        foil_defects: list[dict],
        all_defects: list[dict],
    ) -> str:
        """Run every check encoded in *rule* against *defect*.

        Returns ``SERVICEABLE``, ``BLEND``, or ``REPLACE``.
        """
        rule_id = rule.get("rule_id", "?")

        # -- Explicit non-serviceable flag (e.g. out-of-plane deformation) --
        if rule.get("serviceable") is False:
            logger.debug("%s: rule %s — not serviceable by flag", defect.get("defect_id"), rule_id)
            return "REPLACE"

        # -- Sharp-bottom priority check --
        if not _get(rule, "sharp_bottom_serviceable", True):
            if _get(defect, "sharp_bottom", False):
                logger.debug("%s: sharp bottom → REPLACE via %s", defect.get("defect_id"), rule_id)
                return "REPLACE"

        # -- Depth check --
        max_depth = _get(rule, "max_depth_in")
        if max_depth is not None:
            depth = _get(defect, "depth_in", 0.0)
            if depth > max_depth * self.blend_multiplier:
                logger.debug(
                    "%s: depth %.4f > blend %.4f → REPLACE via %s",
                    defect.get("defect_id"), depth, max_depth * self.blend_multiplier, rule_id,
                )
                return "REPLACE"
            if depth > max_depth:
                logger.debug(
                    "%s: depth %.4f > limit %.4f → BLEND via %s",
                    defect.get("defect_id"), depth, max_depth, rule_id,
                )
                return "BLEND"

        # -- Min-depth gate (overflow rules like 3d / 4-overflow) --
        min_depth = _get(rule, "min_depth_in")
        if min_depth is not None:
            depth = _get(defect, "depth_in", 0.0)
            if depth < min_depth:
                return "SERVICEABLE"

        # -- Length check --
        max_length = _get(rule, "max_length_in")
        if max_length is not None:
            length = _get(defect, "length_in", 0.0)
            if length > max_length * self.blend_multiplier:
                logger.debug(
                    "%s: length %.4f > blend %.4f → REPLACE via %s",
                    defect.get("defect_id"), length, max_length * self.blend_multiplier, rule_id,
                )
                return "REPLACE"
            if length > max_length:
                logger.debug(
                    "%s: length %.4f > limit %.4f → BLEND via %s",
                    defect.get("defect_id"), length, max_length, rule_id,
                )
                return "BLEND"

        # -- Combined depth+length (abradable buildup) --
        max_combined = _get(rule, "max_combined_depth_length_in")
        if max_combined is not None:
            combined = _get(defect, "depth_in", 0.0) + _get(defect, "length_in", 0.0)
            if combined > max_combined:
                return "REPLACE"

        # -- Width check --
        max_width = _get(rule, "max_width_in")
        if max_width is not None:
            width = _get(defect, "width_in", 0.0)
            if width > max_width:
                return "REPLACE"

        # -- Cannot-cross check (scratches crossing edge boundaries) --
        if _get(rule, "cannot_cross", False):
            if _get(defect, "crosses_edge", False):
                logger.debug(
                    "%s: crosses edge → REPLACE via %s", defect.get("defect_id"), rule_id,
                )
                return "REPLACE"

        # -- Tip proximity check --
        max_from_tip = _get(rule, "max_from_tip_spanwise_in")
        if max_from_tip is not None:
            tip_dist = _get(defect, "tip_distance_spanwise_in")
            if tip_dist is not None and tip_dist > max_from_tip:
                return "SERVICEABLE"

        rule_areas = set(rule.get("areas", []))
        rule_types = set(rule.get("defect_types", []))

        # -- Filter peer defects (same area+type on this foil) --
        peers = self._filter_peers(
            defect, foil_defects, rule_areas, rule_types, rule
        )

        # -- Local count check --
        local_max = _get(rule, "local_max")
        if local_max is not None:
            count = len(peers) + 1
            if count > local_max:
                logger.debug(
                    "%s: local count %d > %d → REPLACE via %s",
                    defect.get("defect_id"), count, local_max, rule_id,
                )
                return "REPLACE"

        # -- Local per-pair count (e.g. 2 per adjacent-area pair) --
        local_max_pair = _get(rule, "local_max_per_pair")
        if local_max_pair is not None:
            if self._pair_count_exceeded(defect, peers, rule_areas, local_max_pair):
                logger.debug(
                    "%s: pair count exceeded → REPLACE via %s",
                    defect.get("defect_id"), rule_id,
                )
                return "REPLACE"

        # -- Global count check --
        global_max = _get(rule, "global_max")
        if global_max is not None:
            n_airfoils = _get(rule, "global_check_airfoils", 10)
            global_peers = self._filter_peers(
                defect, all_defects, rule_areas, rule_types, rule
            )
            foils_seen = {_get(d, "foil_number") for d in global_peers}
            foils_seen.add(_get(defect, "foil_number"))
            effective_count = len(global_peers) + 1
            if effective_count > global_max:
                logger.debug(
                    "%s: global count %d > %d → REPLACE via %s",
                    defect.get("defect_id"), effective_count, global_max, rule_id,
                )
                return "REPLACE"
            if _get(rule, "max_affected_airfoils") is not None:
                if len(foils_seen) > rule["max_affected_airfoils"]:
                    return "REPLACE"

        # -- Separation check --
        result = self._check_separation(defect, peers, rule)
        if result != "SERVICEABLE":
            logger.debug(
                "%s: separation fail → %s via %s",
                defect.get("defect_id"), result, rule_id,
            )
            return result

        return "SERVICEABLE"

    # ------------------------------------------------------------------
    # Peer filtering & ignore logic
    # ------------------------------------------------------------------

    def _filter_peers(
        self,
        defect: dict,
        population: list[dict],
        rule_areas: set[str],
        rule_types: set[str],
        rule: dict,
    ) -> list[dict]:
        """Return defects from *population* that match the rule's area+type
        constraints, excluding *defect* itself.

        Applies ``ignore_if_round_bottom_below`` filtering when specified.
        """
        defect_id = defect.get("defect_id")
        ignore_threshold = _get(rule, "ignore_if_round_bottom_below")
        min_depth_gate = _get(rule, "min_depth_in")

        peers: list[dict] = []
        for d in population:
            if d.get("defect_id") == defect_id:
                continue
            if _get(d, "classified_type", "unknown") not in rule_types:
                continue
            d_zones = set(_get(d, "zone_ids", []))
            if not d_zones.intersection(rule_areas):
                continue
            if min_depth_gate is not None:
                if _get(d, "depth_in", 0.0) < min_depth_gate:
                    continue
            if ignore_threshold is not None:
                if _get(d, "round_bottom", False) and _get(d, "depth_in", 0.0) <= ignore_threshold:
                    continue
            peers.append(d)
        return peers

    def _pair_count_exceeded(
        self,
        defect: dict,
        peers: list[dict],
        rule_areas: set[str],
        max_per_pair: int,
    ) -> bool:
        """Check whether any pair of adjacent areas exceeds *max_per_pair*."""
        sorted_areas = sorted(rule_areas)
        for i, a1 in enumerate(sorted_areas):
            for a2 in sorted_areas[i + 1:]:
                pair = {a1, a2}
                count = 0
                d_zones = set(_get(defect, "zone_ids", []))
                if d_zones.intersection(pair):
                    count += 1
                for p in peers:
                    p_zones = set(_get(p, "zone_ids", []))
                    if p_zones.intersection(pair):
                        count += 1
                if count > max_per_pair:
                    return True
        return False

    # ------------------------------------------------------------------
    # Separation logic
    # ------------------------------------------------------------------

    def _check_separation(
        self, defect: dict, peers: list[dict], rule: dict
    ) -> str:
        """Verify minimum separation between *defect* and its *peers*.

        The ``min_separation_in`` field may be a float, the string
        ``"deepest_flaw"``, or ``"deepest_flaw_or_0.250"`` (whichever is
        greater).  Returns ``SERVICEABLE`` when the check passes.
        """
        raw_sep = _get(rule, "min_separation_in")
        if raw_sep is None or not peers:
            return "SERVICEABLE"

        min_sep = self._resolve_separation(raw_sep, defect, peers)
        if min_sep is None or min_sep <= 0:
            return "SERVICEABLE"

        nearest = self._nearest_distance_in(defect, peers)
        if nearest is None:
            return "SERVICEABLE"

        if nearest < min_sep:
            return "REPLACE"
        return "SERVICEABLE"

    def _resolve_separation(
        self, raw: Any, defect: dict, peers: list[dict]
    ) -> float | None:
        """Translate a separation spec into a numeric threshold (inches)."""
        if isinstance(raw, (int, float)):
            return float(raw)

        if isinstance(raw, str):
            depths = [_get(d, "depth_in", 0.0) for d in peers]
            depths.append(_get(defect, "depth_in", 0.0))
            deepest = max(depths) if depths else 0.0

            if raw == "deepest_flaw":
                return deepest
            if raw == "deepest_flaw_or_0.250":
                return max(deepest, 0.250)

        return None

    @staticmethod
    def _nearest_distance_in(defect: dict, peers: list[dict]) -> float | None:
        """Compute the nearest Euclidean distance (in inches) between
        *defect* and any peer using their ``centroid_mm`` fields."""
        c = _get(defect, "centroid_mm")
        if c is None:
            return None

        peer_centroids = [_get(p, "centroid_mm") for p in peers]
        peer_centroids = [pc for pc in peer_centroids if pc is not None]
        if not peer_centroids:
            return None

        ref = np.asarray(c, dtype=float).reshape(1, -1)
        pts = np.asarray(peer_centroids, dtype=float)
        if pts.ndim == 1:
            pts = pts.reshape(1, -1)
        dists = cdist(ref, pts).ravel()
        return float(np.min(dists)) / MM_PER_INCH

    # ------------------------------------------------------------------
    # Merge logic (scratch aggregation)
    # ------------------------------------------------------------------

    def _apply_merge_rules(self, all_defects: list[dict]) -> None:
        """Pre-pass: merge scratches that are closer than the configured
        separation threshold by summing their lengths into the surviving
        defect and marking the others as merged.

        Merged defects receive ``_merged_into`` pointing to the surviving id.
        """
        merge_entries: list[dict] = []
        for rs in self.rule_sets:
            for block in rs.get("rule_blocks", []):
                if not block.get("priority"):
                    continue
                for rule in block.get("rules", []):
                    thresh = _get(rule, "merge_if_separation_below")
                    if thresh is not None:
                        merge_entries.append(rule)

        if not merge_entries:
            return

        for rule in merge_entries:
            thresh = rule["merge_if_separation_below"]
            rule_areas = set(rule.get("areas", []))
            rule_types = set(rule.get("defect_types", []))
            self._merge_nearby(all_defects, rule_areas, rule_types, thresh)

    def _merge_nearby(
        self,
        defects: list[dict],
        areas: set[str],
        types: set[str],
        threshold_in: float,
    ) -> None:
        """Union-find style merge of defects within *threshold_in* inches."""
        candidates = []
        for d in defects:
            if d.get("_merged_into"):
                continue
            if _get(d, "classified_type", "unknown") not in types:
                continue
            d_zones = set(_get(d, "zone_ids", []))
            if not d_zones.intersection(areas):
                continue
            if _get(d, "centroid_mm") is None:
                continue
            candidates.append(d)

        if len(candidates) < 2:
            return

        centroids = np.array([d["centroid_mm"] for d in candidates], dtype=float)
        dists_mm = cdist(centroids, centroids)
        dists_in = dists_mm / MM_PER_INCH

        parent = list(range(len(candidates)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                if _get(candidates[i], "foil_number") != _get(candidates[j], "foil_number"):
                    continue
                if dists_in[i, j] < threshold_in:
                    union(i, j)

        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(len(candidates)):
            groups[find(i)].append(i)

        for root, members in groups.items():
            if len(members) <= 1:
                continue
            survivor = candidates[root]
            total_length = _get(survivor, "length_in", 0.0)
            max_depth = _get(survivor, "depth_in", 0.0)
            for idx in members:
                if idx == root:
                    continue
                merged = candidates[idx]
                total_length += _get(merged, "length_in", 0.0)
                max_depth = max(max_depth, _get(merged, "depth_in", 0.0))
                merged["_merged_into"] = survivor.get("defect_id")
                merged["disposition"] = "MERGED"
                merged["rule_applied"] = f"Merged into {survivor.get('defect_id')}"
            survivor["length_in"] = total_length
            survivor["depth_in"] = max_depth
            survivor["_merge_count"] = len(members)
            logger.info(
                "Merged %d defects into %s (length=%.4f in, depth=%.4f in)",
                len(members),
                survivor.get("defect_id"),
                total_length,
                max_depth,
            )

    # ------------------------------------------------------------------
    # Shared count pools
    # ------------------------------------------------------------------

    def _init_pool_counters(
        self, defects_by_foil: dict[int | str, list[dict]]
    ) -> dict[str, dict]:
        """Initialize per-pool tracking structures."""
        counters: dict[str, dict] = {}
        for pool_id, pool in self.shared_pools.items():
            counters[pool_id] = {
                "local": defaultdict(int),
                "global": 0,
                "foils_seen": set(),
                "pool": pool,
            }
        return counters

    def _update_pool_counters(
        self,
        counters: dict[str, dict],
        defect: dict,
        foil_number: int | str,
    ) -> None:
        """Increment pool counters when *defect* matches a shared pool."""
        if defect.get("_merged_into"):
            return
        if _get(defect, "disposition") == "MERGED":
            return

        defect_type = _get(defect, "classified_type", "unknown")
        zones = set(_get(defect, "zone_ids", []))
        depth = _get(defect, "depth_in", 0.0)

        for pool_id, state in counters.items():
            pool = state["pool"]
            pool_areas = set(pool.get("areas", []))
            if not zones.intersection(pool_areas):
                continue

            referenced_rules = pool.get("referenced_by", [])
            pool_types = self._types_for_rules(referenced_rules)
            if defect_type not in pool_types:
                continue

            min_trigger = _get(pool, "min_depth_trigger_in")
            if min_trigger is not None and depth < min_trigger:
                continue

            max_pool_depth = _get(pool, "max_depth_in")
            if max_pool_depth is not None and depth > max_pool_depth:
                continue

            if not _get(pool, "sharp_bottom_serviceable", True):
                if _get(defect, "sharp_bottom", False):
                    continue

            state["local"][foil_number] += 1
            state["global"] += 1
            state["foils_seen"].add(foil_number)

    def _check_pool_limits(
        self,
        counters: dict[str, dict],
        defect: dict,
        foil_number: int | str,
        defects_by_foil: dict[int | str, list[dict]],
    ) -> str:
        """Return the worst disposition from any pool the defect participates
        in whose limits are exceeded."""
        disposition = "SERVICEABLE"
        zones = set(_get(defect, "zone_ids", []))
        defect_type = _get(defect, "classified_type", "unknown")

        for pool_id, state in counters.items():
            pool = state["pool"]
            pool_areas = set(pool.get("areas", []))
            if not zones.intersection(pool_areas):
                continue
            pool_types = self._types_for_rules(pool.get("referenced_by", []))
            if defect_type not in pool_types:
                continue

            local_max = _get(pool, "local_max")
            if local_max is not None and state["local"][foil_number] > local_max:
                disposition = _worst(disposition, "REPLACE")
                logger.debug(
                    "%s: pool %s local %d > %d",
                    defect.get("defect_id"), pool_id,
                    state["local"][foil_number], local_max,
                )

            global_max = _get(pool, "global_max")
            if global_max is not None and state["global"] > global_max:
                disposition = _worst(disposition, "REPLACE")
                logger.debug(
                    "%s: pool %s global %d > %d",
                    defect.get("defect_id"), pool_id,
                    state["global"], global_max,
                )

        return disposition

    def _types_for_rules(self, rule_ids: list[str]) -> set[str]:
        """Collect defect_types from specific rule IDs."""
        types: set[str] = set()
        for rs in self.rule_sets:
            for block in rs.get("rule_blocks", []):
                for rule in block.get("rules", []):
                    if rule.get("rule_id") in rule_ids:
                        types.update(rule.get("defect_types", []))
        return types

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _disposition_summary(defects: list[dict]) -> dict[str, int]:
        summary: dict[str, int] = defaultdict(int)
        for d in defects:
            summary[d.get("disposition", "UNKNOWN")] += 1
        return dict(summary)

    # ------------------------------------------------------------------
    # LLM logic-block evaluation
    # ------------------------------------------------------------------

    _CONDITION_PATTERNS: list[tuple[str, str]] = [
        (r"damage\s+contacting\s+(.*?)(?:\s*\(|$)", "location"),
        (r"extending\s+into\s+(.*?)\)", "extent"),
        (r"depth\s*(?:greater|more|>)\s*(?:than\s+)?([\d.]+)", "min_depth"),
        (r"depth\s*(?:less|fewer|<)\s*(?:than\s+)?([\d.]+)", "max_depth"),
        (r"sharp[\s_-]*bottom", "sharp_bottom"),
        (r"round[\s_-]*bottom", "round_bottom"),
        (r"crosses?\s+(?:the\s+)?edge", "crosses_edge"),
    ]

    def evaluate_logic_block(self, defect: dict, rule: dict) -> str:
        """Process a Llama3-emitted ``logic`` block against *defect*.

        The *rule* dict is expected to contain a ``logic`` key shaped as::

            {
                "if_condition": "<natural-language predicate>",
                "then": "<action or limit description>",
                "else": "<action or '-1' for not-applicable>"
            }

        Returns ``SERVICEABLE``, ``BLEND``, or ``REPLACE``.
        """
        logic = rule.get("logic")
        if logic is None:
            return "SERVICEABLE"

        condition_text = str(logic.get("if_condition", "")).lower()
        then_text = str(logic.get("then", "")).lower()
        else_text = str(logic.get("else", "")).lower()

        condition_met = self._evaluate_condition(defect, condition_text)

        branch = then_text if condition_met else else_text

        if branch in ("-1", "n/a", "not applicable", ""):
            return "SERVICEABLE"

        return self._interpret_branch(defect, branch)

    def _evaluate_condition(self, defect: dict, condition: str) -> bool:
        """Parse natural-language *condition* and test it against *defect*."""
        props: dict[str, Any] = {}
        for pattern, key in self._CONDITION_PATTERNS:
            m = re.search(pattern, condition, re.IGNORECASE)
            if m:
                props[key] = m.group(1).strip() if m.lastindex else True

        if "location" in props:
            defect_loc = str(_get(defect, "location", "")).lower()
            if props["location"].lower() not in defect_loc:
                return False

        if "extent" in props:
            extent_desc = props["extent"].lower()
            defect_extent = str(_get(defect, "extent", "")).lower()
            for keyword in ("concave", "convex", "both"):
                if keyword in extent_desc and keyword not in defect_extent:
                    return False

        if "min_depth" in props:
            if _get(defect, "depth_in", 0.0) <= float(props["min_depth"]):
                return False

        if "max_depth" in props:
            if _get(defect, "depth_in", 0.0) >= float(props["max_depth"]):
                return False

        if "sharp_bottom" in props:
            if not _get(defect, "sharp_bottom", False):
                return False

        if "round_bottom" in props:
            if not _get(defect, "round_bottom", False):
                return False

        if "crosses_edge" in props:
            if not _get(defect, "crosses_edge", False):
                return False

        return True

    @staticmethod
    def _interpret_branch(defect: dict, branch: str) -> str:
        """Derive a disposition from a ``then``/``else`` branch string."""
        if "replace" in branch:
            return "REPLACE"
        if "blend" in branch:
            return "BLEND"

        limit_match = re.search(r"([\d.]+)\s*(?:inch|in\.?|\")", branch)
        if limit_match:
            limit_val = float(limit_match.group(1))
            check_match = re.search(
                r"(?:maximum|max|limit)\s+(\w+)", branch
            )
            if check_match:
                dim_name = check_match.group(1).lower()
                dim_keys = {
                    "depth": "depth_in",
                    "length": "length_in",
                    "width": "width_in",
                }
                key = dim_keys.get(dim_name, "depth_in")
            else:
                key = "depth_in"

            actual = _get(defect, key, 0.0)
            if actual > limit_val:
                return "REPLACE"
            return "SERVICEABLE"

        if "serviceable" in branch or "acceptable" in branch:
            return "SERVICEABLE"

        return "SERVICEABLE"

    # ------------------------------------------------------------------
    # Multi-rule chain evaluation
    # ------------------------------------------------------------------

    def evaluate_chain(self, defect: dict, rule_blocks: list[dict]) -> str:
        """Evaluate a sequence of rule blocks in priority order.

        Priority blocks (those with ``"priority": true`` or containing
        ``sharp_bottom`` / ``cannot_cross`` keys) are evaluated first.
        If any priority rule triggers REPLACE, evaluation short-circuits.
        Remaining blocks are processed sequentially and the worst
        disposition across all blocks is returned.

        Parameters
        ----------
        defect : dict
            The defect under evaluation.
        rule_blocks : list[dict]
            Rule blocks, each containing ``rules`` and optional ``priority``.

        Returns
        -------
        str
            ``SERVICEABLE``, ``BLEND``, or ``REPLACE``.
        """
        priority_blocks: list[dict] = []
        normal_blocks: list[dict] = []

        for block in rule_blocks:
            is_priority = block.get("priority", False)
            if not is_priority:
                for r in block.get("rules", []):
                    if r.get("sharp_bottom_serviceable") is not None or r.get("cannot_cross"):
                        is_priority = True
                        break
            (priority_blocks if is_priority else normal_blocks).append(block)

        disposition = "SERVICEABLE"

        for block in priority_blocks:
            for rule in block.get("rules", []):
                result = self._evaluate_chain_rule(defect, rule)
                if result == "REPLACE":
                    logger.debug(
                        "%s: priority rule %s → REPLACE (chain short-circuit)",
                        defect.get("defect_id"),
                        rule.get("rule_id", "?"),
                    )
                    return "REPLACE"
                disposition = _worst(disposition, result)

        for block in normal_blocks:
            for rule in block.get("rules", []):
                result = self._evaluate_chain_rule(defect, rule)
                disposition = _worst(disposition, result)
                if disposition == "REPLACE":
                    return "REPLACE"

        return disposition

    def _evaluate_chain_rule(self, defect: dict, rule: dict) -> str:
        """Evaluate a single rule within a chain context.

        Handles both traditional limit-based rules and LLM ``logic`` blocks.
        """
        if rule.get("logic"):
            return self.evaluate_logic_block(defect, rule)

        if not _get(rule, "sharp_bottom_serviceable", True):
            if _get(defect, "sharp_bottom", False):
                return "REPLACE"

        if _get(rule, "cannot_cross", False):
            if _get(defect, "crosses_edge", False):
                return "REPLACE"

        max_depth = _get(rule, "max_depth_in")
        if max_depth is not None:
            depth = _get(defect, "depth_in", 0.0)
            if depth > max_depth * self.blend_multiplier:
                return "REPLACE"
            if depth > max_depth:
                return "BLEND"

        max_length = _get(rule, "max_length_in")
        if max_length is not None:
            length = _get(defect, "length_in", 0.0)
            if length > max_length * self.blend_multiplier:
                return "REPLACE"
            if length > max_length:
                return "BLEND"

        if rule.get("serviceable") is False:
            return "REPLACE"

        return "SERVICEABLE"

    # ------------------------------------------------------------------
    # Separation distance computation
    # ------------------------------------------------------------------

    def compute_separation_distance(
        self, defect: dict, peers: list[dict]
    ) -> float | None:
        """Compute the nearest Euclidean distance between *defect* and *peers*.

        Supports dynamic thresholds such as
        ``"more than depth of deepest flaw present"`` when used downstream.

        Parameters
        ----------
        defect : dict
            Must contain ``centroid_mm`` (list/tuple of coordinates).
        peers : list[dict]
            Peer defects, each with ``centroid_mm``.

        Returns
        -------
        float or None
            Nearest distance in **inches**, or ``None`` if centroids are
            missing.
        """
        c = _get(defect, "centroid_mm")
        if c is None:
            return None

        valid_peers = [p for p in peers if _get(p, "centroid_mm") is not None]
        if not valid_peers:
            return None

        ref = np.asarray(c, dtype=float).reshape(1, -1)
        pts = np.asarray(
            [p["centroid_mm"] for p in valid_peers], dtype=float
        )
        if pts.ndim == 1:
            pts = pts.reshape(1, -1)

        dists_in = cdist(ref, pts).ravel() / MM_PER_INCH
        return float(np.min(dists_in))

    def resolve_dynamic_threshold(
        self, spec: str | float, defect: dict, peers: list[dict]
    ) -> float | None:
        """Resolve a separation threshold specification.

        Parameters
        ----------
        spec : str or float
            A numeric value (e.g. ``0.250``) or a dynamic rule string like
            ``"more than depth of deepest flaw present"``.
        defect : dict
            The defect under evaluation.
        peers : list[dict]
            Peer defects.

        Returns
        -------
        float or None
            Resolved threshold in inches.
        """
        if isinstance(spec, (int, float)):
            return float(spec)

        if isinstance(spec, str):
            depths = [_get(d, "depth_in", 0.0) for d in peers]
            depths.append(_get(defect, "depth_in", 0.0))
            deepest = max(depths) if depths else 0.0

            lowered = spec.lower()
            if "deepest" in lowered or "deepest flaw" in lowered:
                fixed_match = re.search(r"([\d.]+)", spec)
                if fixed_match:
                    return max(deepest, float(fixed_match.group(1)))
                return deepest

            numeric = re.search(r"([\d.]+)", spec)
            if numeric:
                return float(numeric.group(1))

        return None

    # ------------------------------------------------------------------
    # Scratch merge (public API)
    # ------------------------------------------------------------------

    def merge_scratches(self, defects: list[dict]) -> list[dict]:
        """Merge nearby scratches per IBR rules.

        Implements: *"For scratches more than 0.001 inch depth that are
        separated by less than 0.015 inch, consider as single scratch by
        adding their lengths."*

        Uses union-find to cluster qualifying scratches, sums their lengths
        into the group representative, and marks the rest as merged.

        Parameters
        ----------
        defects : list[dict]
            Full defect list (modified in place; merged entries receive
            ``_merged_into`` and ``disposition = "MERGED"``).

        Returns
        -------
        list[dict]
            The surviving (non-merged) defects.
        """
        DEPTH_GATE = 0.001
        SEP_THRESHOLD = 0.015

        scratches = [
            d for d in defects
            if _get(d, "classified_type", "").lower() in ("scratch", "scratches")
            and _get(d, "depth_in", 0.0) > DEPTH_GATE
            and _get(d, "centroid_mm") is not None
            and not d.get("_merged_into")
        ]

        if len(scratches) < 2:
            return [d for d in defects if not d.get("_merged_into")]

        centroids = np.array(
            [d["centroid_mm"] for d in scratches], dtype=float
        )
        dists_in = cdist(centroids, centroids) / MM_PER_INCH

        parent = list(range(len(scratches)))

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(a: int, b: int) -> None:
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(len(scratches)):
            for j in range(i + 1, len(scratches)):
                if _get(scratches[i], "foil_number") != _get(scratches[j], "foil_number"):
                    continue
                if dists_in[i, j] < SEP_THRESHOLD:
                    _union(i, j)

        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(len(scratches)):
            groups[_find(i)].append(i)

        for root, members in groups.items():
            if len(members) <= 1:
                continue
            survivor = scratches[root]
            total_length = _get(survivor, "length_in", 0.0)
            max_depth = _get(survivor, "depth_in", 0.0)
            for idx in members:
                if idx == root:
                    continue
                merged = scratches[idx]
                total_length += _get(merged, "length_in", 0.0)
                max_depth = max(max_depth, _get(merged, "depth_in", 0.0))
                merged["_merged_into"] = survivor.get("defect_id")
                merged["disposition"] = "MERGED"
                merged["rule_applied"] = (
                    f"Scratch merge into {survivor.get('defect_id')}"
                )
            survivor["length_in"] = total_length
            survivor["depth_in"] = max_depth
            survivor["_merge_count"] = len(members)
            logger.info(
                "merge_scratches: merged %d scratches into %s "
                "(length=%.4f in, depth=%.4f in)",
                len(members),
                survivor.get("defect_id"),
                total_length,
                max_depth,
            )

        return [d for d in defects if not d.get("_merged_into")]

    # ------------------------------------------------------------------
    # Visual separation check
    # ------------------------------------------------------------------

    @staticmethod
    def check_visual_separation(
        defects: list[dict], min_threshold_mm: float = 1.0,
    ) -> bool:
        """Check whether *defects* are visually separated.

        Implements the rule: *"separation limit does not apply as long as
        defects are visually separated."*  Defects are considered visually
        separated when every pair has distinct centroids farther apart than
        *min_threshold_mm* millimetres.

        Parameters
        ----------
        defects : list[dict]
            Defects to check, each with ``centroid_mm``.
        min_threshold_mm : float
            Minimum distance in mm to consider two defects visually distinct.

        Returns
        -------
        bool
            ``True`` if all defect pairs are visually separated.
        """
        centroids = [
            _get(d, "centroid_mm")
            for d in defects
            if _get(d, "centroid_mm") is not None
        ]
        if len(centroids) < 2:
            return True

        pts = np.asarray(centroids, dtype=float)
        if pts.ndim == 1:
            pts = pts.reshape(1, -1)
        dists = cdist(pts, pts)

        n = len(centroids)
        for i in range(n):
            for j in range(i + 1, n):
                if dists[i, j] < min_threshold_mm:
                    return False
        return True

    # ------------------------------------------------------------------
    # Evaluation trace (public API)
    # ------------------------------------------------------------------

    def get_evaluation_trace(self, defect: dict) -> list[dict]:
        """Return a step-by-step trace of how *defect* was (or would be)
        evaluated.

        Each entry in the returned list is a dict with:

        - ``step``       – 1-based ordinal
        - ``rule_id``    – the rule that was checked
        - ``block_id``   – parent block id
        - ``check``      – human-readable description of the check
        - ``result``     – ``"PASS"`` or ``"FAIL"``
        - ``disposition``– disposition produced by this rule
        - ``cumulative`` – running worst disposition up to this step

        The last entry always carries the final disposition.

        Parameters
        ----------
        defect : dict
            Must contain at least ``classified_type`` and ``zone_ids``.

        Returns
        -------
        list[dict]
            Ordered trace entries.
        """
        defect_type = _get(defect, "classified_type", "unknown")
        zone_ids: list[str] = _get(defect, "zone_ids", [])
        entries = self._find_matching_entries(zone_ids, defect_type)

        if not entries:
            return [
                {
                    "step": 1,
                    "rule_id": None,
                    "block_id": None,
                    "check": "No matching rules for type/zone",
                    "result": "PASS",
                    "disposition": "SERVICEABLE",
                    "cumulative": "SERVICEABLE",
                }
            ]

        priority_entries = [e for e in entries if e["block"].get("priority")]
        normal_entries = [e for e in entries if not e["block"].get("priority")]
        ordered = priority_entries + normal_entries

        trace: list[dict] = []
        cumulative = "SERVICEABLE"

        for step_num, entry in enumerate(ordered, start=1):
            rule = entry["rule"]
            block = entry["block"]
            rule_id = rule.get("rule_id", "?")
            block_id = block.get("block_id", "?")

            checks_performed: list[str] = []
            step_disposition = "SERVICEABLE"

            if rule.get("serviceable") is False:
                checks_performed.append("serviceable=false flag")
                step_disposition = "REPLACE"

            elif not _get(rule, "sharp_bottom_serviceable", True):
                checks_performed.append("sharp_bottom check")
                if _get(defect, "sharp_bottom", False):
                    step_disposition = "REPLACE"

            if step_disposition == "SERVICEABLE":
                max_depth = _get(rule, "max_depth_in")
                if max_depth is not None:
                    depth = _get(defect, "depth_in", 0.0)
                    checks_performed.append(
                        f"depth {depth:.4f} vs limit {max_depth:.4f}"
                    )
                    if depth > max_depth * self.blend_multiplier:
                        step_disposition = "REPLACE"
                    elif depth > max_depth:
                        step_disposition = "BLEND"

            if step_disposition == "SERVICEABLE":
                max_length = _get(rule, "max_length_in")
                if max_length is not None:
                    length = _get(defect, "length_in", 0.0)
                    checks_performed.append(
                        f"length {length:.4f} vs limit {max_length:.4f}"
                    )
                    if length > max_length * self.blend_multiplier:
                        step_disposition = "REPLACE"
                    elif length > max_length:
                        step_disposition = "BLEND"

            if step_disposition == "SERVICEABLE" and _get(rule, "cannot_cross", False):
                checks_performed.append("cannot_cross edge check")
                if _get(defect, "crosses_edge", False):
                    step_disposition = "REPLACE"

            if step_disposition == "SERVICEABLE" and rule.get("logic"):
                checks_performed.append("LLM logic block evaluation")
                step_disposition = self.evaluate_logic_block(defect, rule)

            if not checks_performed:
                checks_performed.append("all dimensional checks passed")

            result = "FAIL" if step_disposition != "SERVICEABLE" else "PASS"
            cumulative = _worst(cumulative, step_disposition)

            trace.append(
                {
                    "step": step_num,
                    "rule_id": rule_id,
                    "block_id": block_id,
                    "check": "; ".join(checks_performed),
                    "result": result,
                    "disposition": step_disposition,
                    "cumulative": cumulative,
                }
            )

            if cumulative == "REPLACE":
                break

        return trace
