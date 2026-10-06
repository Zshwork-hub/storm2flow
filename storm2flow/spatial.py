from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

from .errors import InputValidationError


@dataclass(frozen=True)
class RasterInfo:
    path: Path
    width: int
    height: int
    pixel_width_m: float
    pixel_height_m: float
    nodata: float | None
    crs_wkt: str

    @property
    def pixel_area_m2(self) -> float:
        return abs(self.pixel_width_m * self.pixel_height_m)


def read_raster_info(path: str | Path) -> RasterInfo:
    """Read raster metadata through GDAL, which is bundled with QGIS."""
    try:
        from osgeo import gdal
    except ImportError as exc:  # pragma: no cover - only reached outside QGIS
        raise InputValidationError("GDAL/OSGeo is required for raster processing") from exc

    raster_path = Path(path)
    dataset = gdal.Open(str(raster_path), gdal.GA_ReadOnly)
    if dataset is None:
        raise InputValidationError(f"cannot open DEM: {raster_path}")
    band = dataset.GetRasterBand(1)
    transform = dataset.GetGeoTransform(can_return_null=True)
    projection = dataset.GetProjectionRef()
    if transform is None or not projection:
        raise InputValidationError("DEM must have a geotransform and CRS")
    if transform[2] != 0 or transform[4] != 0:
        raise InputValidationError("rotated DEM grids are not supported in MVP")
    if not all(math.isfinite(v) for v in transform) or abs(transform[1]) <= 0 or abs(transform[5]) <= 0:
        raise InputValidationError("DEM pixel size must be positive")
    require_projected_crs(projection)
    return RasterInfo(
        path=raster_path,
        width=dataset.RasterXSize,
        height=dataset.RasterYSize,
        pixel_width_m=float(transform[1]),
        pixel_height_m=float(transform[5]),
        nodata=band.GetNoDataValue(),
        crs_wkt=projection,
    )


def require_projected_crs(wkt: str) -> None:
    try:
        from osgeo import osr
    except ImportError as exc:  # pragma: no cover
        raise InputValidationError("GDAL/OSGeo is required for CRS validation") from exc
    spatial_ref = osr.SpatialReference(wkt=wkt)
    if not spatial_ref.IsProjected():
        raise InputValidationError("DEM CRS must be a projected CRS with metre-based horizontal units")
    unit_name = spatial_ref.GetLinearUnitsName() or ""
    unit_factor = spatial_ref.GetLinearUnits()
    if not math.isclose(unit_factor, 1.0, abs_tol=1e-12) or unit_name.lower() not in {"metre", "meter", "metres", "meters", "m"}:
        raise InputValidationError("DEM projected CRS must use metres as its horizontal unit")
