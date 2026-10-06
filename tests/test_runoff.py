import numpy as np

from storm2flow.rainfall import RainfallSeries
from storm2flow.runoff import calculate_net_rainfall


def test_initial_and_stable_losses_are_accounted_for():
    rainfall = RainfallSeries(np.array([5.0, 20.0, 10.0]), 1.0)
    result = calculate_net_rainfall(rainfall, initial_loss_mm=10.0, stable_loss_mm_per_h=2.0)
    np.testing.assert_allclose(result.initial_loss_mm, [5.0, 5.0, 0.0])
    np.testing.assert_allclose(result.stable_loss_mm, [0.0, 2.0, 2.0])
    np.testing.assert_allclose(result.net_rainfall_mm, [0.0, 13.0, 8.0])


def test_runoff_volume_conversion():
    rainfall = RainfallSeries(np.array([10.0]), 1.0)
    result = calculate_net_rainfall(rainfall, 0.0, 0.0)
    assert result.volume_m3(2.0) == 20_000.0
