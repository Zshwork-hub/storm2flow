from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from qgis.PyQt.QtCore import QProcess, QProcessEnvironment, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QWidget, QLabel, QLineEdit, QPushButton, QComboBox, QDoubleSpinBox, QSpinBox,
    QPlainTextEdit, QCheckBox, QFileDialog, QMessageBox, QProgressBar, QScrollArea)
from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsVectorLayer, QgsProject
from qgis.gui import QgsProjectionSelectionWidget, QgsMapToolEmitPoint


def number(minimum=0, maximum=1e9, value=0, decimals=4):
    field = QDoubleSpinBox()
    field.setRange(minimum, maximum)
    field.setDecimals(decimals)
    field.setValue(value)
    field.setKeyboardTracking(False)
    return field


class StormDialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_log)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.job = None
        self.last_result = None
        self.preview_result = None
        self.spatial_result = None
        self.pick_tool = None
        self.previous_tool = None
        self.cancelled = False
        self.setWindowTitle('storm2flow · 小流域设计洪水')
        self.resize(820, 740)
        layout = QVBoxLayout(self)
        banner = QLabel('设计洪水初步筛查 · 先复核流域与参数，再计算和导出。默认损失与单位线参数为示例值，请核对来源。')
        banner.setWordWrap(True)
        layout.addWidget(banner)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.basin_form = self.page('1 流域与出口')
        self.name = QLineEdit()
        self.mode = QComboBox()
        self.mode.addItems(['DEM 自动提取', '手动流域参数'])
        self.basin_form.addRow('流域名称', self.name)
        self.basin_form.addRow('参数模式', self.mode)
        self.dem_path = QLineEdit()
        self.basin_form.addRow('DEM 文件', self.path_row(self.dem_path, 'dem'))
        self.x = number(-1e9, value=0, decimals=6)
        self.y = number(-1e9, value=0, decimals=6)
        self.basin_form.addRow('出口 X / 经度', self.x)
        self.basin_form.addRow('出口 Y / 纬度', self.y)
        self.outlet_crs = QgsProjectionSelectionWidget()
        self.outlet_crs.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        self.basin_form.addRow('出口坐标系', self.outlet_crs)
        self.pick_button = QPushButton('在 QGIS 地图上选择出口')
        self.pick_button.clicked.connect(self.pick_outlet)
        self.basin_form.addRow(self.pick_button)
        self.reproject = QCheckBox('将 DEM 重投影到下列米制坐标系')
        self.target_crs = QgsProjectionSelectionWidget()
        self.target_crs.setCrs(QgsCoordinateReferenceSystem())
        self.basin_form.addRow(self.reproject)
        self.basin_form.addRow('DEM 目标坐标系', self.target_crs)
        self.radius = number(value=100, decimals=1)
        self.threshold = QSpinBox()
        self.threshold.setRange(0, 1_000_000_000)
        self.threshold.setSpecialValueText('自动建议（需复核）')
        self.basin_form.addRow('吸附半径（m）', self.radius)
        self.basin_form.addRow('河网阈值（贡献像元）', self.threshold)
        self.preview_button = QPushButton('提取并预览流域参数')
        self.preview_button.clicked.connect(lambda: self.start_job('preview'))
        self.basin_form.addRow(self.preview_button)
        self.area = number(decimals=6)
        self.length = number(decimals=6)
        self.slope = number(maximum=1, decimals=8)
        self.basin_form.addRow('流域面积（km²）', self.area)
        self.basin_form.addRow('主河道长度（km）', self.length)
        self.basin_form.addRow('主河道比降（无量纲）', self.slope)
        self.reviewed = QCheckBox('已查看出口、流域和主河道，确认以上参数（允许人工修正）')
        self.reviewed.setEnabled(False)
        self.basin_form.addRow(self.reviewed)
        self.spatial_info = QLabel('尚未提取空间参数。')
        self.spatial_info.setWordWrap(True)
        self.basin_form.addRow(self.spatial_info)

        rain_form = self.page('2 暴雨与产流')
        self.rain_source = QLineEdit()
        self.return_period = QSpinBox()
        self.return_period.setRange(1, 10000)
        self.return_period.setValue(20)
        self.time_step = number(minimum=.0001, maximum=24, value=1)
        self.rain_values = QPlainTextEdit()
        self.rain_values.setPlaceholderText('逐时段雨量（mm），用逗号、空格或换行分隔。例：12, 35, 58, 42, 20, 8')
        self.rain_values.setMaximumHeight(180)
        self.initial_loss = number(value=20)
        self.stable_loss = number(value=2)
        rain_form.addRow('暴雨参数来源', self.rain_source)
        rain_form.addRow('重现期（年）', self.return_period)
        rain_form.addRow('时间步长（h）', self.time_step)
        rain_form.addRow('每时段雨量（mm）', self.rain_values)
        rain_form.addRow('初损 Ia（mm）', self.initial_loss)
        rain_form.addRow('稳损 f（mm/h）', self.stable_loss)
        rain_form.addRow(QLabel('总历时按时段数 × 时间步长计算。雨量是每段深度，不能输入累计雨量。'))

        model_form = self.page('3 汇流与成果')
        self.n = number(minimum=.01, maximum=100, value=2.5)
        self.k = number(minimum=.001, maximum=10000, value=1.2)
        self.uh_source = QLineEdit()
        self.output_parent = QLineEdit()
        model_form.addRow('Gamma 形状 n', self.n)
        model_form.addRow('尺度 K（h）', self.k)
        model_form.addRow('n、K 参数来源', self.uh_source)
        model_form.addRow('成果保存目录', self.path_row(self.output_parent, 'output'))
        self.import_button = QPushButton('导入已有参数 JSON')
        self.import_button.clicked.connect(self.import_config)
        model_form.addRow(self.import_button)
        self.summary = QLabel('计算完成后显示洪峰、峰值区间、洪量和复核提示。')
        self.summary.setWordWrap(True)
        model_form.addRow(self.summary)
        self.report_button = QPushButton('打开计算报告')
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self.open_report)
        self.layers_button = QPushButton('加载最新流域、主河道和出口图层')
        self.layers_button.setEnabled(False)
        self.layers_button.clicked.connect(self.load_layers)
        model_form.addRow(self.report_button)
        model_form.addRow(self.layers_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        layout.addWidget(self.log)
        buttons = QHBoxLayout()
        self.run_button = QPushButton('计算设计洪水并导出')
        self.run_button.clicked.connect(lambda: self.start_job('calculate'))
        self.cancel_button = QPushButton('取消计算')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_job)
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.mode.currentIndexChanged.connect(self.update_mode)
        for field in (self.x, self.y, self.radius, self.threshold):
            field.valueChanged.connect(self.invalidate_preview)
        self.dem_path.textChanged.connect(self.invalidate_preview)
        self.outlet_crs.crsChanged.connect(self.invalidate_preview)
        self.target_crs.crsChanged.connect(self.invalidate_preview)
        self.reproject.toggled.connect(self.invalidate_preview)
        self.reproject.toggled.connect(self.update_mode)
        for field in (self.area, self.length, self.slope):
            field.valueChanged.connect(lambda: self.reviewed.setChecked(False))
        self.update_mode()

    def page(self, title):
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        return form

    def path_row(self, edit, kind):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit)
        button = QPushButton('选择…')
        button.clicked.connect(lambda: self.browse(edit, kind))
        row.addWidget(button)
        return widget

    def browse(self, edit, kind):
        if kind == 'output':
            path = QFileDialog.getExistingDirectory(self, '选择成果保存目录')
        else:
            path, _ = QFileDialog.getOpenFileName(self, '选择 DEM', '', 'DEM (*.tif *.tiff);;所有文件 (*)')
        if path:
            edit.setText(path)

    def update_mode(self, *_):
        automatic = self.mode.currentIndex() == 0
        for field in (self.dem_path.parentWidget(), self.x, self.y, self.outlet_crs,
                      self.radius, self.threshold, self.reproject, self.preview_button, self.pick_button):
            field.setEnabled(automatic)
        self.target_crs.setEnabled(automatic and self.reproject.isChecked())
        self.invalidate_preview()

    def invalidate_preview(self, *_):
        self.preview_result = None
        self.spatial_result = None
        self.layers_button.setEnabled(False)
        self.reviewed.setChecked(False)
        self.reviewed.setEnabled(self.mode.currentIndex() == 1)
        self.spatial_info.setText('空间设置已改变，请重新提取。' if self.mode.currentIndex() == 0 else '使用人工输入的流域参数。')

    def pick_outlet(self):
        canvas = self.iface.mapCanvas()
        self.restore_map_tool()
        self.previous_tool = canvas.mapTool()
        self.pick_tool = QgsMapToolEmitPoint(canvas)
        self.pick_tool.canvasClicked.connect(self.point_picked)
        canvas.setMapTool(self.pick_tool)
        self.log.appendPlainText('请在 QGIS 地图上点击控制断面。')

    def point_picked(self, point, _button):
        self.x.setValue(point.x())
        self.y.setValue(point.y())
        self.outlet_crs.setCrs(self.iface.mapCanvas().mapSettings().destinationCrs())
        self.restore_map_tool()
        self.raise_()

    def restore_map_tool(self):
        if self.pick_tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is self.pick_tool:
                if self.previous_tool is not None:
                    canvas.setMapTool(self.previous_tool)
                else:
                    canvas.unsetMapTool(self.pick_tool)
            self.pick_tool.deleteLater()
        self.pick_tool = self.previous_tool = None

    def build_config(self, kind='calculate'):
        from ..errors import InputValidationError
        if not self.name.text().strip():
            raise InputValidationError('请填写流域名称。')
        if kind == 'preview' and self.mode.currentIndex() != 0:
            raise InputValidationError('手动参数模式无需提取 DEM。')
        basin = {'name': self.name.text().strip(), 'parameter_source': '用户复核'}
        processing = {}
        if self.mode.currentIndex() == 0:
            dem = Path(self.dem_path.text())
            if not dem.is_file():
                raise InputValidationError('请选择存在的 DEM 文件。')
            crs = self.outlet_crs.crs()
            if not crs.isValid():
                raise InputValidationError('请选择出口坐标系。')
            basin.update(dem_path=str(dem.resolve()), outlet_xy=[self.x.value(), self.y.value()],
                         outlet_crs=crs.authid() or crs.toWkt())
            processing.update(snap_radius_m=self.radius.value(), stream_threshold_cells=self.threshold.value() or None)
            if self.reproject.isChecked():
                target = self.target_crs.crs()
                if not target.isValid() or target.isGeographic():
                    raise InputValidationError('DEM 目标必须为有效米制投影坐标系。')
                processing['target_crs'] = target.authid() or target.toWkt()
        if kind == 'preview':
            return {'schema_version': '1.0', 'basin': basin, 'processing': processing}
        rainfall = [float(token) for token in re.split(r'[\s,，;；]+', self.rain_values.toPlainText().strip()) if token]
        if not rainfall or any(not math.isfinite(v) or v < 0 for v in rainfall):
            raise InputValidationError('请输入有限、非负的逐时段雨量。')
        if not self.rain_source.text().strip() or not self.uh_source.text().strip():
            raise InputValidationError('请填写暴雨和单位线参数来源；默认值仅供演示。')
        if kind == 'calculate':
            if not self.reviewed.isChecked():
                raise InputValidationError('请先提取并复核空间参数，再勾选确认。手动模式也需确认参数。')
            if self.area.value() <= 0 or self.length.value() <= 0 or self.slope.value() <= 0:
                raise InputValidationError('面积、主河道长度和比降必须大于零。')
            basin.update(area_km2=self.area.value(), main_channel_length_km=self.length.value(),
                         main_channel_slope=self.slope.value())
        config = {'schema_version': '1.0', 'basin': basin, 'processing': processing,
                  'rainfall': {'source': self.rain_source.text().strip(), 'return_period_y': self.return_period.value(),
                               'time_step_h': self.time_step.value(), 'duration_h': len(rainfall)*self.time_step.value(),
                               'rainfall_mm': rainfall},
                  'runoff': {'initial_loss_mm': self.initial_loss.value(), 'stable_loss_mm_per_h': self.stable_loss.value()},
                  'unit_hydrograph': {'n': self.n.value(), 'K_h': self.k.value(), 'source': self.uh_source.text().strip()}}
        return config

    def spatial_signature(self):
        return (self.mode.currentIndex(), self.dem_path.text(), self.x.value(), self.y.value(),
                self.outlet_crs.crs().toWkt(), self.reproject.isChecked(), self.target_crs.crs().toWkt(),
                self.radius.value(), self.threshold.value())

    def start_job(self, kind):
        if self.process.state() != QProcess.NotRunning:
            return
        try:
            config = self.build_config(kind)
            self.restore_map_tool()
            parent = Path(self.output_parent.text())
            if not self.output_parent.text().strip() or not parent.is_dir():
                raise ValueError('请选择已有的成果保存目录。')
            identifier = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]
            job_dir = parent / '.storm2flow-jobs' / identifier
            job_dir.mkdir(parents=True)
            config_path = job_dir / 'parameters.json'
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            result = parent / (('空间预览-' if kind == 'preview' else '设计洪水-') + identifier)
            prefix = Path(QgsApplication.prefixPath())
            python = prefix.parent.parent / 'bin/python.exe'
            if not python.is_file():
                raise ValueError('未找到 QGIS 自带 Python，请核对 QGIS 安装环境。')
            environment = QProcessEnvironment.systemEnvironment()
            python_path = str(Path(__file__).resolve().parents[2])
            old_path = environment.value('PYTHONPATH')
            environment.insert('PYTHONPATH', python_path + (';' + old_path if old_path else ''))
            environment.insert('PYTHONHOME', sys.prefix)
            environment.insert('PYTHONIOENCODING', 'utf-8')
            environment.insert('MPLCONFIGDIR', str(job_dir / 'mpl-cache'))
            self.process.setProcessEnvironment(environment)
            self.process.setWorkingDirectory(str(job_dir))
            args = ['-m', 'storm2flow', str(config_path), '--output', str(result)]
            if kind == 'preview':
                args.append('--spatial-preview')
            self.job = (kind, result, self.spatial_signature())
            self.cancelled = False
            self.set_busy(True)
            self.log.clear()
            self.log.appendPlainText('正在提取空间参数…' if kind == 'preview' else '正在计算并导出成果…')
            self.process.start(str(python), args)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '输入检查', str(exc))

    def set_busy(self, busy):
        self.tabs.setEnabled(not busy)
        self.run_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.progress.setRange(0, 0 if busy else 1)
        self.progress.setValue(0 if busy else 1)

    def read_log(self):
        message = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace').strip()
        if message:
            self.log.appendPlainText(message)

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.set_busy(False)
            self.job = None
            self.log.appendPlainText('计算进程无法启动，请核对 QGIS Python 安装路径。')

    def finished(self, code, status):
        self.read_log()
        self.set_busy(False)
        job, self.job = self.job, None
        if job is None:
            return
        kind, result, signature = job
        if self.cancelled or code != 0 or status != QProcess.NormalExit:
            self.log.appendPlainText('计算已取消。已生成的文件保留供检查。' if self.cancelled else '计算失败，请查看上方消息及输出目录中的 failure.txt。')
            return
        try:
            if kind == 'preview':
                if signature != self.spatial_signature():
                    self.log.appendPlainText('空间输入已变化，本次预览不用于当前参数，请重新提取。')
                    return
                data = json.loads((result / 'spatial_analysis.json').read_text(encoding='utf-8'))
                parameters = data['automatic_parameters']
                for field, key in ((self.area, 'area_km2'), (self.length, 'main_channel_length_km'), (self.slope, 'main_channel_slope')):
                    if not field.minimum() <= parameters[key] <= field.maximum():
                        raise ValueError(f'自动参数 {key} 超出界面可编辑范围，请使用 CLI 或复核输入。')
                self.area.setValue(parameters['area_km2'])
                self.length.setValue(parameters['main_channel_length_km'])
                self.slope.setValue(parameters['main_channel_slope'])
                self.preview_result = result
                self.spatial_result = result
                self.reviewed.setEnabled(True)
                self.reviewed.setChecked(False)
                outlet = data['outlet']
                self.spatial_info.setText(f"出口偏移 {outlet['offset_m']:.2f} m；回归比降 {parameters['regression_slope']:.6f}。\n"
                                          + '\n'.join(data['warnings']))
                self.layers_button.setEnabled(True)
                self.log.appendPlainText('提取完成。可在成果页加载图层，查看出口和主河道后确认参数。')
            else:
                data = json.loads((result / 'summary.json').read_text(encoding='utf-8'))
                self.last_result = result
                self.spatial_result = result if (result / 'basin.gpkg').exists() else None
                self.summary.setText(f"时段平均洪峰：{data['peak_mean_flow_m3s']:.3f} m³/s\n"
                                     f"峰值区间：{data['peak_interval_start_h']:.2f}—{data['peak_interval_end_h']:.2f} h\n"
                                     f"洪量：{data['hydrograph_volume_m3']:.1f} m³\n" + '\n'.join(data['warnings']))
                self.report_button.setEnabled(True)
                self.layers_button.setEnabled((result / 'basin.gpkg').exists())
                self.tabs.setCurrentIndex(2)
                self.log.appendPlainText(f'计算完成：{result}')
        except (ValueError, KeyError, OSError) as exc:
            self.log.appendPlainText(f'成果读取失败：{exc}')

    def cancel_job(self):
        if self.process.state() != QProcess.NotRunning:
            self.cancelled = True
            self.process.kill()

    def open_report(self):
        if self.last_result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_result / 'report.html')))

    def load_layers(self):
        result = self.spatial_result
        if result is None:
            return
        for name in ('basin', 'main_channel', 'outlets'):
            layer = QgsVectorLayer(f'{result / "basin.gpkg"}|layername={name}', f'storm2flow · {name}', 'ogr')
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入参数', '', 'JSON (*.json)')
        if path:
            try:
                self.apply_config(Path(path))
            except (ValueError, KeyError, OSError, TypeError) as exc:
                QMessageBox.warning(self, '参数读取失败', str(exc))

    def apply_config(self, path):
        from ..config import load_config
        data = load_config(path)
        basin, rain = data['basin'], data['rainfall']
        # Validate representability before changing any widgets. Spin boxes
        # clamp/round silently unless the adapter explicitly checks their limits.
        checks = [(self.time_step, rain['time_step_h'], '时间步长'),
                  (self.initial_loss, data['runoff']['initial_loss_mm'], '初损'),
                  (self.stable_loss, data['runoff']['stable_loss_mm_per_h'], '稳损'),
                  (self.n, data['unit_hydrograph']['n'], 'n'),
                  (self.k, data['unit_hydrograph']['K_h'], 'K')]
        processing = data.get('processing', {})
        checks.extend([(self.radius, processing.get('snap_radius_m', 100), '吸附半径'),
                       (self.threshold, processing.get('stream_threshold_cells') or 0, '河网阈值'),
                       (self.return_period, rain.get('return_period_y') or 20, '重现期')])
        checks.extend((field, basin.get(key) or 0, key) for field, key in
                      ((self.area, 'area_km2'), (self.length, 'main_channel_length_km'), (self.slope, 'main_channel_slope')))
        if basin.get('dem_path'):
            checks.extend([(self.x, basin['outlet_xy'][0], '出口 X'), (self.y, basin['outlet_xy'][1], '出口 Y')])
        for field, value, label in checks:
            if not isinstance(value, (float, int)) or not math.isfinite(value) or not field.minimum() <= value <= field.maximum():
                raise ValueError(f'{label} 超出界面范围；参数未导入，请使用 CLI 或修正文件。')
            decimals = field.decimals() if isinstance(field, QDoubleSpinBox) else 0
            if not math.isclose(value, round(value, decimals), rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f'{label} 超出界面精度；参数未导入，请使用 CLI 或修正文件。')
        self.name.setText(basin.get('name', ''))
        self.mode.setCurrentIndex(0 if basin.get('dem_path') else 1)
        if basin.get('dem_path'):
            self.dem_path.setText(str((path.parent / basin['dem_path']).resolve()))
            self.x.setValue(basin['outlet_xy'][0])
            self.y.setValue(basin['outlet_xy'][1])
            self.outlet_crs.setCrs(QgsCoordinateReferenceSystem(basin['outlet_crs']))
        processing = data.get('processing', {})
        self.radius.setValue(processing.get('snap_radius_m', 100))
        self.threshold.setValue(processing.get('stream_threshold_cells') or 0)
        self.reproject.setChecked(bool(processing.get('target_crs')))
        self.target_crs.setCrs(QgsCoordinateReferenceSystem(processing.get('target_crs', '')))
        for field, key in ((self.area, 'area_km2'), (self.length, 'main_channel_length_km'), (self.slope, 'main_channel_slope')):
            field.setValue(basin.get(key) or 0)
        self.rain_source.setText(rain.get('source', ''))
        self.return_period.setValue(rain.get('return_period_y') or 20)
        self.time_step.setValue(rain['time_step_h'])
        self.rain_values.setPlainText(', '.join(str(v) for v in rain['rainfall_mm']))
        self.initial_loss.setValue(data['runoff']['initial_loss_mm'])
        self.stable_loss.setValue(data['runoff']['stable_loss_mm_per_h'])
        self.n.setValue(data['unit_hydrograph']['n'])
        self.k.setValue(data['unit_hydrograph']['K_h'])
        self.uh_source.setText(data['unit_hydrograph'].get('source', ''))
        self.invalidate_preview()

    def shutdown(self):
        self.cancel_job()
        self.process.waitForFinished(3000)
        self.restore_map_tool()

    def closeEvent(self, event):
        if self.process.state() != QProcess.NotRunning:
            self.log.appendPlainText('计算仍在运行，请先取消计算后关闭。')
            event.ignore()
            return
        self.restore_map_tool()
        event.accept()
