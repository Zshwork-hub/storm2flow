import argparse
from .pipeline import run_calculation


def main():
    parser = argparse.ArgumentParser(description='storm2flow design flood calculation')
    parser.add_argument('config', help='UTF-8 parameters JSON')
    parser.add_argument('--output', required=True, help='new result directory')
    parser.add_argument('--spatial-preview', action='store_true', help='extract spatial parameters only')
    args = parser.parse_args()
    try:
        if args.spatial_preview:
            from .preview import run_preview
            result = run_preview(args.config, args.output)
        else:
            result = run_calculation(args.config, args.output)
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(1, f'Calculation failed: {exc}\n')
    print(f'Results: {result}')


if __name__ == '__main__':
    main()
