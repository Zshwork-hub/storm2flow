from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import InputValidationError


@dataclass(frozen=True)
class RainfallSeries:
    """Incremental rainfall for equally sized time steps.

    ``rainfall_mm`` contains rainfall depth in each interval, not cumulative
    rainfall. ``time_step_h`` is the interval length in hours.
    """

    rainfall_mm: np.ndarray
    time_step_h: float
    return_period_y: int | None = None
    source: str = "manual"

    def __post_init__(self) -> None:
        values = np.asarray(self.rainfall_mm, dtype=float)
        object.__setattr__(self, "rainfall_mm", values)
        if values.ndim != 1 or values.size == 0:
            raise InputValidationError("rainfall_mm must be a non-empty one-dimensional array")
        if not np.all(np.isfinite(values)) or np.any(values < 0):
            raise InputValidationError("rainfall_mm must contain finite non-negative values")
        if not np.isfinite(self.time_step_h) or self.time_step_h <= 0:
            raise InputValidationError("time_step_h must be positive")
        if self.return_period_y is not None and self.return_period_y <= 0:
            raise InputValidationError("return_period_y must be positive")

    @property
    def duration_h(self) -> float:
        return float(self.rainfall_mm.size * self.time_step_h)

    @property
    def total_mm(self) -> float:
        return float(self.rainfall_mm.sum())
