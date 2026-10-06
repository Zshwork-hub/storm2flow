from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import InputValidationError
from .rainfall import RainfallSeries


@dataclass(frozen=True)
class RunoffResult:
    rainfall_mm: np.ndarray
    initial_loss_mm: np.ndarray
    stable_loss_mm: np.ndarray
    net_rainfall_mm: np.ndarray

    @property
    def total_rainfall_mm(self) -> float:
        return float(self.rainfall_mm.sum())

    @property
    def total_net_rainfall_mm(self) -> float:
        return float(self.net_rainfall_mm.sum())

    def volume_m3(self, area_km2: float) -> float:
        if not np.isfinite(area_km2) or area_km2 <= 0:
            raise InputValidationError("area_km2 must be positive")
        return self.total_net_rainfall_mm * area_km2 * 1000.0


def calculate_net_rainfall(
    rainfall: RainfallSeries,
    initial_loss_mm: float,
    stable_loss_mm_per_h: float,
) -> RunoffResult:
    """Apply the initial-loss and constant-infiltration-loss model."""
    if not np.isfinite(initial_loss_mm) or initial_loss_mm < 0:
        raise InputValidationError("initial_loss_mm must be non-negative")
    if not np.isfinite(stable_loss_mm_per_h) or stable_loss_mm_per_h < 0:
        raise InputValidationError("stable_loss_mm_per_h must be non-negative")

    rain = rainfall.rainfall_mm.copy()
    initial = np.zeros_like(rain)
    stable = np.zeros_like(rain)
    net = np.zeros_like(rain)
    remaining_initial = float(initial_loss_mm)
    stable_capacity = stable_loss_mm_per_h * rainfall.time_step_h

    for index, amount in enumerate(rain):
        initial[index] = min(amount, remaining_initial)
        remaining_initial -= initial[index]
        after_initial = amount - initial[index]
        stable[index] = min(after_initial, stable_capacity)
        net[index] = after_initial - stable[index]

    if np.any(net < -1e-12) or np.any(net > rain + 1e-12):
        raise RuntimeError("runoff calculation violated rainfall bounds")
    return RunoffResult(rain, initial, stable, np.maximum(net, 0.0))
