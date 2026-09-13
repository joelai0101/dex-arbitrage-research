"""Build diagnostic variants and validate input fidelity; no formal timing."""
import argparse
import itertools
import json
import math
import os
from pathlib import Path
import subprocess

from prepare_source import prepare

MODES = [('B1', 1, 0), ('B50', 50, 0), ('B100', 100, 0),
         ('B500', 500, 0), ('B1000', 1000, 0), ('EG', 1, 1)]


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def finite(value):
    number = float(value)
    return number if math.isfinite(number) else None


def parse(raw):
    answers, colors, graph = [], {}, {}
    for line in raw.splitlines():
        fields = line.split('\t')
        if fields[0] == 'COMMON_ANSWER':
            _, trial, phase, row, weight, path, gap = fields
            answers.append(dict(trial=int(trial), phase=phase, row=int(row),
                                reported_weight=finite(weight),
                                path=[int(v) for v in path.split(',') if v], gap=finite(gap)))
        elif fields[0] == 'COMMON_FINAL_COLOR':
            _, trial, v, c = fields
            colors.setdefault(trial, {})[v] = int(c)
        elif fields[0] == 'COMMON_FINAL_EDGE':
            _, trial, u, v, w = fields
            graph.setdefault(trial, {})[f'{u},{v}'] = float(w)
    return dict(answers=answers, colors=colors, graph=graph)


def exact_k(graph, k, colors=None):
    vertices = {v for edge in graph for v in edge}
    weights = []
    for cycle in itertools.permutations(sorted(vertices), k):
        if cycle[0] != min(cycle):
            continue
        if colors and len({colors[str(v)] for v in cycle}) != k:
            continue
        edges = [(cycle[i], cycle[(i + 1) % k]) for i in range(k)]
        if all(edge in graph for edge in edges):
            weights.append(sum(graph[edge] for edge in edges))
    return min(weights, default=None)


