from __future__ import annotations

import json
import math
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
    step = _number(rainfall.get("time_step_h"), "rainfall.time_step_h", positive=True)
    for value in values:
        _number(value, "rainfall.rainfall_mm", positive=False)
    if "duration_h" in rainfall:
        duration = _number(rainfall["duration_h"], "rainfall.duration_h", positive=True)
        if not math.isclose(duration, len(values) * step, rel_tol=1e-8, abs_tol=1e-8):
            raise InputValidationError("rainfall.duration_h does not match array length and time_step_h")
    if rainfall.get("return_period_y") is not None:
        _number(rainfall["return_period_y"], "rainfall.return_period_y", positive=True)

    runoff = config["runoff"]
    for name in ("initial_loss_mm", "stable_loss_mm_per_h"):
        _number(runoff.get(name), f"runoff.{name}", positive=False)

    uh = config["unit_hydrograph"]
    for name in ("n", "K_h"):
        _number(uh.get(name), f"unit_hydrograph.{name}", positive=True)


def _number(value: Any, name: str, *, positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputValidationError(f"{name} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise InputValidationError(f"{name} must be {'positive' if positive else 'non-negative'}")
    return float(value)
