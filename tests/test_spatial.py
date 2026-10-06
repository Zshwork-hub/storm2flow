import pytest

from storm2flow.errors import InputValidationError
from storm2flow.spatial import require_projected_crs


def test_geographic_crs_is_rejected():
    osgeo = pytest.importorskip("osgeo")
    from osgeo import osr

    geographic = osr.SpatialReference()
    geographic.ImportFromEPSG(4326)
    with pytest.raises(InputValidationError):
        require_projected_crs(geographic.ExportToWkt())


def test_metric_projected_crs_is_accepted():
    osgeo = pytest.importorskip("osgeo")
    from osgeo import osr

    projected = osr.SpatialReference()
    projected.ImportFromEPSG(32650)
    require_projected_crs(projected.ExportToWkt())
