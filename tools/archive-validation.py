"""Archive measured P4 tables and exact source identities without copying DEMs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[1]


def archive(source, destination):
    summary = json.loads((source / 'summary.json').read_text(encoding='utf-8'))
    if destination.exists():
        raise ValueError('archive directory already exists')
    # Check that a later edit has not changed the product whose performance
    # was measured. Text hashes use LF normalization for Windows checkouts.
    commit = summary['git_commit']
    fingerprints = {}
    product_modules = ['__init__', 'config', 'errors', 'rainfall', 'runoff', 'unit_hydrograph',
                       'dem', 'spatial', 'spatial_pipeline', 'pipeline', 'output']
    for module in product_modules:
        relative = f'storm2flow/{module}.py'
        recorded = subprocess.run(['git', 'show', f'{commit}:{relative}'], cwd=REPO,
                                  capture_output=True, check=True).stdout.replace(b'\r\n', b'\n')
        current = (REPO / relative).read_bytes().replace(b'\r\n', b'\n')
        if current != recorded:
            raise ValueError(f'measured product has since changed: {relative}')
        fingerprints[relative] = hashlib.sha256(current).hexdigest()
    destination.mkdir(parents=True)
    for name in ('report.md', 'summary.json', 'synthetic.json', 'performance.json', 'performance.csv'):
        shutil.copyfile(source / name, destination / name)
    for log in sorted(source.glob('benchmark-*.log')):
        shutil.copyfile(log, destination / log.name)
    if (source / 'source_snapshot.json').exists():
        shutil.copyfile(source / 'source_snapshot.json', destination / 'source_snapshot.json')
    provenance = {'product_commit': commit, 'product_matches_measured_commit': True,
                  'product_text_sha256_lf_normalized': fingerprints,
                  'validation_source_sha256_at_archival': hashlib.sha256((REPO / 'storm2flow/validation.py').read_bytes()).hexdigest(),
                  'harness_source_sha256_at_archival': hashlib.sha256((REPO / 'tools/run-validation.py').read_bytes()).hexdigest(),
                  'note': 'Harness hash is at archival time; diagnostic fixes may follow the measurement. Product source is checked against measured Git commit.'}
    (destination / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    cases = json.loads((source / 'synthetic.json').read_text(encoding='utf-8'))
    lines = ['\n## 独立合成案例逐项结果', '', '| 案例 | 类型 | 通过 |', '|---|---|---|']
    lines.extend(f"|{case['case']}|{case['kind']}|{case['passed']}|" for case in cases)
    lines.extend(['', '上述案例输入与误差明细见 [synthetic.json](synthetic.json)，性能原始数据见 [performance.json](performance.json)。',
                  '产品源文件与测量时 Git 提交逐项核对，校验信息见 [provenance.json](provenance.json)。',
                  '真实案例状态始终单独保存为未验证，合成验收结果不替代实测精度。', ''])
    with (destination / 'report.md').open('a', encoding='utf-8') as stream:
        stream.write('\n'.join(lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    archive(args.source, args.destination)
    print(args.destination.resolve())
