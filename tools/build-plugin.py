"""Build a QGIS ZIP with one storm2flow top-level plugin directory."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build(destination):
    package = Path(__file__).parents[1] / 'storm2flow'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for source in sorted(package.rglob('*')):
            if source.is_file() and '__pycache__' not in source.parts and source.suffix in ('.py', '.ui', '.txt'):
                archive.write(source, Path('storm2flow') / source.relative_to(package))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist/storm2flow-0.2.0.zip'))
    print(build(parser.parse_args().output).resolve())
