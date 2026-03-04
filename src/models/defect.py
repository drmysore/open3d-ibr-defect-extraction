from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum
import numpy as np


class DefectType(Enum):
    NICK = "nick"
    DENT = "dent"
    CRACK = "crack"
    FOD = "FOD"
    EROSION = "erosion"
    SCRATCH = "scratch"
    GOUGE = "gouge"


class Disposition(Enum):
    SERVICEABLE = "SERVICEABLE"
    BLEND = "BLEND"
    REPLACE = "REPLACE"


@dataclass
class Defect:
    defect_id: str
    foil_number: int
    points: np.ndarray
    deviations: np.ndarray
    centroid: np.ndarray
    max_depth: float
    point_count: int

    depth_mm: float = 0.0
    depth_inches: float = 0.0
    width_mm: float = 0.0
    width_inches: float = 0.0
    length_mm: float = 0.0
    length_inches: float = 0.0
    measurement_method: str = ""

    is_edge_defect: bool = False
    nearest_edge: str = ""
    edge_distance_mm: float = 0.0

    zones: list = field(default_factory=list)
    applied_zone: str = ""
    applied_limits: dict = field(default_factory=dict)
    disposition: str = ""

    defect_type: Optional[DefectType] = None
    type_confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "defect_id": self.defect_id,
            "foil_number": self.foil_number,
            "centroid_mm": self.centroid.tolist() if isinstance(self.centroid, np.ndarray) else self.centroid,
            "max_depth_mm": self.max_depth,
            "point_count": self.point_count,
            "depth_mm": self.depth_mm,
            "depth_inches": self.depth_inches,
            "width_mm": self.width_mm,
            "width_inches": self.width_inches,
            "length_mm": self.length_mm,
            "length_inches": self.length_inches,
            "measurement_method": self.measurement_method,
            "is_edge_defect": self.is_edge_defect,
            "nearest_edge": self.nearest_edge,
            "edge_distance_mm": self.edge_distance_mm,
            "zones": [z["id"] if isinstance(z, dict) else z for z in self.zones],
            "applied_zone": self.applied_zone,
            "disposition": self.disposition,
            "defect_type": self.defect_type.value if self.defect_type else None,
            "type_confidence": self.type_confidence,
        }
