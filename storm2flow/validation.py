"""Independent synthetic acceptance cases; never interpreted as observed accuracy."""
from __future__ import annotations

from math import exp, gamma
from pathlib import Path

import numpy as np
from scipy.integrate import quad

from .rainfall import RainfallSeries
from .runoff import calculate_net_rainfall
from .unit_hydrograph import GammaUnitHydrograph
from .spatial_pipeline import analyze_dem


def reference_cdf(t: float, n: float, k: float) -> float:
    """Closed forms for n=1,2; independent PDF quadrature otherwise."""
    if t <= 0:
        return 0.0
    if n == 1:
        return 1 - exp(-t / k)
    if n == 2:
        return 1 - exp(-t / k) * (1 + t / k)
    return quad(lambda x: x ** (n-1) * exp(-x/k) / (k**n * gamma(n)),
                0, t, epsabs=1e-11, epsrel=1e-11)[0]


def hydrology_case(name, rain, net_reference, *, dt, area, ia, loss, n, k):
    rainfall = RainfallSeries(np.array(rain), dt, source='synthetic acceptance')
    runoff = calculate_net_rainfall(rainfall, ia, loss)
    result = GammaUnitHydrograph(n, k).convolve(runoff.net_rainfall_mm, dt, area)
    # Reference sums use explicit scalar loops, not numpy.convolve or gammainc.
    response = [reference_cdf((i+1)*dt, n, k) - reference_cdf(i*dt, n, k)
                for i in range(len(result.unit_response))]
    expected = [sum(net_reference[i] * response[j-i]
                    for i in range(len(net_reference)) if 0 <= j-i < len(response))
                * area / (3.6*dt) for j in range(len(response)+len(net_reference)-1)]
    expected_peak = max(expected)
    ideal_volume = sum(net_reference) * area * 1000
    net_error = float(np.max(np.abs(runoff.net_rainfall_mm - net_reference)))
    ordinate_error = float(np.max(np.abs(result.flow_m3s - expected)))
    volume_error = abs(result.volume_m3 - ideal_volume) / max(ideal_volume, 1)
    reference_peak_index = int(np.argmax(expected))
    peak_time_error = abs(result.peak_time_h - reference_peak_index*dt)
    peak_error = abs(result.peak_flow_m3s - expected_peak) / max(expected_peak, 1e-12)
    return {'case': name, 'kind': 'synthetic_hydrology', 'basis': 'independent closed form / PDF quadrature',
            'inputs': {'rainfall_mm': rain, 'net_reference_mm': net_reference, 'dt_h': dt,
                       'area_km2': area, 'Ia_mm': ia, 'f_mm_per_h': loss, 'n': n, 'K_h': k},
            'peak_m3s': result.peak_flow_m3s, 'reference_peak_m3s': expected_peak,
            'peak_relative_error': peak_error, 'peak_interval_start_error_h': peak_time_error,
            'volume_m3': result.volume_m3, 'ideal_volume_m3': ideal_volume,
            'volume_relative_error': volume_error, 'net_max_absolute_error_mm': net_error,
            'flow_max_absolute_error_m3s': ordinate_error, 'unit_response_sum': result.unit_response_sum,
            'passed': bool(net_error < 1e-10 and ordinate_error < 1e-8 and peak_error < 1e-8
                           and peak_time_error < 1e-10 and volume_error < .01
                           and .999 <= result.unit_response_sum <= 1)}


def write_plane_dem(path: Path, size: int, width=30.0, height=30.0):
    from osgeo import gdal, osr
    y, x = np.indices((size, size))
    # Equal physical derivatives give a diagonal drainage path, even for
    # rectangular pixels. Elevation remains positive for benchmark sizes.
    values = 10000.0 - .02 * (x*width + y*height)
    ref = osr.SpatialReference()
    ref.ImportFromEPSG(32650)
    dataset = gdal.GetDriverByName('GTiff').Create(str(path), size, size, 1, gdal.GDT_Float64)
    dataset.SetGeoTransform((500000, width, 0, 3000000, 0, -height))
    dataset.SetProjection(ref.ExportToWkt())
    dataset.GetRasterBand(1).WriteArray(values)
    dataset = None
    return [500000 + (size-.5)*width, 3000000 - (size-.5)*height]


def spatial_case(directory: Path, size, width, height):
    path = directory / f'plane-{size}-{width}-{height}.tif'
    outlet = write_plane_dem(path, size, width, height)
    actual = analyze_dem(path, outlet, outlet_crs='EPSG:32650', radius_m=0, threshold_cells=1)
    # Exact geometric expectations specified independently of D8 functions.
    expected_area = size * size * width * height / 1e6
    expected_length = (size-1) * (width**2 + height**2)**.5 / 1000
    expected_slope = .02*(width+height)/(width**2+height**2)**.5
    errors = [abs(actual.parameters.area_km2 / expected_area - 1),
              abs(actual.parameters.main_channel_length_km / expected_length - 1),
              abs(actual.parameters.main_channel_slope / expected_slope - 1)]
    return {'case': f'plane_{size}_{width}_{height}', 'kind': 'synthetic_spatial',
            'basis': 'analytic plane geometry, stream threshold 1',
            'area_km2': actual.parameters.area_km2, 'reference_area_km2': expected_area,
            'length_km': actual.parameters.main_channel_length_km, 'reference_length_km': expected_length,
            'slope': actual.parameters.main_channel_slope, 'reference_slope': expected_slope,
            'area_relative_error': errors[0], 'length_relative_error': errors[1],
            'slope_relative_error': errors[2], 'passed': bool(errors[0] < .05 and errors[1] < .1 and errors[2] < .1)}


def synthetic_suite(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    results = [
        hydrology_case('exponential_single_pulse', [10], [10], dt=1, area=1, ia=0, loss=0, n=1, k=1),
        hydrology_case('integer_gamma_with_losses', [5,20,10], [0,13,8], dt=1, area=6.82, ia=10, loss=2, n=2, k=1.2),
        hydrology_case('fractional_gamma_half_hour', [0,2,5,9], [0,0,3,8], dt=.5, area=2, ia=3, loss=2, n=2.5, k=1.2),
        hydrology_case('zero_rainfall', [0,0,0], [0,0,0], dt=1, area=1, ia=20, loss=2, n=2.5, k=1.2),
        hydrology_case('rain_below_initial_loss', [2,3,4], [0,0,0], dt=1, area=1, ia=20, loss=2, n=2, k=1),
    ]
    for shape in ((32,30,30), (32,10,20), (64,30,30)):
        results.append(spatial_case(directory, *shape))
    pattern = np.array([1., 2., 5., 3., 1.])
    peaks = []
    for total in (60., 90., 120.):
        rain = RainfallSeries(pattern/pattern.sum()*total, 1.)
        runoff = calculate_net_rainfall(rain, 10, 2)
        peaks.append(GammaUnitHydrograph(2.5, 1.2).convolve(runoff.net_rainfall_mm, 1., 2.).peak_flow_m3s)
    results.append({'case': 'nested_storm_peak_monotonicity', 'kind': 'synthetic_property',
                    'basis': 'same pattern, nested total depths; not real return-period statistics',
                    'totals_mm': [60,90,120], 'peaks_m3s': peaks,
                    'passed': all(a <= b for a, b in zip(peaks, peaks[1:]))})
    return results
