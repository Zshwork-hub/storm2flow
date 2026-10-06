"""DEM-to-basin workflow with inspectable raster and vector artifacts."""
from dataclasses import dataclass, asdict
import csv
import json
from pathlib import Path

import numpy as np

from .dem import (DemData, BasinParameters, SnappedOutlet, read_dem, fill_depressions,
                  flow_direction, flow_accumulation, extract_streams,
                  snap_outlet, delineate_watershed, calculate_basin_parameters)
from .errors import InputValidationError


@dataclass(frozen=True)
class SpatialAnalysis:
    dem: DemData
    filled: np.ndarray
    directions: np.ndarray
    accumulation: np.ndarray
    streams: np.ndarray
    watershed: np.ndarray
    outlet: SnappedOutlet
    parameters: BasinParameters
    threshold_cells: float
    warnings: tuple[str, ...]


def analyze_dem(path: str | Path, outlet_xy, *, outlet_crs: str,
                radius_m: float = 100.0, threshold_cells: float | None = None,
                target_crs: str | None = None) -> SpatialAnalysis:
    """Transform a user-specified point CRS into the metric DEM CRS before snapping."""
    from osgeo import osr
    dem = read_dem(path, target_crs=target_crs)
    if (not isinstance(outlet_xy, (list, tuple)) or len(outlet_xy) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) for v in outlet_xy)):
        raise InputValidationError("outlet_xy must contain x and y")
    if not isinstance(outlet_crs, str) or not outlet_crs.strip():
        raise InputValidationError("outlet_crs must be a CRS identifier")
    if threshold_cells is None:
        threshold_cells = max(2, int(dem.valid.sum() * .005))
    source = osr.SpatialReference()
    if source.SetFromUserInput(outlet_crs) != 0:
        raise InputValidationError("invalid outlet_crs")
    target = osr.SpatialReference(wkt=dem.info.crs_wkt)
    source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    x, y, _ = osr.CoordinateTransformation(source, target).TransformPoint(*outlet_xy)
    filled = fill_depressions(dem.values, dem.valid)
    directions = flow_direction(filled, dem.valid, dem.info.pixel_width_m, dem.info.pixel_height_m)
    accumulation = flow_accumulation(directions, dem.valid)
    streams = extract_streams(accumulation, threshold_cells)
    outlet = snap_outlet(dem, accumulation, x, y, radius_m, threshold_cells)
    watershed = delineate_watershed(directions, dem.valid, outlet.row, outlet.col)
    params = calculate_basin_parameters(dem, filled, directions, accumulation, watershed,
                                        (outlet.row, outlet.col), streams=streams)
    warnings = []
    warnings.append(f"本次河网阈值为 {threshold_cells} 个贡献像元；阈值影响河道起点，须结合影像复核。")
    if target_crs:
        warnings.append(f"DEM 按用户指定的 {target_crs} 重投影，使用双线性高程重采样；请复核像元尺寸。")
    if max(abs(dem.info.pixel_width_m), abs(dem.info.pixel_height_m)) > 100:
        warnings.append("DEM 分辨率超过 100 m，请复核参数精度。")
    if np.any(~dem.valid):
        warnings.append("DEM 含 NoData：其邻接单元按开放排水边界处理，请检查数据缺口是否截断流域。")
    if watershed[0].any() or watershed[-1].any() or watershed[:, 0].any() or watershed[:, -1].any():
        warnings.append("流域接触 DEM 外边界，请确认 DEM 覆盖完整上游范围。")
    if params.main_channel_slope <= 0:
        warnings.append("主河道首尾比降为零；平坦区路径由确定性排水规则决定，需人工复核。")
    if np.count_nonzero(filled[dem.valid] != dem.values[dem.valid]):
        warnings.append("DEM 已填洼；比降使用处理后高程，原始及处理后高程均保存在纵断面表中。")
    return SpatialAnalysis(dem, filled, directions, accumulation, streams, watershed,
                           outlet, params, threshold_cells, tuple(warnings))


