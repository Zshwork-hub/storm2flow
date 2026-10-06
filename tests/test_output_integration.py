"""Run with python -m unittest discover -s tests -p test_output_integration.py."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from storm2flow.errors import InputValidationError
from storm2flow.pipeline import run_calculation
from storm2flow.config import validate_config
from storm2flow.unit_hydrograph import GammaUnitHydrograph


class OutputIntegrationTests(unittest.TestCase):
    def setUp(self):
        workspace_temp = Path(__file__).parents[1] / 'results' / 'test-temp'
        workspace_temp.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=workspace_temp)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = json.loads((Path(__file__).parents[1] / 'examples/design_storm.json').read_text(encoding='utf-8'))
        self.config['basin']['name'] = '<script>alert(1)</script>中文流域'

    def run_case(self):
        source = self.root / '参数.json'
        source.write_text(json.dumps(self.config, ensure_ascii=False), encoding='utf-8')
        return run_calculation(source, self.root / '成果')

    def test_exports_roundtrip_and_consistent_volume(self):
        result = self.run_case()
        summary = json.loads((result / 'summary.json').read_text(encoding='utf-8'))
        with (result / 'hydrograph.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        volume = sum(float(row['mean_flow_m3s']) * (float(row['end_time_h']) - float(row['start_time_h'])) * 3600 for row in rows)
        self.assertAlmostEqual(volume, summary['hydrograph_volume_m3'])
        self.assertLess(abs(volume / summary['net_rain_volume_m3'] - 1), 0.01)
        self.assertEqual((result / 'hydrograph.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        report = (result / 'report.html').read_text(encoding='utf-8')
        self.assertIn('&lt;script&gt;', report)
        self.assertNotIn('<script>', report)
        self.assertTrue((result / 'intermediate/unit_response.csv').exists())
        with self.assertRaises(InputValidationError):
            self.run_case()

    def test_first_interval_nonzero_volume_regression(self):
        result = GammaUnitHydrograph(1, 1).convolve(np.array([10.]), 1, 1)
        self.assertAlmostEqual(result.volume_m3, 10000, delta=0.01)

    def test_missing_vector_retains_parameters_and_failure(self):
        self.config['basin']['vector_path'] = 'missing.gpkg'
        with self.assertRaises(InputValidationError):
            self.run_case()
        self.assertTrue((self.root / '成果/parameters.json').exists())
        self.assertTrue((self.root / '成果/failure.txt').exists())

    def test_zero_rainfall_produces_zero_finite_outputs(self):
        self.config['rainfall']['rainfall_mm'] = [0] * 6
        result = self.run_case()
        summary = json.loads((result / 'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['hydrograph_volume_m3'], 0)
        self.assertEqual(summary['peak_mean_flow_m3s'], 0)

    def test_nonfinite_wrong_type_and_duration_are_rejected(self):
        for bad in (float('nan'), float('inf'), -1, True, 'bad', None):
            with self.subTest(bad=bad), self.assertRaises(InputValidationError):
                self.config['rainfall']['time_step_h'] = bad
                validate_config(self.config)
        self.config['rainfall']['time_step_h'] = 1
        self.config['rainfall']['duration_h'] = 7
        with self.assertRaises(InputValidationError):
            validate_config(self.config)

    def test_geopackage_preserves_polygon_and_crs(self):
        from osgeo import ogr, osr
        ref = osr.SpatialReference()
        ref.ImportFromEPSG(32650)
        source = self.root / '输入流域.gpkg'
        ds = ogr.GetDriverByName('GPKG').CreateDataSource(str(source))
        layer = ds.CreateLayer('basin', ref, ogr.wkbPolygon)
        feat = ogr.Feature(layer.GetLayerDefn())
        feat.SetGeometry(ogr.CreateGeometryFromWkt('POLYGON ((500000 3000000, 502200 3000000, 502200 3003100, 500000 3003100, 500000 3000000))'))
        layer.CreateFeature(feat)
        feat = None
        layer = None
        ds = None
        self.config['basin']['vector_path'] = source.name
        result = self.run_case()
        ds = ogr.Open(str(result / 'basin.gpkg'))
        layer = ds.GetLayerByName('basin')
        self.assertEqual(layer.GetFeatureCount(), 1)
        self.assertEqual(layer.GetSpatialRef().GetAuthorityCode(None), '32650')
        self.assertIn('32650', (result / 'report.html').read_text(encoding='utf-8'))
        exported_feature = layer.GetNextFeature()
        self.assertAlmostEqual(exported_feature.GetGeometryRef().GetArea(), 6820000)
        exported_feature = None
        layer = None
        ds = None


if __name__ == '__main__':
    unittest.main()
