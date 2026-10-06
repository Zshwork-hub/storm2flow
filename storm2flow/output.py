"""Portable result export. CSV flow ordinates are interval means."""
from __future__ import annotations

import csv
import html
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import scipy

from .errors import InputValidationError
from .rainfall import RainfallSeries
from .runoff import RunoffResult
from .unit_hydrograph import HydrographResult


def write_csv(path: Path, headers: list[str], rows) -> None:
    # BOM permits Excel on Windows to identify UTF-8 and Chinese field names.
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def export_geopackage(source: Path, destination: Path) -> list[dict]:
    """Copy polygon and optional point/line layers, retaining their spatial CRS."""
    from osgeo import ogr
    from .spatial import require_projected_crs

    dataset = ogr.Open(str(source))
    if dataset is None:
        raise InputValidationError(f"cannot open basin vector source: {source}")
    layers = []
    spatial_metadata = []
    has_polygon = False
    for index in range(dataset.GetLayerCount()):
        layer = dataset.GetLayerByIndex(index)
        ref = layer.GetSpatialRef()
        if ref is None:
            raise InputValidationError(f"layer {layer.GetName()} has no CRS")
        require_projected_crs(ref.ExportToWkt())
        spatial_metadata.append({"layer": layer.GetName(), "crs_wkt": ref.ExportToWkt(),
                                 "authority": ref.GetAuthorityName(None),
                                 "authority_code": ref.GetAuthorityCode(None)})
        for feature in layer:
            geom = feature.GetGeometryRef()
            if geom is None or geom.IsEmpty() or not geom.IsValid():
                raise InputValidationError(f"layer {layer.GetName()} contains invalid geometry")
            if ogr.GT_Flatten(geom.GetGeometryType()) in (ogr.wkbPolygon, ogr.wkbMultiPolygon):
                has_polygon = True
        layer.ResetReading()
        layers.append(layer)
    if not has_polygon:
        raise InputValidationError("basin vector source must contain a non-empty polygon")
    output = ogr.GetDriverByName("GPKG").CreateDataSource(str(destination))
    if output is None:
        raise InputValidationError(f"cannot create GeoPackage: {destination}")
    try:
        for layer in layers:
            if output.CopyLayer(layer, layer.GetName()) is None:
                raise InputValidationError(f"failed to export layer: {layer.GetName()}")
    finally:
        output = None
        dataset = None
    return spatial_metadata


def export_results(
    destination: Path,
    config: dict,
    rainfall: RainfallSeries,
    runoff: RunoffResult,
    hydrograph: HydrographResult,
    *,
    basin_source: Path | None = None,
) -> Path:
    """Export to a new directory; refuse overwriting any existing result directory.

    Failures retain partial artifacts and failure.txt for diagnosis.
    """
    if destination.exists():
        raise InputValidationError(f"output directory already exists: {destination}")
    destination.mkdir(parents=True)
    try:
        return _export(destination, config, rainfall, runoff, hydrograph, basin_source)
    except Exception as exc:
        (destination / "failure.txt").write_text(str(exc), encoding="utf-8")
        raise


