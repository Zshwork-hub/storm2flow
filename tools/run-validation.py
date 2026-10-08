"""P4 reproducible synthetic acceptance and fresh-process DEM performance."""
import argparse
import csv
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def peak_working_set_mb():
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    data = Counters()
    data.cb = ctypes.sizeof(data)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(data), data.cb):
        return None
    return data.PeakWorkingSetSize / 1024**2


def worker(args):
    from storm2flow.validation import write_plane_dem
    from storm2flow.pipeline import run_calculation
    import storm2flow, numpy, scipy
    from osgeo import gdal
    directory = args.output.resolve()
    directory.mkdir(parents=True)
    outlet = write_plane_dem(directory / 'dem.tif', args.worker_size)
    config = json.loads((REPO / 'examples/design_storm.json').read_text(encoding='utf-8'))
    config['basin'] = {'name': f'性能合成DEM {args.worker_size}', 'dem_path': 'dem.tif',
                       'outlet_xy': outlet, 'outlet_crs': 'EPSG:32650'}
    config['processing'] = {'snap_radius_m': 0, 'stream_threshold_cells': None}
    path = directory / 'config.json'
    path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
    start = time.perf_counter()
    cpu = time.process_time()
    output = run_calculation(path, directory / 'results')
    elapsed = time.perf_counter() - start
    cpu_elapsed = time.process_time() - cpu
    summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    expected_area = args.worker_size**2 * 30**2 / 1e6
    result = {'size': args.worker_size, 'cells': args.worker_size**2,
              'area_km2': summary['area_km2'], 'expected_area_km2': expected_area,
              'area_relative_error': abs(summary['area_km2']/expected_area-1),
              'pipeline_wall_s': elapsed, 'cpu_s': cpu_elapsed,
              'peak_working_set_mb': peak_working_set_mb(),
              'volume_relative_error': summary['water_balance_relative_error'],
              'versions': summary['versions'], 'passed': bool(elapsed < 300
                  and abs(summary['area_km2']/expected_area-1) < .05
                  and summary['water_balance_relative_error'] < .01)}
    (directory / 'measurement.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


def run(args):
    from storm2flow.validation import synthetic_suite
    if args.output.exists():
        raise ValueError('validation directory already exists; use a new directory')
    directory = args.output.resolve()
    directory.mkdir(parents=True)
    tracked_inputs = [REPO / 'tools/run-validation.py', REPO / 'examples/design_storm.json']
    tracked_inputs.extend(sorted((REPO / 'storm2flow').glob('*.py')))
    (directory / 'source_snapshot.json').write_text(json.dumps({
        str(path.relative_to(REPO)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tracked_inputs}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Running independent synthetic cases...', flush=True)
    cases = synthetic_suite(directory / 'synthetic')
    (directory / 'synthetic.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    samples = []
    for size in args.sizes:
        for repeat in range(args.repeats):
            print(f'Benchmark {size} x {size}, repetition {repeat+1}/{args.repeats}...', flush=True)
            case_dir = directory / f'benchmark-{size}-{repeat+1}'
            start = time.perf_counter()
            try:
                child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker-size', str(size),
                                        '--output', str(case_dir)], cwd=REPO, capture_output=True,
                                       timeout=args.timeout)
                (directory / f'benchmark-{size}-{repeat+1}.log').write_bytes(child.stdout + child.stderr)
                if child.returncode != 0:
                    measurement = {'size': size, 'repeat': repeat+1, 'passed': False,
                                   'error': f'worker exit {child.returncode}; see log'}
                else:
                    measurement = json.loads((case_dir / 'measurement.json').read_text(encoding='utf-8'))
            except subprocess.TimeoutExpired as exc:
                (directory / f'benchmark-{size}-{repeat+1}.log').write_bytes(
                    (exc.stdout or b'') + (exc.stderr or b'') + b'\nWorker timeout.\n')
                measurement = {'size': size, 'repeat': repeat+1, 'passed': False,
                               'error': f'worker timed out after {args.timeout}s'}
            measurement['fresh_process_wall_s'] = time.perf_counter() - start
            measurement['repeat'] = repeat+1
            samples.append(measurement)
            (directory / 'performance.json').write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"Finished: {measurement.get('pipeline_wall_s', 'failed')} s, peak memory {measurement.get('peak_working_set_mb')} MB", flush=True)
    table = []
    for size in args.sizes:
        selected = [m for m in samples if m['size'] == size]
        successes = [m for m in selected if 'pipeline_wall_s' in m]
        times = [m['pipeline_wall_s'] for m in successes]
        table.append({'size': size, 'cells': size**2, 'runs': len(selected),
                      'pipeline_median_s': statistics.median(times) if times else None,
                      'pipeline_min_s': min(times) if times else None,
                      'pipeline_max_s': max(times) if times else None,
                      'fresh_process_max_s': max(m['fresh_process_wall_s'] for m in selected),
                      'peak_working_set_mb': max((m['peak_working_set_mb'] for m in successes
                                                 if m['peak_working_set_mb'] is not None), default=None),
                      'passed': all(m['passed'] for m in selected)})
    with (directory / 'performance.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    summary = {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
               'status': 'synthetic_and_performance_only', 'real_case_validation': 'not_performed_no_data',
               'git_commit': subprocess.run(['git','rev-parse','HEAD'],cwd=REPO,capture_output=True,text=True).stdout.strip(),
               'working_tree_dirty': bool(subprocess.run(['git','status','--porcelain'],cwd=REPO,capture_output=True,text=True).stdout.strip()),
               'host': {'os': platform.platform(), 'python': platform.python_version(), 'logical_cpus': os.cpu_count()},
               'synthetic_cases': len(cases), 'synthetic_passed': sum(c['passed'] for c in cases),
               'performance': table, 'performance_samples': samples,
               'passed': all(c['passed'] for c in cases) and all(m['passed'] for m in samples)}
    (directory / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# P4 合成验证与性能报告', '',
             '真实案例尚未验证：当前没有实测/独立计算基准和完整案例输入。不能据此宣称真实洪峰误差低于 20%。', '',
             f"合成验收：{summary['synthetic_passed']}/{summary['synthetic_cases']} 通过。", '',
             '| DEM 规模 | 次数 | 流水线中位数(s) | 最慢(s) | 含启动最长(s) | 峰值工作集(MB) | 通过 |',
             '|---|---:|---:|---:|---:|---:|---|']
    for row in table:
        fmt = lambda key: f"{row[key]:.2f}" if row[key] is not None else '不可用'
        lines.append(f"|{row['size']}×{row['size']}|{row['runs']}|{fmt('pipeline_median_s')}|{fmt('pipeline_max_s')}|{fmt('fresh_process_max_s')}|{fmt('peak_working_set_mb')}|{row['passed']}|")
    lines.extend(['', '口径：独立子进程；流水线时间含 DEM 分析、水文计算、栅格/矢量/CSV/PNG/HTML 输出，不含导入依赖和创建输入 DEM；含启动时间同时记录。',
                  '峰值工作集为 Windows 报告的进程整个生命周期峰值，包含依赖与输入生成，不等同于机器剩余内存。',
                  '基准为规则倾斜合成地形，不能保证复杂真实地形同样耗时；单机少量重复不构成统计置信区间。',
                  '洪水参考使用指数/整数 Gamma 闭式解和非整数 PDF 数值积分；时间口径与产品一致，按区间起点离散降雨响应，不用于证明区间内均匀降雨连续解的精度。',
                  '', '详细值见 synthetic.json、performance.json、performance.csv 和 summary.json。'])
    (directory / 'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(f'Validation report: {directory / "report.md"}', flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sizes', type=int, nargs='+', default=[128,256,512,1024])
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=360)
    parser.add_argument('--worker-size', type=int)
    arguments = parser.parse_args()
    if arguments.repeats < 1 or arguments.timeout < 1 or any(s < 2 for s in arguments.sizes):
        parser.error('repeats/timeout must be positive and DEM sizes must be >=2')
    if arguments.worker_size:
        worker(arguments)
    else:
        raise SystemExit(run(arguments))
