# storm2flow

小流域设计洪水初步筛查工具。已支持 DEM 参数提取、出口吸附、平坦区排水、河网最长主河道和成果输出；QGIS 插件界面尚在开发中。

## 开发基线

- 目标运行环境：QGIS 3.44.14 自带 Python 3.12.14
- P0 算法依赖：NumPy、SciPy；成果输出依赖 Matplotlib，GeoPackage 依赖 GDAL/OGR
- P0 不依赖 rasterio、WhiteboxTools 或 QGIS

## 运行演示

在仓库目录打开 PowerShell，使用本机 QGIS Python：

```powershell
.\tools\run-qgis-python.ps1 -PythonArguments @('-m', 'storm2flow', 'examples/design_storm.json', '--output', 'results/demo')
```

生成 `results/demo/report.html`。输出目录必须不存在；再次运行使用新目录名。脚本面向 QGIS 3.44.14 / Python312，安装位置不同时通过 `-QgisRoot` 指定。退出时恢复原环境变量。

演示数据为合成参数，不能作为真实流域结果。

## DEM 空间演示

```powershell
.\tools\run-qgis-python.ps1 -PythonArguments @('tools/create-spatial-demo.py', 'results/spatial-input')
.\tools\run-qgis-python.ps1 -PythonArguments @('-m', 'storm2flow', 'results/spatial-input/parameters.json', '--output', 'results/spatial-demo')
```

上述 DEM 是米制投影的合成地形，含一个洼地。输入目录和输出目录都必须不存在。

DEM 模式在 `basin` 中设置 `dem_path`、`outlet_xy`、`outlet_crs`。坐标顺序为 x/y（经纬度则为经度/纬度），出口按指定 CRS 转换到 DEM CRS。`processing.snap_radius_m` 控制吸附距离；`stream_threshold_cells` 控制河网阈值（贡献像元数，包含本单元）。未指定阈值时建议值为有效 DEM 像元数的 0.5%，至少 2 个；阈值必须结合影像复核。

经纬度 DEM 必须指定 `processing.target_crs` 为合适的米制投影 CRS，例如 `EPSG:32650`；未指定时拒绝直接计算面积。重投影使用 GDAL 双线性高程重采样，转换后的像元尺寸写入栅格。

`area_km2`、`main_channel_length_km`、`main_channel_slope` 为 null 或省略时使用自动值；显式填写时保留用户覆盖值。报告同时保留自动参数。河道比降基于处理后高程，纵断面包含原始和填洼高程、距离及坐标；回归比降用于辅助复核，当前不自动平滑原始剖面。

最长主河道按河网内的实际累计路径长度确定，考虑非方形像元。平坦区采用向下坡/开放边界的确定性等高传播；NoData 邻接处按开放边界处理，可能截断流域，报告会提示检查。过程栅格、吸附信息和纵断面在 `intermediate/` 中，GeoPackage 含流域、多条分离多边形（如有）、主河道和两个出口点。

空间验收测试：

```powershell
.\tools\run-qgis-python.ps1 -PythonArguments @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_spatial_pipeline.py', '-v')
```

## 成果与时间定义

- `parameters.json`、`summary.json`：参数、来源、结果、运行版本和警告；
- `rainfall.csv`、`runoff.csv`：时段雨量、损失、净雨和累计值；
- `hydrograph.csv`、`peak_flows.csv`：时段平均流量、峰值所在区间和洪量；
- `hydrograph.png`、`report.html`：过程线与离线报告；
- `intermediate/unit_response.csv`：单位线响应；
- `basin.gpkg`：提供空间输入时导出。

流量代表区间平均值，洪量采用 `ΣQ×Δt×3600`。峰现时间表示峰值所在区间；图表和报告使用同一组结果。

在配置 `basin` 中增加 `vector_path`（相对于配置文件所在目录），可以导出已有流域矢量。输入必须包含非空有效多边形和米制投影 CRS。点、线图层可一起保留。面积为人工复核输入，当前不会用几何自动替换。未提供图层时在报告中明确提示空间成果缺失，不构造虚假边界。

导出失败保留已生成成果及 `failure.txt`；已有目录不会被覆盖。

## 运行测试

无需 pytest 的成果集成测试：

```powershell
.\tools\run-qgis-python.ps1 -PythonArguments @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_output_integration.py', '-v')
```

安装开发测试依赖后可运行全部测试：

```text
python -m pytest
```

在 QGIS 环境中运行时使用：

```text
D:\QGIS 3.44.14\bin\python-qgis-ltr.bat -m pytest
```
