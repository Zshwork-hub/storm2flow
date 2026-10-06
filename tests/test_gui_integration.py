"""Real Qt/QGIS widget and subprocess checks, using an offscreen map canvas."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import tempfile
import time
import unittest
from zipfile import ZipFile
import importlib.util
import subprocess
import sys

from qgis.PyQt.QtWidgets import QMainWindow
from qgis.PyQt.QtCore import QProcess
from qgis.PyQt.QtGui import QFontDatabase, QFont
from qgis.core import QgsApplication, QgsProject
from qgis.gui import QgsMapCanvas


class TestIface:
    def __init__(self):
        self.window = QMainWindow()
        self.canvas = QgsMapCanvas(self.window)
        self.window.setCentralWidget(self.canvas)
        self.actions = []

    def mainWindow(self): return self.window
    def mapCanvas(self): return self.canvas
    def addPluginToMenu(self, menu, action): self.actions.append(action)
    def addToolBarIcon(self, action): pass
    def removePluginMenu(self, menu, action): self.actions.remove(action)
    def removeToolBarIcon(self, action): pass


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(__file__).parents[1]
        cls.base = cls.repo / 'results/gui-tests'
        cls.base.mkdir(parents=True, exist_ok=True)
        cls.app = QgsApplication([], True, str(cls.base / 'profile'))
        cls.app.setPrefixPath(os.environ['QGIS_PREFIX_PATH'], True)
        cls.app.initQgis()
        # Offscreen Qt cannot discover Windows fonts automatically.
        font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        if font_id >= 0:
            cls.app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().removeAllMapLayers()
        cls.app.exitQgis()

    def setUp(self):
        from storm2flow import classFactory
        self.iface = TestIface()
        self.plugin = classFactory(self.iface)
        self.plugin.initGui()
        self.plugin.run()
        self.dialog = self.plugin.dialog
        self.temporary = tempfile.TemporaryDirectory(dir=self.base)
        self.root = Path(self.temporary.name)

    def tearDown(self):
        QgsProject.instance().removeAllMapLayers()
        self.plugin.unload()
        self.app.processEvents()
        self.iface.window.close()
        self.temporary.cleanup()

    def wait_job(self):
        deadline = time.monotonic() + 60
        while self.dialog.job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        if self.dialog.job is not None:
            self.dialog.cancel_job()
            self.fail('subprocess did not finish within 60s')
        self.assertEqual(self.dialog.process.state(), QProcess.NotRunning)

    def configure_manual(self):
        from storm2flow.gui.dialog import StormDialog
        self.dialog.apply_config(self.repo / 'examples/design_storm.json')
        self.dialog.length.setValue(3.5)
        self.dialog.slope.setValue(.05)
        self.dialog.output_parent.setText(str(self.root))

    def test_plugin_lifecycle_and_review_gate(self):
        self.plugin.initGui()
        self.assertEqual(len(self.iface.actions), 1)
        self.configure_manual()
        with self.assertRaises(ValueError):
            self.dialog.build_config()
        self.dialog.reviewed.setChecked(True)
        self.assertEqual(self.dialog.build_config()['basin']['area_km2'], 6.82)
        self.dialog.area.setValue(7)
        self.assertFalse(self.dialog.reviewed.isChecked())
        self.plugin.unload()
        self.assertEqual(self.iface.actions, [])

    def test_manual_subprocess_generates_report(self):
        self.configure_manual()
        self.dialog.reviewed.setChecked(True)
        self.dialog.start_job('calculate')
        self.wait_job()
        self.assertIsNotNone(self.dialog.last_result, self.dialog.log.toPlainText())
        self.assertTrue((self.dialog.last_result / 'report.html').exists())
        self.assertTrue(self.dialog.report_button.isEnabled())
        data = json.loads((self.dialog.last_result / 'summary.json').read_text(encoding='utf-8'))
        self.assertLess(data['water_balance_relative_error'], .01)
        self.dialog.tabs.setCurrentIndex(2)
        self.dialog.grab().save(str(self.base / 'gui-results.png'))

    def test_spatial_preview_review_calculate_and_load_layers(self):
        from osgeo import gdal, osr
        import numpy as np
        ref = osr.SpatialReference()
        ref.ImportFromEPSG(32650)
        path = self.root / 'dem.tif'
        ds = gdal.GetDriverByName('GTiff').Create(str(path), 20, 20, 1, gdal.GDT_Float32)
        ds.SetProjection(ref.ExportToWkt())
        ds.SetGeoTransform((500000, 10, 0, 3000000, 0, -10))
        y, x = np.indices((20, 20))
        ds.GetRasterBand(1).WriteArray(1000. - y - x)
        ds = None
        data = json.loads((self.repo / 'examples/design_storm.json').read_text(encoding='utf-8'))
        data['basin'] = {'name': 'GUI 空间测试', 'dem_path': str(path),
                         'outlet_xy': [500195, 2999805], 'outlet_crs': 'EPSG:32650'}
        data['processing'] = {'stream_threshold_cells': 1, 'snap_radius_m': 0}
        config = self.root / 'parameters.json'
        config.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.dialog.apply_config(config)
        self.dialog.output_parent.setText(str(self.root))
        self.dialog.rain_values.clear()
        self.dialog.rain_source.clear()
        self.dialog.uh_source.clear()
        self.dialog.pick_outlet()
        self.dialog.start_job('preview')
        self.assertIsNone(self.dialog.pick_tool)
        self.wait_job()
        self.assertIsNotNone(self.dialog.preview_result, self.dialog.log.toPlainText())
        self.assertAlmostEqual(self.dialog.area.value(), .04)
        self.assertFalse(self.dialog.reviewed.isChecked())
        self.dialog.rain_values.setPlainText('12, 35, 58, 42, 20, 8')
        self.dialog.rain_source.setText('synthetic demonstration')
        self.dialog.uh_source.setText('synthetic demonstration')
        self.dialog.load_layers()
        self.assertEqual(len(QgsProject.instance().mapLayers()), 3)
        self.dialog.reviewed.setChecked(True)
        self.dialog.start_job('calculate')
        self.wait_job()
        self.assertIsNotNone(self.dialog.last_result, self.dialog.log.toPlainText())
        self.assertTrue((self.dialog.last_result / 'basin.gpkg').exists())
        # A subsequent preview must replace the prior calculation's spatial selection.
        self.dialog.start_job('preview')
        self.wait_job()
        self.assertEqual(self.dialog.spatial_result, self.dialog.preview_result)
        self.assertNotEqual(self.dialog.spatial_result, self.dialog.last_result)
        # Disabled widgets can still be changed programmatically: stale results
        # must never confirm a different outlet snapshot.
        self.dialog.start_job('preview')
        self.dialog.x.setValue(self.dialog.x.value() - 1)
        self.wait_job()
        self.assertIsNone(self.dialog.preview_result)
        self.assertFalse(self.dialog.reviewed.isEnabled())
        self.dialog.radius.setValue(1)
        self.assertIsNone(self.dialog.preview_result)
        self.assertFalse(self.dialog.reviewed.isEnabled())

    def test_cancelled_job_never_marks_result_successful(self):
        self.configure_manual()
        self.dialog.reviewed.setChecked(True)
        self.dialog.start_job('calculate')
        self.dialog.cancel_job()
        self.wait_job()
        self.assertIsNone(self.dialog.last_result)
        self.assertFalse(self.dialog.cancel_button.isEnabled())

    def test_plugin_zip_layout(self):
        script = self.repo / 'tools/build-plugin.py'
        spec = importlib.util.spec_from_file_location('build_plugin', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path = module.build(self.root / 'plugin.zip')
        with ZipFile(path) as archive:
            names = archive.namelist()
            self.assertIn('storm2flow/__init__.py', names)
            self.assertIn('storm2flow/metadata.txt', names)
            self.assertIn('storm2flow/gui/dialog.py', names)
            self.assertFalse(any('__pycache__' in n for n in names))
            self.assertTrue(all(n.startswith('storm2flow/') for n in names))
            installed = self.root / 'plugins'
            archive.extractall(installed)
        loaded = subprocess.run([sys.executable, '-c',
            'from pathlib import Path; import storm2flow; '
            'assert Path(storm2flow.__file__).resolve().parent.parent == Path.cwd(); '
            'assert storm2flow.classFactory(None).__class__.__name__ == "Storm2FlowPlugin"; '
            'print("installed plugin import: PASS")'], cwd=installed, capture_output=True, timeout=30)
        self.assertEqual(loaded.returncode, 0, loaded.stderr)

    def test_import_rejects_silent_clamping(self):
        data = json.loads((self.repo / 'examples/design_storm.json').read_text(encoding='utf-8'))
        path = self.root / 'too-small.json'
        data['unit_hydrograph']['n'] = .001
        path.write_text(json.dumps(data), encoding='utf-8')
        previous = self.dialog.n.value()
        with self.assertRaises(ValueError):
            self.dialog.apply_config(path)
        self.assertEqual(self.dialog.n.value(), previous)


if __name__ == '__main__':
    unittest.main()
