from importlib import import_module

from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import Qgis


class Storm2FlowPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        if self.action is not None:
            return
        self.action = QAction('storm2flow 小流域设计洪水', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu('storm2flow', self.action)
        self.iface.addToolBarIcon(self.action)

    def run(self):
        if Qgis.QGIS_VERSION_INT != 34414:
            QMessageBox.warning(self.iface.mainWindow(), '版本检查', '当前试用版仅验证 QGIS 3.44.14，请使用该版本。')
            return
        missing = []
        for name in ('numpy', 'scipy', 'matplotlib', 'osgeo.gdal'):
            try:
                import_module(name)
            except (ImportError, OSError) as exc:
                missing.append(f'{name}: {exc}')
        if missing:
            QMessageBox.warning(self.iface.mainWindow(), '依赖检查', 'QGIS Python 依赖不可用：\n' + '\n'.join(missing))
            return
        if self.dialog is None:
            from .gui.dialog import StormDialog
            self.dialog = StormDialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def unload(self):
        if self.dialog is not None:
            self.dialog.shutdown()
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        if self.action is not None:
            self.iface.removePluginMenu('storm2flow', self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
