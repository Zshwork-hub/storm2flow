"""storm2flow hydrology core."""

from importlib import import_module

__version__ = "0.2.0"


def classFactory(iface):
    """QGIS plugin entry point; keep numerical dependencies lazy."""
    from .plugin import Storm2FlowPlugin
    return Storm2FlowPlugin(iface)


def __getattr__(name):
    modules = {"RainfallSeries": "rainfall", "RunoffResult": "runoff",
               "calculate_net_rainfall": "runoff", "HydrographResult": "unit_hydrograph",
               "GammaUnitHydrograph": "unit_hydrograph"}
    if name in modules:
        return getattr(import_module(f'.{modules[name]}', __name__), name)
    raise AttributeError(name)

__all__ = [
    "RainfallSeries",
    "RunoffResult",
    "calculate_net_rainfall",
    "HydrographResult",
    "GammaUnitHydrograph",
]
