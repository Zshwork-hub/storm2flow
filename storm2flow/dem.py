from __future__ import annotations

from dataclasses import dataclass
from collections import deque
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
    regression_slope: float = 0.0


@dataclass(frozen=True)
class DemData:
    values: np.ndarray
    valid: np.ndarray
    info: RasterInfo
    geotransform: tuple[float, ...]


def read_dem(path: str | Path, *, target_crs: str | None = None) -> DemData:
    try:
        from osgeo import gdal
    except ImportError as exc:  # pragma: no cover
        raise InputValidationError("GDAL/OSGeo is required for DEM processing") from exc
    dataset = gdal.Open(str(path), gdal.GA_ReadOnly)
    if dataset is None:
        raise InputValidationError(f"cannot open DEM: {path}")
    if target_crs is None:
        info = read_raster_info(path)
    else:
        from osgeo import osr
        from .spatial import require_projected_crs
        target = osr.SpatialReference()
        if target.SetFromUserInput(target_crs) != 0:
            raise InputValidationError("invalid DEM target_crs")
        require_projected_crs(target.ExportToWkt())
        if not dataset.GetProjectionRef() or dataset.GetGeoTransform(can_return_null=True) is None:
            raise InputValidationError("DEM must have a CRS and geotransform before reprojection")
        dataset = gdal.Warp('', dataset, format='MEM', dstSRS=target.ExportToWkt(),
                            resampleAlg='bilinear', outputType=gdal.GDT_Float64,
                            dstNodata=float('nan'))
        if dataset is None:
            raise InputValidationError("DEM reprojection failed")
        gt = dataset.GetGeoTransform()
        info = RasterInfo(Path(path), dataset.RasterXSize, dataset.RasterYSize, gt[1], gt[5],
                          dataset.GetRasterBand(1).GetNoDataValue(), dataset.GetProjectionRef())
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
    # NoData margins are open drainage boundaries, including interior holes.
    for r in range(rows):
        for c in range(cols):
            if valid[r, c] and any(
                not (0 <= r + dr < rows and 0 <= c + dc < cols) or not valid[r + dr, c + dc]
                for dr, dc, _ in NEIGHBOURS
            ):
                visited[r, c] = True
                heapq.heappush(heap, (filled[r, c], r, c))
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


