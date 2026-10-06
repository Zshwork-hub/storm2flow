# storm2flow

小流域设计洪水初步筛查工具。当前支持手动复核参数的计算和成果输出；自动出口吸附、平坦区流向和 QGIS 界面尚在开发中。

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
