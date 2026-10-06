from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import InputValidationError


REQUIRED_SCHEMA_VERSION = "1.0"


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputValidationError(f"configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise InputValidationError(f"invalid JSON configuration: {exc}") from exc
    validate_config(data)
    return data


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise InputValidationError("configuration root must be an object")
    if config.get("schema_version") != REQUIRED_SCHEMA_VERSION:
        raise InputValidationError(f"schema_version must be {REQUIRED_SCHEMA_VERSION}")
    for section in ("basin", "rainfall", "runoff", "unit_hydrograph"):
        if not isinstance(config.get(section), dict):
            raise InputValidationError(f"missing configuration section: {section}")

    rainfall = config["rainfall"]
    values = rainfall.get("rainfall_mm")
    if not isinstance(values, list) or not values:
        raise InputValidationError("rainfall.rainfall_mm must be a non-empty list")
    if rainfall.get("time_step_h", 0) <= 0:
        raise InputValidationError("rainfall.time_step_h must be positive")
    if any(not isinstance(value, (int, float)) or value < 0 for value in values):
        raise InputValidationError("rainfall.rainfall_mm must contain non-negative numbers")

    runoff = config["runoff"]
    if runoff.get("initial_loss_mm", -1) < 0 or runoff.get("stable_loss_mm_per_h", -1) < 0:
        raise InputValidationError("runoff losses must be non-negative")

    uh = config["unit_hydrograph"]
    if uh.get("n", 0) <= 0 or uh.get("K_h", 0) <= 0:
        raise InputValidationError("unit_hydrograph n and K_h must be positive")
