"""Build isolated release/profile variants; deterministic independent stream oracle.

Usage: python validate.py --compiler PATH --output NEW_DIRECTORY
Run only after verifying no benchmark is active. No UNI performance sweep here.
"""
import argparse
import hashlib
import itertools
import json
import random
import shutil
import subprocess
from pathlib import Path


def oracle(graph, colors, k):
    best = None
    for p in itertools.permutations(range(len(colors[0])), k):
        if p[0] != min(p):
            continue
        if not any(len({c[v] for v in p}) == k for c in colors):
            continue
        edges = list(zip(p, p[1:] + p[:1]))
        if all(e in graph for e in edges):
            w = sum(graph[e] for e in edges)
            if best is None or w < best:
                best = w
    return best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    src = Path(__file__).resolve().parent
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    compiler = args.compiler.resolve()
    records = []

    def run(command, name, timeout=180):
        p = subprocess.run(list(map(str, command)), capture_output=True, timeout=timeout)
        (out / (name + '.log')).write_bytes(p.stdout + p.stderr)
        if p.returncode:
            raise RuntimeError(f'{name} failed: inspect saved log')
        print(name, 'PASS', flush=True)
        records.append({'name': name, 'command': list(map(str, command)), 'returncode': p.returncode})
        return p.stdout.decode('utf-8')

    for name in ['libc++.dll', 'libunwind.dll', 'libwinpthread-1.dll']:
        if (compiler.parent / name).exists():
            shutil.copy2(compiler.parent / name, out / name)
    objects = []
    for name in ['paper_batch_scheduler', 'paper_batch_reference_model']:
        obj = out / (name + '.o')
        run([compiler, '-O3', '-std=c++17', '-c', src / (name + '.cpp'), '-o', obj], 'compile_' + name)
        objects.append(obj)
    tests = []
    for variant in ['release', 'profile']:
        flags = ['-DTRADER_PROFILE'] if variant == 'profile' else []
        for name, file in [('test', 'test_faithful.cpp'), ('driver', 'stream_driver.cpp')]:
            binary = out / f'{variant}_{name}.exe'
            run([compiler, '-O3', '-std=c++17', *flags, src / file, *objects, '-lpsapi', '-o', binary], f'compile_{variant}_{name}')
            if name == 'test':
                tests.append(run([binary], variant + '_unit'))
    smoke = []
    for k in [2, 3, 4, 5]:
        rng = random.Random(91300 + k)
        n = k + 2
        colors = [[v % k for v in range(n)]] + [[rng.randrange(k) for _ in range(n)] for _ in range(7)]
        graph = {(u, v): rng.randint(-8, 8) / 4 for u in range(n) for v in range(n) if u != v and rng.random() < .4}
        case = out / f'k{k}'
        case.mkdir()
        (case / 'graph.txt').write_text(''.join(f'{u} {v} {w}\n' for (u, v), w in graph.items()), encoding='utf-8')
        for i, c in enumerate(colors):
            (case / ('colors.txt' if not i else f'colors_{i}.txt')).write_text(''.join(f'{v}\n' for v in c), encoding='utf-8')
        updates = []
        expected = [oracle(graph, colors, k)]
        snapshots = [dict(graph)]
        for i in range(60):
            u, v = rng.sample(range(n), 2)
            value = 'N' if i % 11 == 0 else 'D' if i % 7 == 0 else rng.randint(-12, 12) / 4
            updates.append(f'{u} {v} {value}\n')
            if value == 'D':
                graph.pop((u, v), None)
            elif value != 'N':
                graph[u, v] = value
            expected.append(oracle(graph, colors, k))
            snapshots.append(dict(graph))
        (case / 'updates.txt').write_text(''.join(updates), encoding='utf-8')
        for mode, b in [('single', 1), ('eg', 1), ('batch', 7)]:
            traces = []
            for variant in ['release', 'profile']:
                trace = case / f'{variant}_{mode}.tsv'
                raw = run([out / f'{variant}_driver.exe', case, k, 8, mode, b, trace], f'k{k}_{variant}_{mode}')
                metrics = json.loads(raw)
                expected_rows = [0] + (list(range(b, 61, b)) + ([60] if 60 % b else []))
                actual = trace.read_text().splitlines()[1:]
                assert [int(line.split('\t')[0]) for line in actual] == expected_rows
                for line in actual:
                    row, weight, path, trial = line.split('\t')
                    row, trial = int(row), int(trial)
                    assert (weight == 'none') == (expected[row] is None)
                    if weight != 'none':
                        p = list(map(int, path.split()))
                        assert len(p) == k + 1 and p[0] == p[-1] and len(set(p[:-1])) == k
                        assert len({colors[trial][v] for v in p[:-1]}) == k
                        w = sum(snapshots[row][e] for e in zip(p, p[1:]))
                        assert abs(float(weight) - expected[row]) < 1e-9 and abs(w - float(weight)) < 1e-9
                assert metrics['rows'] == 60 and metrics['queries'] == len(expected_rows) - 1
                assert metrics['eg_enabled'] == (mode == 'eg')
                assert metrics['fixed_batch_size'] == (None if mode == 'eg' else b)
                if mode == 'eg':
                    assert metrics['algorithm1_calls'] == 0
                    assert metrics['eg_immediate'] + metrics['eg_eof_flushes'] == metrics['maintenance_batches']
                    assert metrics['eg_immediate'] == sum(metrics[x] for x in ['eg_gap_triggers','eg_new_triggers','eg_no_anchor_triggers','eg_deleted_best_triggers'])
                    assert metrics['eg_changed_arrivals'] == metrics['eg_grouped_updates'] == metrics['eg_immediate'] + metrics['deferred']
                    assert sum(int(size)*count for size,count in metrics['eg_group_size_histogram'].items()) == metrics['eg_grouped_updates']
                elif mode == 'single':
                    assert metrics['algorithm1_calls'] > 0 and metrics['dag_forward_passes'] == 0
                else:
                    assert metrics['algorithm1_calls'] == 0 and metrics['dag_forward_passes'] > 0
                assert metrics['dag_forward_passes'] == metrics['dag_backward_passes']
                if variant == 'profile':
                    parts = sum(metrics[key] for key in ['schedule_ms', 'repair_ms', 'propagation_ms', 'candidate_ms', 'classification_ms'])
                    assert parts <= metrics['core_ms'] + .01
                    assert metrics['dp_bookkeeping_ms'] >= -.01
                    assert metrics['dp_total_ms'] + metrics['candidate_ms'] + metrics['classification_ms'] <= metrics['core_ms'] + .01
                traces.append(trace.read_bytes())
                smoke.append({'k': k, 'ell': 8, 'mode': mode, 'variant': variant, 'answers': len(actual), 'metrics': metrics})
            assert traces[0] == traces[1], 'profiling changed answers'
    manifest = {'status': 'small_graph_and_multicolor_correctness_passed', 'unit_outputs': tests, 'commands': records, 'smoke': smoke,
                'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in src.iterdir() if p.is_file()},
                'scope': 'paper-specified mechanisms plus declared correctness completions; not identical author code; UNI performance not measured'}
    (out / 'validation.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('ALL CORRECTNESS GATES PASS; no UNI-scale or paper-performance claim')


if __name__ == '__main__':
    main()