def flow_direction(values: np.ndarray, valid: np.ndarray,
                   pixel_width_m: float = 1.0, pixel_height_m: float = 1.0) -> np.ndarray:
    """D8 steepest descent plus acyclic equal-elevation routing to outlets.

    Flat routing uses a deterministic multi-source breadth-first traversal from
    downhill/edge cells. It does not modify elevations. Closed unfilled pits
    remain terminal cells; call fill_depressions first.
    """
    if values.ndim != 2 or values.shape != valid.shape or not np.all(np.isfinite(values[valid])):
        raise InputValidationError("DEM arrays must match and valid elevations must be finite")
    if not np.isfinite(pixel_width_m) or not np.isfinite(pixel_height_m) or pixel_width_m == 0 or pixel_height_m == 0:
        raise InputValidationError("pixel dimensions must be finite and nonzero")
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
                    distance_m = np.hypot(dc * pixel_width_m, dr * pixel_height_m)
                    drop = (values[r, c] - values[rr, cc]) / distance_m
                    if drop > 0:
                        candidates.append((drop, index))
            if candidates:
                directions[r, c] = max(candidates)[1]
    reached = np.zeros_like(valid, dtype=bool)
    queue = deque()
    for r in range(rows):
        for c in range(cols):
            if not valid[r, c]:
                continue
            boundary = any(not (0 <= r + dr < rows and 0 <= c + dc < cols)
                           or not valid[r + dr, c + dc] for dr, dc, _ in NEIGHBOURS)
            if directions[r, c] >= 0 or boundary:
                reached[r, c] = True
                queue.append((r, c))
    while queue:
        r, c = queue.popleft()
        for index, (dr, dc, _) in enumerate(NEIGHBOURS):
            rr, cc = r + dr, c + dc
            if (0 <= rr < rows and 0 <= cc < cols and valid[rr, cc]
                    and not reached[rr, cc] and values[rr, cc] == values[r, c]):
                directions[rr, cc] = (index + 4) % 8
                reached[rr, cc] = True
                queue.append((rr, cc))
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
            if index > 7:
                raise InputValidationError("D8 direction must be -1 or 0..7")
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
    if len(queue) != int(valid.sum()):
        raise InputValidationError("D8 grid contains a flow cycle")
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
    streams: np.ndarray | None = None,
) -> BasinParameters:
    area_km2 = float(watershed.sum() * dem.info.pixel_area_m2 / 1_000_000.0)
    channel_cells = watershed if streams is None else watershed & streams
    if not channel_cells[outlet]:
        raise InputValidationError("outlet must be on the extracted stream network")
    # Dynamic programming over the contributing DAG: the largest contributing
    # area is not necessarily the longest branch.
    lengths = np.zeros_like(filled, dtype=float)
    predecessors = {}
    targets = {}
    indegree = np.zeros_like(directions, dtype=np.int32)
    for r, c in zip(*np.where(channel_cells)):
        cell = (int(r), int(c))
        if cell == outlet or directions[cell] < 0:
            continue
        dr, dc, _ = NEIGHBOURS[int(directions[cell])]
        target = (int(r + dr), int(c + dc))
        if (0 <= target[0] < filled.shape[0] and 0 <= target[1] < filled.shape[1]
                and channel_cells[target]):
            targets[cell] = (target, float(np.hypot(dc * dem.info.pixel_width_m, dr * dem.info.pixel_height_m)))
            indegree[target] += 1
    queue = deque((int(r), int(c)) for r, c in zip(*np.where(channel_cells & (indegree == 0))))
    count = 0
    while queue:
        cell = queue.popleft()
        count += 1
        if cell not in targets:
            continue
        target, distance = targets[cell]
        candidate = lengths[cell] + distance
        if candidate > lengths[target]:
            lengths[target] = candidate
            predecessors[target] = cell
        indegree[target] -= 1
        if indegree[target] == 0:
            queue.append(target)
    if count != int(channel_cells.sum()):
        raise InputValidationError("watershed contains a flow cycle")
    path = [outlet]
    while path[-1] in predecessors:
        path.append(predecessors[path[-1]])
    length_m = float(lengths[outlet])
    if length_m <= 0:
        raise InputValidationError("watershed has no measurable main channel")
    elevations = np.array([filled[r, c] for r, c in path])
    slope = float((elevations[-1] - elevations[0]) / length_m)
    distances = [0.0]
    for first, second in zip(path, path[1:]):
        distances.append(distances[-1] + float(np.hypot(
            (first[1] - second[1]) * dem.info.pixel_width_m,
            (first[0] - second[0]) * dem.info.pixel_height_m)))
    regression = float(np.polyfit(distances, elevations, 1)[0])
    return BasinParameters(area_km2, length_m / 1000.0, max(0.0, slope), tuple(path), regression)


@dataclass(frozen=True)
class SnappedOutlet:
    row: int
    col: int
    original_x: float
    original_y: float
    snapped_x: float
    snapped_y: float
    offset_m: float


def snap_outlet(dem: DemData, accumulation: np.ndarray, x: float, y: float,
                radius_m: float, threshold_cells: float = 1.0) -> SnappedOutlet:
    """Snap within a metre radius, ranked by accumulation, distance, row/col."""
    if not all(np.isfinite(v) for v in (x, y, radius_m, threshold_cells)) or radius_m < 0 or threshold_cells < 1:
        raise InputValidationError("outlet coordinates/radius/threshold are invalid")
    origin_x, width, _, origin_y, _, height = dem.geotransform
    row = int(np.floor((y - origin_y) / height))
    col = int(np.floor((x - origin_x) / width))
    if not (0 <= row < dem.values.shape[0] and 0 <= col < dem.values.shape[1]) or not dem.valid[row, col]:
        raise InputValidationError("outlet must fall inside a valid DEM cell")
    rows = np.arange(max(0, row - int(np.ceil(radius_m / abs(height))) - 1),
                     min(dem.values.shape[0], row + int(np.ceil(radius_m / abs(height))) + 2))
    cols = np.arange(max(0, col - int(np.ceil(radius_m / abs(width))) - 1),
                     min(dem.values.shape[1], col + int(np.ceil(radius_m / abs(width))) + 2))
    candidates = []
    for r in rows:
        for c in cols:
            xx = origin_x + (c + .5) * width
            yy = origin_y + (r + .5) * height
            distance = float(np.hypot(xx - x, yy - y))
            if dem.valid[r, c] and accumulation[r, c] >= threshold_cells and distance <= radius_m + 1e-9:
                candidates.append((-accumulation[r, c], distance, int(r), int(c), xx, yy))
    if not candidates:
        raise InputValidationError("no stream cell within snap radius; adjust point/radius/threshold")
    _, distance, r, c, xx, yy = min(candidates)
    return SnappedOutlet(r, c, float(x), float(y), float(xx), float(yy), distance)