def save_spatial_analysis(analysis: SpatialAnalysis, directory: Path) -> Path:
    """Write rasters, outlet audit, longitudinal profile and GIS layers."""
    from osgeo import gdal, ogr, osr
    directory.mkdir(parents=True, exist_ok=True)
    info = analysis.dem.info
    for name, values in (("filled_dem", analysis.filled), ("d8_direction", analysis.directions),
                         ("flow_accumulation", analysis.accumulation), ("streams", analysis.streams),
                         ("watershed", analysis.watershed)):
        ds = gdal.GetDriverByName('GTiff').Create(str(directory / f'{name}.tif'), info.width,
                                                  info.height, 1, gdal.GDT_Float64,
                                                  options=['COMPRESS=DEFLATE'])
        ds.SetGeoTransform(analysis.dem.geotransform)
        ds.SetProjection(info.crs_wkt)
        ds.GetRasterBand(1).SetNoDataValue(-9999)
        ds.GetRasterBand(1).WriteArray(np.where(analysis.dem.valid, values, -9999))
        ds = None

    metadata = {"outlet": asdict(analysis.outlet), "automatic_parameters": asdict(analysis.parameters),
                "stream_threshold_cells": analysis.threshold_cells, "warnings": analysis.warnings,
                "dem_crs_wkt": info.crs_wkt,
                "direction_encoding": "-1 terminal; (row,col) offsets: 0(-1,0),1(-1,1),2(0,1),3(1,1),4(1,0),5(1,-1),6(0,-1),7(-1,-1)",
                "nodata_boundary": "open"}
    (directory / 'spatial_analysis.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    gt = analysis.dem.geotransform
    coords = [(gt[0] + (c + .5) * gt[1], gt[3] + (r + .5) * gt[5]) for r, c in analysis.parameters.path]
    distances = [0.0]
    for first, second in zip(coords, coords[1:]):
        distances.append(distances[-1] + float(np.hypot(second[0] - first[0], second[1] - first[1])))
    with (directory / 'channel_profile.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['distance_from_outlet_m', 'x_m', 'y_m', 'raw_elevation_m', 'filled_elevation_m'])
        writer.writerows((d, x, y, analysis.dem.values[r, c], analysis.filled[r, c])
                         for d, (x, y), (r, c) in zip(distances, coords, analysis.parameters.path))

    path = directory / 'basin.gpkg'
    output = ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
    ref = osr.SpatialReference(wkt=info.crs_wkt)
    layer = output.CreateLayer('basin', ref, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn('basin_id', ogr.OFTInteger))
    mask = gdal.GetDriverByName('MEM').Create('', info.width, info.height, 1, gdal.GDT_Byte)
    mask.SetGeoTransform(gt)
    mask.SetProjection(info.crs_wkt)
    mask.GetRasterBand(1).WriteArray(analysis.watershed.astype(np.uint8))
    if gdal.Polygonize(mask.GetRasterBand(1), mask.GetRasterBand(1), layer, 0, []) != 0:
        raise InputValidationError('failed to polygonize watershed')
    layer = output.CreateLayer('main_channel', ref, ogr.wkbLineString)
    geometry = ogr.Geometry(ogr.wkbLineString)
    for x, y in coords:
        geometry.AddPoint_2D(x, y)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(geometry)
    if layer.CreateFeature(feature) != 0:
        raise InputValidationError('failed to save main channel')
    feature = None
    layer = output.CreateLayer('outlets', ref, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn('role', ogr.OFTString))
    for role, x, y in (('original', analysis.outlet.original_x, analysis.outlet.original_y),
                       ('snapped', analysis.outlet.snapped_x, analysis.outlet.snapped_y)):
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint_2D(x, y)
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField('role', role)
        feature.SetGeometry(point)
        if layer.CreateFeature(feature) != 0:
            raise InputValidationError('failed to save outlet')
    feature = None
    layer = None
    output = None
    return path