def _export(destination, config, rainfall, runoff, hydrograph, basin_source):
    # Persist the input before any plotting/spatial operation can fail.
    (destination / "parameters.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    import matplotlib
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    warnings = [
        "当前采用人工复核的流域参数；自动断面吸附和平坦区流向处理尚未完成。",
        "本次仅计算一个重现期，未进行跨重现期单调性检查。",
    ]
    spatial_metadata = []
    if basin_source is None:
        warnings.append("未提供流域空间图层，未生成 basin.gpkg；未用输入参数虚构边界。")
    else:
        spatial_metadata = export_geopackage(basin_source, destination / "basin.gpkg")

    basin = config["basin"]
    if not 0.1 <= basin["area_km2"] <= 1000:
        warnings.append("流域面积超出默认的 0.1—1000 km² 范围，需复核适用性。")
    uh = config["unit_hydrograph"]
    if not uh.get("source"):
        warnings.append("单位线 n、K 参数未登记来源，需人工核对。")

    step = rainfall.time_step_h
    starts = np.arange(rainfall.rainfall_mm.size) * step
    write_csv(destination / "rainfall.csv", ["start_time_h", "end_time_h", "rainfall_mm"],
              zip(starts, starts + step, rainfall.rainfall_mm))
    write_csv(destination / "runoff.csv",
              ["start_time_h", "end_time_h", "rainfall_mm", "initial_loss_mm", "stable_loss_mm",
               "net_rainfall_mm", "cumulative_rainfall_mm", "cumulative_net_rainfall_mm"],
              zip(starts, starts + step, runoff.rainfall_mm, runoff.initial_loss_mm,
                  runoff.stable_loss_mm, runoff.net_rainfall_mm,
                  np.cumsum(runoff.rainfall_mm), np.cumsum(runoff.net_rainfall_mm)))
    write_csv(destination / "hydrograph.csv", ["start_time_h", "end_time_h", "mean_flow_m3s"],
              zip(hydrograph.time_h, hydrograph.time_h + step, hydrograph.flow_m3s))
    write_csv(destination / "peak_flows.csv",
              ["return_period_y", "method", "peak_mean_flow_m3s", "peak_interval_start_h",
               "peak_interval_end_h", "volume_m3"],
              [[rainfall.return_period_y, "gamma", hydrograph.peak_flow_m3s,
                hydrograph.peak_time_h, hydrograph.peak_time_h + step, hydrograph.volume_m3]])
    intermediate = destination / "intermediate"
    intermediate.mkdir()
    write_csv(intermediate / "unit_response.csv", ["start_time_h", "end_time_h", "response_fraction"],
              ((i * step, (i + 1) * step, value) for i, value in enumerate(hydrograph.unit_response)))

    figure = Figure(figsize=(9, 4.5), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    edges = np.append(hydrograph.time_h, hydrograph.time_h[-1] + step)
    axis.stairs(hydrograph.flow_m3s, edges, color="#176a9c", linewidth=1.8)
    axis.set(xlabel="Time (h)", ylabel="Mean flow (m³/s)", title="storm2flow — design hydrograph")
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.2)
    figure.savefig(destination / "hydrograph.png", dpi=160)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "basin_name": basin.get("name", "未命名流域"),
        "area_km2": basin["area_km2"],
        "return_period_y": rainfall.return_period_y,
        "rainfall_source": rainfall.source,
        "time_step_h": step,
        "flow_semantics": "interval_mean",
        "total_rainfall_mm": rainfall.total_mm,
        "total_net_rainfall_mm": runoff.total_net_rainfall_mm,
        "net_rain_volume_m3": runoff.volume_m3(basin["area_km2"]),
        "hydrograph_volume_m3": hydrograph.volume_m3,
        "peak_mean_flow_m3s": hydrograph.peak_flow_m3s,
        "peak_interval_start_h": hydrograph.peak_time_h,
        "peak_interval_end_h": hydrograph.peak_time_h + step,
        "water_balance_relative_error": hydrograph.water_balance_relative_error,
        "unit_response_sum": hydrograph.unit_response_sum,
        "unit_response_truncated_fraction": 1 - hydrograph.unit_response_sum,
        "warnings": warnings,
        "spatial_layers": spatial_metadata,
        "versions": {"storm2flow": "0.1.0", "python": platform.python_version(),
                     "numpy": np.__version__, "scipy": scipy.__version__,
                     "matplotlib": matplotlib.__version__},
    }
    try:
        from osgeo import gdal
        summary["versions"]["gdal"] = gdal.VersionInfo("RELEASE_NAME")
    except ImportError:
        summary["versions"]["gdal"] = None
    try:
        from qgis.core import Qgis
        summary["versions"]["qgis"] = Qgis.QGIS_VERSION
    except ImportError:
        summary["versions"]["qgis"] = None
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    safe = lambda value: html.escape(str(value))
    warning_html = "".join(f"<li>{safe(w)}</li>" for w in warnings)
    rows = "".join(f"<tr><th>{safe(k)}</th><td>{safe(v)}</td></tr>"
                   for k, v in summary.items() if k not in ("warnings", "versions"))
    links = "".join(f'<li><a href="{p.name}">{p.name}</a></li>'
                    for p in sorted(destination.iterdir()) if p.is_file())
    report = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>storm2flow 计算报告</title>
<style>body{{font:16px/1.7 system-ui;margin:40px auto;max-width:1000px;padding:0 20px}}
th,td{{border:1px solid #ddd;padding:6px 12px;text-align:left}}table{{border-collapse:collapse}}
img{{max-width:100%}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:16px}}
.warning{{background:#fff3cf;padding:16px}}</style>
<h1>{safe(summary['basin_name'])} — 设计洪水计算报告</h1>
<p>初步筛查结果。洪峰为时段平均流量最大值；峰现时间表示对应时段的起止时间。</p>
<div class="warning"><strong>复核提示</strong><ul>{warning_html}</ul></div>
<h2>计算结果（字段名含单位）</h2><table>{rows}</table>
<h2>洪水过程线</h2><img src="hydrograph.png" alt="洪水过程线">
<h2>计算方法</h2><p>初损—稳损产流；Gamma 单位线 S(t)=gammainc(n,t/K)。
U_j=S((j+1)Δt)-S(jΔt)；Q_j=convolve(R,U)×A/(3.6Δt)。
洪量=ΣQ_j×Δt×3600，截断尾部未进行人为归一化。</p>
<h2>原始配置与参数来源</h2><pre>{safe(json.dumps(config, ensure_ascii=False, indent=2))}</pre>
<h2>运行版本</h2><pre>{safe(json.dumps(summary['versions'], ensure_ascii=False, indent=2))}</pre>
<h2>成果文件</h2><ul>{links}</ul></html>'''
    (destination / "report.html").write_text(report, encoding="utf-8")
    return destination
