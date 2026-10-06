"""Spatial-only subprocess entry for parameter review before hydrology."""
import json
from pathlib import Path

from .errors import InputValidationError
from .spatial_pipeline import analyze_dem, save_spatial_analysis


def run_preview(config_path, output_dir):
    config_path = Path(config_path).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise InputValidationError(f'output directory already exists: {output_dir}')
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or config.get('schema_version') != '1.0' or not isinstance(config.get('basin'), dict):
        raise InputValidationError('invalid spatial preview configuration')
    basin = config['basin']
    processing = config.get('processing', {})
    output_dir.mkdir(parents=True)
    (output_dir / 'parameters.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        analysis = analyze_dem(config_path.parent / basin['dem_path'], basin['outlet_xy'],
                               outlet_crs=basin['outlet_crs'],
                               radius_m=processing.get('snap_radius_m', 100),
                               threshold_cells=processing.get('stream_threshold_cells'),
                               target_crs=processing.get('target_crs'))
        save_spatial_analysis(analysis, output_dir)
    except Exception as exc:
        (output_dir / 'failure.txt').write_text(str(exc), encoding='utf-8')
        raise
    return output_dir
