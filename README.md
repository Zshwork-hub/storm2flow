# storm2flow

小流域山洪灾害预测工具。当前实现阶段为 P0：纯 Python 水文算法基线，暂不依赖 QGIS。

## 开发基线

- 目标运行环境：QGIS 3.44.14 自带 Python 3.12.14
- P0 算法依赖：NumPy、SciPy
- P0 不依赖 rasterio、WhiteboxTools 或 QGIS

## 运行测试

```text
python -m pytest
```

在 QGIS 环境中运行时使用：

```text
D:\QGIS 3.44.14\bin\python-qgis-ltr.bat -m pytest
```
