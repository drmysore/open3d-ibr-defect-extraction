import json
from typing import Dict, Optional

ROTOR_CONFIGURATIONS = {
    "4137321": {"stage": 1, "blade_count": 20, "name": "Stage 1 Rotor Assy"},
    "4135411": {"stage": 1, "blade_count": 20, "name": "Stage 1 Rotor Assy"},
    "4134621": {"stage": 1, "blade_count": 20, "name": "Stage 1 Rotor"},
    "4130812": {"stage": 2, "blade_count": 38, "name": "Stage 2 Rotor"},
    "4134613": {"stage": 3, "blade_count": 55, "name": "Stage 3 Rotor"},
    "4130813": {"stage": 3, "blade_count": 55, "name": "Stage 3 Rotor"},
    "4119904": {"stage": 4, "blade_count": 42, "name": "Stage 4 Rotor"},
    "4119905": {"stage": 5, "blade_count": 54, "name": "Stage 5 Rotor"},
    "4133006": {"stage": 6, "blade_count": 70, "name": "Stage 6 Rotor"},
    "4136007": {"stage": 7, "blade_count": 82, "name": "Stage 7 Rotor"},
    "4133008": {"stage": 8, "blade_count": 96, "name": "Stage 8 Rotor"},
    "4131129-01": {"stage": 9, "blade_count": 110, "name": "Stage 9 Rotor Assy"},
}

BLADE_GEOMETRY = {
    3: {"span_mm": 165.07, "chord_mm": 79.1, "z_min_mm": 0.0, "z_max_mm": 165.07},
    1: {"span_mm": 120.0, "chord_mm": 65.0, "z_min_mm": 0.0, "z_max_mm": 120.0},
    2: {"span_mm": 140.0, "chord_mm": 72.0, "z_min_mm": 0.0, "z_max_mm": 140.0},
    4: {"span_mm": 150.0, "chord_mm": 75.0, "z_min_mm": 0.0, "z_max_mm": 150.0},
    5: {"span_mm": 145.0, "chord_mm": 73.0, "z_min_mm": 0.0, "z_max_mm": 145.0},
    6: {"span_mm": 135.0, "chord_mm": 68.0, "z_min_mm": 0.0, "z_max_mm": 135.0},
    7: {"span_mm": 125.0, "chord_mm": 64.0, "z_min_mm": 0.0, "z_max_mm": 125.0},
    8: {"span_mm": 115.0, "chord_mm": 60.0, "z_min_mm": 0.0, "z_max_mm": 115.0},
    9: {"span_mm": 105.0, "chord_mm": 56.0, "z_min_mm": 0.0, "z_max_mm": 105.0},
}


def get_blade_count(part_number: str) -> int:
    config = ROTOR_CONFIGURATIONS.get(part_number)
    if config is None:
        raise ValueError(f"Unknown part number: {part_number}")
    return config["blade_count"]


def get_stage(part_number: str) -> int:
    config = ROTOR_CONFIGURATIONS.get(part_number)
    if config is None:
        raise ValueError(f"Unknown part number: {part_number}")
    return config["stage"]


def get_blade_geometry(part_number: str) -> dict:
    stage = get_stage(part_number)
    return BLADE_GEOMETRY.get(stage, BLADE_GEOMETRY[3])


def load_rotor_configs_from_json(path: str) -> list:
    with open(path) as f:
        return json.load(f)
