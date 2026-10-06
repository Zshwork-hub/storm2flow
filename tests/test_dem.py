import numpy as np

from storm2flow.dem import (
    calculate_basin_parameters,
    delineate_watershed,
    fill_depressions,
    flow_accumulation,
    flow_direction,
)
from storm2flow.spatial import RasterInfo
from storm2flow.dem import DemData


def synthetic_dem():
    rows, cols = 20, 20
    y, x = np.indices((rows, cols))
    values = 100.0 - y - x
    valid = np.ones_like(values, dtype=bool)
    info = RasterInfo(
        path=None,
        width=cols,
        height=rows,
        pixel_width_m=10.0,
        pixel_height_m=-10.0,
        nodata=None,
        crs_wkt="synthetic",
    )
    return DemData(values, valid, info, (0, 10, 0, 200, 0, -10))


def test_synthetic_dem_flow_and_basin_parameters():
    dem = synthetic_dem()
    filled = fill_depressions(dem.values, dem.valid)
    direction = flow_direction(filled, dem.valid)
    accumulation = flow_accumulation(direction, dem.valid)
    watershed = delineate_watershed(direction, dem.valid, 19, 19)
    params = calculate_basin_parameters(
        dem, filled, direction, accumulation, watershed, (19, 19)
    )
    assert params.area_km2 == 0.04
    assert params.main_channel_length_km > 0
    assert params.main_channel_slope > 0
    assert watershed.all()


def test_priority_flood_raises_pit_to_boundary_spill_level():
    values = np.array([[10, 10, 10], [10, 0, 10], [10, 10, 10]], dtype=float)
    valid = np.ones_like(values, dtype=bool)
    filled = fill_depressions(values, valid)
    assert filled[1, 1] == 10
