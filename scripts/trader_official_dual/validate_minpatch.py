"""Targeted diagnostic regressions; never publishes formal timing results."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess

from prepare_source import HASHES, prepare, transform
from validate_interface import MODES, assess, parse, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    base = root/'.research_data/common_benchmark'
    native = base/'trader_official_native_20260913/build'
    common = base/'trader_common_input_20260913_v2'
    dual = base/'trader_official_dual_20260913'
    source = out/'minpatch'
    prepare(native/'official_source', source, 'minpatch')
    # Existing interface variants must remain byte-identical to prior builds.
    original = (native/'official_source/cycle_detector.cpp').read_text(encoding='utf-8')
    for variant in ('official', 'oldnew'):
        assert transform(original, variant) == (dual/f'interface_v2/{variant}/cycle_detector.cpp').read_text(encoding='utf-8')
    env = dict(os.environ, PATH=str(native)+os.pathsep+os.environ['PATH'])

    def run(command, label):
        print('START', label, flush=True)
        with (out/f'{label}.stdout.log').open('wb') as stdout, (out/f'{label}.stderr.log').open('wb') as stderr:
            result = subprocess.run(list(map(str, command)), cwd=root, env=env,
                                    stdout=stdout, stderr=stderr, timeout=120)
        save(out/f'{label}.process.json', dict(command=list(map(str, command)),
             returncode=result.returncode, diagnostic_only=True))
        if result.returncode:
            raise RuntimeError(f'{label}: {result.returncode}')
        print('DONE', label, flush=True)
        return (out/f'{label}.stdout.log').read_text(encoding='utf-8')

    binary = out/'minpatch_audit.exe'
    run([root/'.venv/toolchains/llvm-mingw-20260616-ucrt-x86_64/bin/clang++.exe',
         '-O3', '-std=c++17', '-DCOMMON_AUDIT', '-include', native/'trader_native_uint_compat.h',
         source/'directed_graph.cpp', source/'cycle_detector.cpp', source/'dp_with_filter_full.cpp',
         '-o', binary], 'compile')
    binaries = {'oldnew': dual/'interface_v2/oldnew_audit.exe', 'minpatch': binary}
    case = common/'finite_EG_k5'
    initial = {(int(u), int(v)): float(w) for u, v, w in
               (line.split() for line in (case/'graph.txt').read_text().splitlines())}

    def execute(label, graph, updates, seeds, k=5, batch=50, eg=0):
        return {variant: parse(run([exe, graph, updates, k, 1, 10, seeds, batch, eg],
                                  f'{label}_{variant}')) for variant, exe in binaries.items()}

    checks = []
    # Existing finite gap counterexample, all six modes. Keep failures visible.
    for mode, batch, eg in MODES:
        results = execute(f'gap_{mode}', case/'graph.txt', case/'updates.txt', case/'seeds.txt', batch=batch, eg=eg)
        live = dict(initial)
        for line in (case/'updates.txt').read_text().splitlines():
            u, v, w = line.split(); live[int(u), int(v)] = float(w)
        for variant, result in results.items():
            arrivals = [a for a in result['answers'] if a['phase'] == 'arrival']
            checks.append(dict(case='finite_gap', mode=mode, variant=variant,
                 first_arrival=arrivals[0], final=result['answers'][-1],
                 quality=assess(result['answers'][-1], live, 5, result['colors']['0'])))

    # Graph mutation must not depend on vertex ID zero or equal endpoint colors.
    colors = results['oldnew']['colors']['0']
    for same in (False, True):
        u = next(int(v) for v, c in colors.items() if v != '0' and (c == colors['0']) == same)
        updates = out/f'zero_same_{same}.txt'
        updates.write_text(f'{u} 0 -7\n0 0 N\n', encoding='utf-8')
        paired = execute(f'zero_same_{same}', case/'graph.txt', updates, case/'seeds.txt')
        expected = {f'{a},{b}': w for (a,b),w in initial.items()}
        expected[f'{u},0'] = -7.0
        assert paired['minpatch']['graph']['0'] == expected
        assert paired['oldnew']['graph']['0'] != expected
        assert paired['oldnew']['colors'] == paired['minpatch']['colors']
        checks.append(dict(case='destination_zero', same_color=same, source=u,
                           oldnew_failed=True, minpatch_passed=True))

    # Actual reported UNI1 counterexample, one fixed seed and only 769 updates.
    uni = common/'UNI1'
    updates = out/'UNI1_prefix769.txt'
    updates.write_text('\n'.join((uni/'updates.txt').read_text().splitlines()[:769])+'\n', encoding='utf-8')
    seeds = out/'seed647826.txt'
    seeds.write_text('1\n647826\n', encoding='utf-8')
    paired = execute('UNI1_color769', uni/'graph.txt', updates, seeds, batch=1, eg=1)
    color_checks = {}
    for variant, result in paired.items():
        arrivals = [a for a in result['answers'] if a['phase']=='arrival']
        violations = [a['row'] for a in arrivals if a['path'] and
                      len({result['colors']['0'][str(v)] for v in a['path'][:-1]}) != 5]
        color_checks[variant] = dict(violation_rows=violations, last=arrivals[-1])
    assert paired['oldnew']['colors'] == paired['minpatch']['colors']
    assert color_checks['oldnew']['violation_rows']
    assert not color_checks['minpatch']['violation_rows']
    for name, expected in HASHES.items():
        assert hashlib.sha256((native/'official_source'/name).read_bytes()).hexdigest() == expected
    save(out/'validation.json', dict(status='targeted_checks_completed', formal_timing=False,
         original_variants_unchanged=True, original_sources_unchanged=True,
         checks=checks, UNI1_prefix_color=color_checks,
         gap_repaired=False, production_accepted=False,
         next='Review remaining gap/C2 and increase-repair semantics; do not claim a complete corrected EG.'))
    print('SAVED', out/'validation.json', flush=True)


if __name__ == '__main__':
    main()
