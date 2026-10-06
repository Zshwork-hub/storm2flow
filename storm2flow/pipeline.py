from pathlib import Path
import json
from copy import deepcopy
from .errors import InputValidationError
from .config import load_config, _number
from .rainfall import RainfallSeries
from .runoff import calculate_net_rainfall
from .unit_hydrograph import GammaUnitHydrograph
from .output import export_results


def run_calculation(config_path: str | Path, output_dir: str | Path) -> Path:
    """Run one design storm using manual or DEM-derived basin parameters."""
    config_path = Path(config_path).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise InputValidationError(f'output directory already exists: {output_dir}')
    config = load_config(config_path)
    original = deepcopy(config)
    try:
        return _run(config_path, output_dir, config)
    except Exception as exc:
        # Do not replace export-level diagnostics if the directory already exists.
        if not output_dir.exists():
            output_dir.mkdir(parents=True)
            (output_dir / 'parameters.json').write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding='utf-8')
            (output_dir / 'failure.txt').write_text(str(exc), encoding='utf-8')
        raise


def _run(config_path, output_dir, config):
    analysis = None
    if config['basin'].get('dem_path'):
        from .spatial_pipeline import analyze_dem
        basin = config['basin']
        if not basin.get('outlet_crs') or not basin.get('outlet_xy'):
            raise InputValidationError('DEM mode requires outlet_xy and outlet_crs')
        processing = config.get('processing', {})
        analysis = analyze_dem(config_path.parent / basin['dem_path'], basin['outlet_xy'],
                               outlet_crs=basin['outlet_crs'],
                               radius_m=processing.get('snap_radius_m', 100.0),
                               threshold_cells=processing.get('stream_threshold_cells'),
                               target_crs=processing.get('target_crs'))
        automatic = {'area_km2': analysis.parameters.area_km2,
                     'main_channel_length_km': analysis.parameters.main_channel_length_km,
                     'main_channel_slope': analysis.parameters.main_channel_slope,
                     'regression_slope': analysis.parameters.regression_slope}
        basin['automatic_parameters'] = automatic
        for name in ('area_km2', 'main_channel_length_km', 'main_channel_slope'):
            if basin.get(name) is None:
                basin[name] = automatic[name]
            else:
                _number(basin[name], f'basin.{name}', positive=True)
        basin['parameter_source'] = 'DEM extraction with explicit user overrides retained'
    _number(config['basin'].get('area_km2'), 'basin.area_km2', positive=True)
    rain_config = config['rainfall']
    rainfall = RainfallSeries(rain_config['rainfall_mm'], rain_config['time_step_h'],
                              rain_config.get('return_period_y'), rain_config.get('source', 'manual'))
    runoff = calculate_net_rainfall(rainfall, config['runoff']['initial_loss_mm'],
                                   config['runoff']['stable_loss_mm_per_h'])
    model = GammaUnitHydrograph(config['unit_hydrograph']['n'], config['unit_hydrograph']['K_h'])
    hydrograph = model.convolve(runoff.net_rainfall_mm, rainfall.time_step_h, config['basin']['area_km2'])
    source = config['basin'].get('vector_path')
    source_path = config_path.parent / source if source else None
    return export_results(Path(output_dir).resolve(), config, rainfall, runoff, hydrograph,
                          basin_source=source_path, spatial_analysis=analysis)
