import numpy as np

from storm2flow.unit_hydrograph import GammaUnitHydrograph


def test_non_integer_shape_parameter_is_supported():
    model = GammaUnitHydrograph(n=2.5, K_h=1.2)
    response = model.unit_response(1.0)
    assert response.size > 0
    assert 0.999 <= response.sum() <= 1.0


def test_s_curve_is_monotonic_and_bounded():
    model = GammaUnitHydrograph(n=2.5, K_h=1.2)
    values = model.s_curve(np.arange(0.0, 8.0, 1.0))
    assert values[0] == 0.0
    assert np.all(np.diff(values) >= 0)
    assert np.all((values >= 0) & (values <= 1))


def test_convolution_preserves_water_volume():
    model = GammaUnitHydrograph(n=2.5, K_h=1.2)
    result = model.convolve(np.array([0.0, 5.0, 10.0, 8.0, 3.0]), 1.0, 6.82)
    assert result.peak_flow_m3s > 0
    assert result.water_balance_relative_error < 0.01
    assert result.volume_m3 > 0
