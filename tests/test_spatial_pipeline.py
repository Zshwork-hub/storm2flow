import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from storm2flow.dem import (DemData, fill_depressions, flow_direction, flow_accumulation,
                           delineate_watershed, calculate_basin_parameters, snap_outlet)
from storm2flow.spatial import RasterInfo
from storm2flow.errors import InputValidationError
from storm2flow.pipeline import run_calculation


def dem_fixture(values, width=10.0, height=10.0, valid=None):
    valid = np.ones_like(values, dtype=bool) if valid is None else valid
    info = RasterInfo(Path('synthetic'), values.shape[1], values.shape[0], width, -height, None, 'synthetic')
    return DemData(values, valid, info, (0, width, 0, values.shape[0] * height, 0, -height))


class SpatialCoreTests(unittest.TestCase):
    def test_flat_cells_route_to_edge_without_cycles(self):
        values = np.full((7, 7), 10.0)
        values[6, 3] = 9.0
        values[2:5, 2:5] = 0
        valid = np.ones_like(values, dtype=bool)
        filled = fill_depressions(values, valid)
        directions = flow_direction(filled, valid)
        self.assertTrue(np.all(directions[1:-1, 1:-1] >= 0))
        accumulation = flow_accumulation(directions, valid)
        self.assertEqual(accumulation[directions < 0].sum(), valid.sum())
        np.testing.assert_array_equal(directions, flow_direction(filled, valid))

    def test_nodata_border_filling(self):
        values = np.full((5, 5), -9999.0)
        values[1:4, 1:4] = 10
        values[2, 2] = 0
        valid = values != -9999
        filled = fill_depressions(values, valid)
        self.assertEqual(filled[2, 2], 10)
        self.assertEqual(filled[0, 0], -9999)

    def test_cycles_are_rejected(self):
        with self.assertRaises(InputValidationError):
            flow_accumulation(np.array([[2, 6]]), np.ones((1, 2), dtype=bool))

    def test_longest_branch_beats_larger_accumulation(self):
        y, x = np.indices((4, 6))
        dem = dem_fixture(100.0 - y - x)
        directions = np.full((4, 6), -1)
        directions[3, :5] = 2
        directions[1, 3] = 3
        directions[2, 4] = 3
        watershed = delineate_watershed(directions, dem.valid, 3, 5)
        accumulation = flow_accumulation(directions, dem.valid)
        accumulation[2, 4] = 100  # deliberately tempt the former greedy implementation
        params = calculate_basin_parameters(dem, dem.values, directions, accumulation, watershed, (3, 5))
        self.assertAlmostEqual(params.main_channel_length_km, 0.05)
        self.assertEqual(params.path[-1], (3, 0))

    def test_rectangular_pixels_have_correct_length_and_slope(self):
        y, x = np.indices((20, 20))
        dem = dem_fixture(1000.0 - 2*y - x, width=10, height=20)
        directions = flow_direction(dem.values, dem.valid, 10, 20)
        accumulation = flow_accumulation(directions, dem.valid)
        watershed = delineate_watershed(directions, dem.valid, 19, 19)
        params = calculate_basin_parameters(dem, dem.values, directions, accumulation, watershed, (19, 19))
        length = 19 * np.hypot(10, 20)
        self.assertAlmostEqual(params.area_km2, 0.08)
        self.assertAlmostEqual(params.main_channel_length_km * 1000, length)
        self.assertAlmostEqual(params.main_channel_slope, 57 / length)
        self.assertAlmostEqual(params.regression_slope, params.main_channel_slope)

    def test_stream_threshold_changes_channel_head_not_basin_area(self):
        dem = dem_fixture(np.array([[5., 4., 3., 2., 1.]]))
        directions = np.array([[2, 2, 2, 2, -1]])
        accumulation = flow_accumulation(directions, dem.valid)
        watershed = delineate_watershed(directions, dem.valid, 0, 4)
        params = calculate_basin_parameters(dem, dem.values, directions, accumulation,
                                            watershed, (0, 4), streams=accumulation >= 3)
        self.assertEqual(params.path[-1], (0, 2))
        self.assertAlmostEqual(params.main_channel_length_km, .02)
        self.assertAlmostEqual(params.area_km2, .0005)

    def test_snap_radius_threshold_and_nodata(self):
        dem = dem_fixture(np.zeros((3, 3)))
        accumulation = np.array([[1, 2, 1], [1, 9, 1], [1, 2, 1]])
        outlet = snap_outlet(dem, accumulation, 15, 25, 11, 2)
        self.assertEqual((outlet.row, outlet.col), (1, 1))
        self.assertEqual(outlet.offset_m, 10)
        with self.assertRaises(InputValidationError):
            snap_outlet(dem, accumulation, 15, 25, 9, 3)
        with self.assertRaises(InputValidationError):
            snap_outlet(dem, accumulation, -1, 25, 100)
        dem.valid[0, 1] = False
        with self.assertRaises(InputValidationError):
            snap_outlet(dem, accumulation, 15, 25, 11)


