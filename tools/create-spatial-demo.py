"""Create deterministic, explicitly synthetic DEM inputs for the spatial CLI."""
import argparse
import json
from pathlib import Path

import numpy as np
from osgeo import gdal, osr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.directory.exists():
        parser.error('input directory already exists; choose a new directory')
    args.directory.mkdir(parents=True)
    ref = osr.SpatialReference()
    ref.ImportFromEPSG(32650)
    y, x = np.indices((100, 100))
    elevation = (1000.0 - y - x).astype(float)
    elevation[45:55, 45:55] -= 30.0  # a depression to exercise fill and flat routing
    ds = gdal.GetDriverByName('GTiff').Create(str(args.directory / 'synthetic_dem.tif'),
                                             100, 100, 1, gdal.GDT_Float32)
    ds.SetProjection(ref.ExportToWkt())
    ds.SetGeoTransform((500000, 10, 0, 3000000, 0, -10))
    ds.GetRasterBand(1).SetNoDataValue(-9999)
    ds.GetRasterBand(1).WriteArray(elevation)
    ds = None
    config = json.loads((Path(__file__).parents[1] / 'examples/design_storm.json').read_text(encoding='utf-8'))
    config['basin'] = {
        'name': '合成DEM演示（非真实流域）', 'dem_path': 'synthetic_dem.tif',
        'outlet_xy': [500993, 2999007], 'outlet_crs': 'EPSG:32650',
        'area_km2': None, 'main_channel_length_km': None, 'main_channel_slope': None,
    }
    config['processing'] = {'stream_threshold_cells': 50, 'snap_radius_m': 20}
    (args.directory / 'parameters.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    print(args.directory.resolve())


if __name__ == '__main__':
    main()