def assess(answer, graph, k, colors):
    path = answer['path']
    valid = (len(path) == k + 1 and path[0] == path[-1] and
             len(set(path[:-1])) == k and all((u, v) in graph for u, v in zip(path, path[1:])))
    actual = sum(graph[u, v] for u, v in zip(path, path[1:])) if valid else None
    best = exact_k(graph, k)
    colored_best = exact_k(graph, k, colors)
    reported = answer['reported_weight']
    return dict(valid_cycle=valid, actual_weight=actual, oracle_weight=best,
                colored_oracle_weight=colored_best,
                reported_weight_matches=valid and reported is not None and math.isclose(actual, reported, abs_tol=1e-10),
                regret=(actual - best) if valid and best is not None else None,
                relative_error_pct=(100 * abs(actual-best)/abs(best)) if valid and best is not None and abs(best)>1e-12 else None,
                colored_optimal=valid and colored_best is not None and math.isclose(actual, colored_best, abs_tol=1e-10))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    native = root / '.research_data/common_benchmark/trader_official_native_20260913/build'
    common = root / '.research_data/common_benchmark/trader_common_input_20260913_v2'
    env = dict(os.environ, PATH=str(native) + os.pathsep + os.environ['PATH'])
    compiler = root / '.venv/toolchains/llvm-mingw-20260616-ucrt-x86_64/bin/clang++.exe'

    def run(command, label, timeout=120):
        print('START', label, flush=True)
        with (out/f'{label}.stdout.log').open('wb') as stdout, (out/f'{label}.stderr.log').open('wb') as stderr:
            result = subprocess.run(list(map(str, command)), env=env, stdout=stdout,
                                    stderr=stderr, timeout=timeout, cwd=root)
        save(out/f'{label}.process.json', dict(command=list(map(str, command)), returncode=result.returncode,
                                              diagnostic_only=True))
        if result.returncode:
            raise RuntimeError(f'{label} failed: {result.returncode}')
        print('DONE', label, flush=True)
        return (out/f'{label}.stdout.log').read_text(encoding='utf-8')

    binaries = {}
    for variant in ['official', 'oldnew']:
        source = out/variant
        prepare(native/'official_source', source, variant)
        binary = out/f'{variant}_audit.exe'
        run([compiler, '-O3', '-std=c++17', '-DCOMMON_AUDIT', '-include', native/'trader_native_uint_compat.h',
             source/'directed_graph.cpp', source/'cycle_detector.cpp', source/'dp_with_filter_full.cpp',
             '-o', binary], f'compile_{variant}')
        binaries[variant] = binary
    source = out/'official'
    color_binary = out/'colors.exe'
    run([compiler, '-O3', '-std=c++17', '-DCOMMON_COLOR_EXPORT', '-include', native/'trader_native_uint_compat.h',
         source/'directed_graph.cpp', source/'cycle_detector.cpp', source/'dp_with_filter_full.cpp',
         '-o', color_binary], 'compile_colors')

    # Export actual C++ RNG colors without graph initialization or timing claims.
    raw = run([color_binary, common/'UNI1/graph.txt', common/'UNI1/updates.txt', 5, 80, 10,
               root/'6D/code/.upstream/TRADER/seeds.txt', 1, 0], 'UNI1_colors')
    initial, counts = {}, []
    for line in raw.splitlines():
        f = line.split('\t')
        if f[0] == 'COMMON_INITIAL_COLOR':
            initial.setdefault(f[1], {})[f[2]] = int(f[3])
        elif f[0] == 'COMMON_INITIAL_VERTEX_COUNT':
            counts.append(int(f[2]))
    final = parse(raw)['colors']
    assert initial == json.loads((common/'UNI1/official_initial_colors.json').read_text())
    assert counts == [4152]*80
    assert len(final) == 80 and all(len(c)==4156 for c in final.values())
    save(out/'UNI1_all_arrival_colors.json', final)

    checks = []
    for k, folder in [(3, 'finite_EG_test'), (5, 'finite_EG_k5')]:
        case = common/folder
        original_graph = {(int(u),int(v)):float(w) for u,v,w in
                          (line.split() for line in (case/'graph.txt').read_text().splitlines())}
        update_lines = (case/'updates.txt').read_text().splitlines()
        for mode, batch, auto in MODES:
            # Finite-only interface output must equal the observed upstream run.
            baseline = run([common/'observed_trader.exe', case/'graph.txt', case/'updates.txt',
                            k, 1, 10, case/'seeds.txt', batch, auto], f'k{k}_{mode}_native')
            expected = []
            for line in baseline.splitlines():
                if line.startswith('AUDIT_ANSWER\t'):
                    _, row, weight, path = line.split('\t')
                    expected.append((int(row), finite(weight), [int(v) for v in path.split(',') if v]))
            for variant, binary in binaries.items():
                result = parse(run([binary, case/'graph.txt', case/'updates.txt', k, 1, 10,
                                    case/'seeds.txt', batch, auto], f'k{k}_{mode}_{variant}'))
                arrivals = [a for a in result['answers'] if a['phase']=='arrival']
                assert len(arrivals) == len(update_lines)
                if variant == 'official':
                    assert [(a['row'],a['reported_weight'],a['path']) for a in arrivals] == expected
                live = dict(original_graph)
                quality = []
                for answer, line in zip(arrivals, update_lines):
                    u,v,w = line.split(); live[int(u),int(v)] = float(w)
                    quality.append(assess(answer, live, k, result['colors']['0']))
                checks.append(dict(k=k, mode=mode, variant=variant,
                                   native_trace_equal=True if variant=='official' else None,
                                   answers=arrivals, quality=quality))

    # N counts towards fixed-B boundaries; it never creates a 0->0 edge.
    # First-arrival colors must agree even when all updates wait until EOF.
    case = out/'arrival_fixture'; case.mkdir()
    graph = common/'finite_EG_k5/graph.txt'
    updates = ['0 0 N', '10 11 -1', '11 12 -2', '5 6 -12', '0 0 N', '6 7 -1']
    (case/'updates.txt').write_text('\n'.join(updates)+'\n')
    expected_graph = {(int(u),int(v)):float(w) for u,v,w in
                      (line.split() for line in graph.read_text().splitlines())}
    for line in updates:
        u,v,w = line.split()
        if w!='N': expected_graph[int(u),int(v)] = float(w)
    paired_colors = None
    for variant, binary in binaries.items():
        for mode,batch,auto in MODES:
            result = parse(run([binary,graph,case/'updates.txt',5,1,10,
                                common/'finite_EG_k5/seeds.txt',batch,auto],f'arrival_{variant}_{mode}'))
            assert len([a for a in result['answers'] if a['phase']=='arrival'])==len(updates)
            assert result['graph']['0'] == {f'{u},{v}':w for (u,v),w in expected_graph.items()}
            if paired_colors is None: paired_colors = result['colors']
            assert result['colors'] == paired_colors
    save(out/'validation.json', dict(
        status='interface_regression_passed', formal_timing=False,
        native_trace_comparisons=12, noop_and_future_color_cases=12,
        UNI1_initial_colors_match=True, UNI1_initial_vertices=4152,
        UNI1_total_color_vertices=4156, future_vertices_not_preadded=True,
        known_finite_quality_cases=checks, gap_repaired=False,
        patched_version_ready=False,
        next='Resolve gap representation separately; build paired online service and quality measurement.'))
    print('VALIDATED interface; old/new-only patch is not accepted as complete EG.',flush=True)


if __name__ == '__main__':
    main()
