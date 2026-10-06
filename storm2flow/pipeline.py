from pathlib import Path
from .config import load_config, _number
from .rainfall import RainfallSeries
from .runoff import calculate_net_rainfall
from .unit_hydrograph import GammaUnitHydrograph
from .output import export_results


def run_calculation(config_path: str | Path, output_dir: str | Path) -> Path:
    """Run one design storm with explicitly supplied, reviewed basin parameters."""
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
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
                          basin_source=source_path)
