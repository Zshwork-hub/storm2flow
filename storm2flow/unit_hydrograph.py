from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import gammainc, gamma

from .errors import ConservationError, InputValidationError


@dataclass(frozen=True)
class HydrographResult:
    time_h: np.ndarray
    flow_m3s: np.ndarray
    unit_response: np.ndarray
    unit_response_sum: float
    water_balance_relative_error: float

    @property
    def peak_flow_m3s(self) -> float:
        return float(np.max(self.flow_m3s))

    @property
    def peak_time_h(self) -> float:
        return float(self.time_h[int(np.argmax(self.flow_m3s))])

    @property
    def volume_m3(self) -> float:
        if self.flow_m3s.size < 2:
            return 0.0
        return float(np.trapezoid(self.flow_m3s, self.time_h) * 3600.0)


class GammaUnitHydrograph:
    """Gamma instantaneous unit hydrograph with non-integer shape ``n``."""

    def __init__(self, n: float, K_h: float, *, cutoff: float = 0.999):
        if not np.isfinite(n) or n <= 0:
            raise InputValidationError("n must be positive")
        if not np.isfinite(K_h) or K_h <= 0:
            raise InputValidationError("K_h must be positive")
        if not 0 < cutoff < 1:
            raise InputValidationError("cutoff must be between 0 and 1")
        self.n = float(n)
        self.K_h = float(K_h)
        self.cutoff = float(cutoff)

    def s_curve(self, time_h: np.ndarray | float) -> np.ndarray:
        t = np.asarray(time_h, dtype=float)
        result = np.zeros_like(t, dtype=float)
        positive = t > 0
        result[positive] = gammainc(self.n, t[positive] / self.K_h)
        return result

    def unit_response(self, time_step_h: float, *, max_time_h: float | None = None) -> np.ndarray:
        if not np.isfinite(time_step_h) or time_step_h <= 0:
            raise InputValidationError("time_step_h must be positive")
        if max_time_h is None:
            max_time_h = self.K_h * 20.0
        if max_time_h <= time_step_h:
            raise InputValidationError("max_time_h must exceed time_step_h")
        steps = int(np.ceil(max_time_h / time_step_h))
        edges = np.arange(steps + 1, dtype=float) * time_step_h
        response = np.diff(self.s_curve(edges))
        while response.sum() < self.cutoff:
            extra = max(steps, 1)
            edges = np.arange(steps + extra + 1, dtype=float) * time_step_h
            response = np.diff(self.s_curve(edges))
            steps += extra
            if steps > 1_000_000:
                raise RuntimeError("unit response cutoff could not be reached")
        return response

    def convolve(
        self,
        net_rainfall_mm: np.ndarray,
        time_step_h: float,
        area_km2: float,
        *,
        conservation_tolerance: float = 0.01,
    ) -> HydrographResult:
        rain = np.asarray(net_rainfall_mm, dtype=float)
        if rain.ndim != 1 or rain.size == 0 or not np.all(np.isfinite(rain)) or np.any(rain < 0):
            raise InputValidationError("net_rainfall_mm must be a non-empty finite non-negative array")
        if not np.isfinite(area_km2) or area_km2 <= 0:
            raise InputValidationError("area_km2 must be positive")
        if conservation_tolerance <= 0:
            raise InputValidationError("conservation_tolerance must be positive")

        response = self.unit_response(time_step_h)
        flow = np.convolve(rain, response) * area_km2 / (3.6 * time_step_h)
        time = np.arange(flow.size, dtype=float) * time_step_h
        expected_volume = float(rain.sum() * area_km2 * 1000.0)
        actual_volume = float(np.sum(flow) * time_step_h * 3600.0)
        relative_error = abs(actual_volume - expected_volume) / max(expected_volume, 1.0)
        if relative_error > conservation_tolerance:
            raise ConservationError(
                f"hydrograph volume error {relative_error:.6%} exceeds {conservation_tolerance:.2%}"
            )
        return HydrographResult(time, flow, response, float(response.sum()), relative_error)
