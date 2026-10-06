from __future__ import annotations

from dataclasses import dataclass
import heapq
from pathlib import Path

import numpy as np

from .errors import InputValidationError
from .spatial import RasterInfo, read_raster_info


NEIGHBOURS = (
    (-1, 0, 1.0),
    (-1, 1, 2**0.5),
    (0, 1, 1.0),
    (1, 1, 2**0.5),
    (1, 0, 1.0),
    (1, -1, 2**0.5),
    (0, -1, 1.0),
    (-1, -1, 2**0.5),
)


@dataclass(frozen=True)
class BasinParameters:
    area_km2: float
    main_channel_length_km: float
    main_channel_slope: float
    path: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class DemData:
    values: np.ndarray
    valid: np.ndarray
    info: RasterInfo
    geotransform: tuple[float, ...]


def read_dem(path: str | Path) -> DemData:
    try:
        from osgeo import gdal
    except ImportError as exc:  # pragma: no cover
        raise InputValidationError("GDAL/OSGeo is required for DEM processing") from exc
    info = read_raster_info(path)
    dataset = gdal.Open(str(path), gdal.GA_ReadOnly)
    band = dataset.GetRasterBand(1)
    values = band.ReadAsArray().astype(float)
    valid = np.isfinite(values)
    if info.nodata is not None:
        valid &= values != info.nodata
    if not np.any(valid):
        raise InputValidationError("DEM contains no valid elevation cells")
    return DemData(values, valid, info, dataset.GetGeoTransform())


def fill_depressions(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Priority-flood depression filling without an external GIS backend."""
    if values.shape != valid.shape or values.ndim != 2:
        raise InputValidationError("values and valid must be matching two-dimensional arrays")
    filled = values.copy()
    visited = ~valid
    heap: list[tuple[float, int, int]] = []
    rows, cols = values.shape
    for r in range(rows):
        for c in (0, cols - 1):
            if valid[r, c] and not visited[r, c]:
                visited[r, c] = True
                heapq.heappush(heap, (filled[r, c], r, c))
    for c in range(cols):
        for r in (0, rows - 1):
            if valid[r, c] and not visited[r, c]:
                visited[r, c] = True
                heapq.heappush(heap, (filled[r, c], r, c))
    while heap:
        level, r, c = heapq.heappop(heap)
        for dr, dc, _ in NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if 0 <= rr < rows and 0 <= cc < cols and valid[rr, cc] and not visited[rr, cc]:
                visited[rr, cc] = True
                filled[rr, cc] = max(filled[rr, cc], level)
                heapq.heappush(heap, (filled[rr, cc], rr, cc))
    return filled


def flow_direction(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Return D8 direction indices; -1 means no downhill neighbour."""
    rows, cols = values.shape
    directions = np.full((rows, cols), -1, dtype=np.int8)
    for r in range(rows):
        for c in range(cols):
            if not valid[r, c]:
                continue
            candidates: list[tuple[float, int]] = []
            for index, (dr, dc, distance) in enumerate(NEIGHBOURS):
                rr, cc = r + dr, c + dc
                if 0 <= rr < rows and 0 <= cc < cols and valid[rr, cc]:
                    drop = (values[r, c] - values[rr, cc]) / distance
                    if drop > 0:
                        candidates.append((drop, index))
            if candidates:
                directions[r, c] = max(candidates)[1]
    return directions


def flow_accumulation(directions: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Count contributing cells for a D8 direction grid."""
    rows, cols = directions.shape
    accumulation = np.where(valid, 1.0, 0.0)
    indegree = np.zeros_like(directions, dtype=np.int32)
    targets: dict[tuple[int, int], tuple[int, int]] = {}
    for r in range(rows):
        for c in range(cols):
            index = int(directions[r, c])
            if index < 0:
                continue
            dr, dc, _ = NEIGHBOURS[index]
            target = (r + dr, c + dc)
            if 0 <= target[0] < rows and 0 <= target[1] < cols and valid[target]:
                targets[(r, c)] = target
                indegree[target] += 1
    queue = [(r, c) for r in range(rows) for c in range(cols) if valid[r, c] and indegree[r, c] == 0]
    cursor = 0
    while cursor < len(queue):
        cell = queue[cursor]
        cursor += 1
        target = targets.get(cell)
        if target is None:
            continue
        accumulation[target] += accumulation[cell]
        indegree[target] -= 1
        if indegree[target] == 0:
            queue.append(target)
    return accumulation


def delineate_watershed(
    directions: np.ndarray,
    valid: np.ndarray,
    outlet_row: int,
    outlet_col: int,
) -> np.ndarray:
    rows, cols = directions.shape
    if not (0 <= outlet_row < rows and 0 <= outlet_col < cols and valid[outlet_row, outlet_col]):
        raise InputValidationError("outlet must be inside a valid DEM cell")
    watershed = np.zeros_like(valid, dtype=bool)
    stack = [(outlet_row, outlet_col)]
    while stack:
        r, c = stack.pop()
        if watershed[r, c]:
            continue
        watershed[r, c] = True
        for dr, dc, _ in NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if 0 <= rr < rows and 0 <= cc < cols and valid[rr, cc] and not watershed[rr, cc]:
                index = int(directions[rr, cc])
                if index >= 0:
                    tr, tc, _ = NEIGHBOURS[index]
                    if (rr + tr, cc + tc) == (r, c):
                        stack.append((rr, cc))
    return watershed


def extract_streams(accumulation: np.ndarray, threshold_cells: float) -> np.ndarray:
    if not np.isfinite(threshold_cells) or threshold_cells < 1:
        raise InputValidationError("threshold_cells must be at least 1")
    return accumulation >= threshold_cells


def calculate_basin_parameters(
    dem: DemData,
    filled: np.ndarray,
    directions: np.ndarray,
    accumulation: np.ndarray,
    watershed: np.ndarray,
    outlet: tuple[int, int],
) -> BasinParameters:
    area_km2 = float(watershed.sum() * dem.info.pixel_area_m2 / 1_000_000.0)
    path = [outlet]
    current = outlet
    while True:
        r, c = current
        upstream: list[tuple[float, tuple[int, int], float]] = []
        for dr, dc, distance in NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < directions.shape[0] and 0 <= cc < directions.shape[1]) or not watershed[rr, cc]:
                continue
            index = int(directions[rr, cc])
            if index >= 0 and (rr + NEIGHBOURS[index][0], cc + NEIGHBOURS[index][1]) == current:
                upstream.append((accumulation[rr, cc], (rr, cc), distance))
        if not upstream:
            break
        _, next_cell, distance = max(upstream, key=lambda item: item[0])
        path.append(next_cell)
        current = next_cell
    length_m = 0.0
    for first, second in zip(path, path[1:]):
        length_m += ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5
    length_m *= dem.info.pixel_width_m
    elevations = np.array([filled[r, c] for r, c in path])
    slope = float((elevations[-1] - elevations[0]) / max(length_m, 1e-12))
    return BasinParameters(area_km2, length_m / 1000.0, max(0.0, slope), tuple(path))