class SpatialFileTests(unittest.TestCase):
    def test_warp_excludes_uncovered_footprint_instead_of_creating_zero_dem(self):
        from osgeo import gdal, osr
        from storm2flow.dem import read_dem
        base = Path(__file__).parents[1] / 'results/test-temp'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            path = Path(temporary) / 'rotated.tif'
            ref = osr.SpatialReference()
            ref.ImportFromEPSG(32650)
            dataset = gdal.GetDriverByName('GTiff').Create(str(path), 10, 10, 1, gdal.GDT_Float32)
            dataset.SetProjection(ref.ExportToWkt())
            dataset.SetGeoTransform((500000, 10, 3, 3000000, 2, -10))
            dataset.GetRasterBand(1).WriteArray(np.full((10, 10), 100.0))
            dataset = None
            dem = read_dem(path, target_crs='EPSG:32650')
            self.assertTrue(np.any(~dem.valid))
            self.assertTrue(np.all(np.isnan(dem.values[~dem.valid])))
            np.testing.assert_allclose(dem.values[dem.valid], 100)

    def test_geographic_dem_requires_explicit_metric_target(self):
        from osgeo import gdal, osr
        from storm2flow.dem import read_dem
        base = Path(__file__).parents[1] / 'results/test-temp'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            path = Path(temporary) / 'geographic.tif'
            ref = osr.SpatialReference()
            ref.ImportFromEPSG(4326)
            dataset = gdal.GetDriverByName('GTiff').Create(str(path), 20, 20, 1, gdal.GDT_Float32)
            dataset.SetProjection(ref.ExportToWkt())
            dataset.SetGeoTransform((117, .0001, 0, 30, 0, -.0001))
            dataset.GetRasterBand(1).WriteArray(np.ones((20, 20)))
            dataset = None
            with self.assertRaises(InputValidationError):
                read_dem(path)
            dem = read_dem(path, target_crs='EPSG:32650')
            self.assertIn('32650', dem.info.crs_wkt)
            self.assertGreater(dem.info.pixel_area_m2, 1)
            with self.assertRaises(InputValidationError):
                read_dem(path, target_crs='EPSG:4326')

    def test_dem_to_report_and_spatial_roundtrip(self):
        from osgeo import gdal, ogr, osr
        base = Path(__file__).parents[1] / 'results/test-temp'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            root = Path(temporary)
            ref = osr.SpatialReference()
            ref.ImportFromEPSG(32650)
            dem_path = root / '合成DEM.tif'
            ds = gdal.GetDriverByName('GTiff').Create(str(dem_path), 20, 20, 1, gdal.GDT_Float32)
            ds.SetProjection(ref.ExportToWkt())
            ds.SetGeoTransform((500000, 10, 0, 3000000, 0, -10))
            y, x = np.indices((20, 20))
            ds.GetRasterBand(1).WriteArray(1000.0 - y - x)
            ds = None
            config = json.loads((Path(__file__).parents[1] / 'examples/design_storm.json').read_text(encoding='utf-8'))
            config['basin'] = {'name': '合成空间验收', 'dem_path': dem_path.name,
                               'outlet_xy': [500195, 2999805], 'outlet_crs': 'EPSG:32650'}
            config['processing'] = {'snap_radius_m': 0, 'stream_threshold_cells': 1}
            config_path = root / '参数.json'
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
            output = run_calculation(config_path, root / '成果')
            parameters = json.loads((output / 'parameters.json').read_text(encoding='utf-8'))
            self.assertAlmostEqual(parameters['basin']['area_km2'], 0.04)
            expected_length = 19 * np.sqrt(2) * 10
            self.assertAlmostEqual(parameters['basin']['main_channel_length_km'] * 1000, expected_length)
            gpkg = ogr.Open(str(output / 'basin.gpkg'))
            polygons = gpkg.GetLayerByName('basin')
            area = sum(feature.GetGeometryRef().GetArea() for feature in polygons)
            self.assertAlmostEqual(area, 40000)
            self.assertEqual(gpkg.GetLayerByName('outlets').GetFeatureCount(), 2)
            channel_feature = gpkg.GetLayerByName('main_channel').GetNextFeature()
            self.assertAlmostEqual(channel_feature.GetGeometryRef().Length(), expected_length)
            channel_feature = None
            polygons = None
            gpkg = None
            for filename in ('filled_dem', 'd8_direction', 'flow_accumulation', 'streams', 'watershed'):
                raster = gdal.Open(str(output / 'intermediate' / (filename + '.tif')))
                self.assertEqual(raster.RasterXSize, 20)
                self.assertIn('32650', raster.GetProjection())
                raster = None
            self.assertTrue((output / 'intermediate/channel_profile.csv').exists())
            summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertLess(summary['water_balance_relative_error'], .01)
            self.assertEqual(summary['outlet_snapping']['offset_m'], 0)
            self.assertTrue(summary['outlet_snapping']['success'])
            report = (output / 'report.html').read_text(encoding='utf-8')
            self.assertIn('intermediate/channel_profile.csv', report)
            self.assertIn('snapped_x', report)


if __name__ == '__main__':
    unittest.main()
