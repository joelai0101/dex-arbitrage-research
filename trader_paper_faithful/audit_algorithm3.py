"""Reproduce the known Algorithm 3 state-level gap; this does not fix it.

Exit 0 means both the repeat-update counterexample and the incorrect skip-seen
mutation were reproduced. It does NOT mean the once-per-pass criterion passed.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    src = Path(__file__).resolve().parent
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    compiler = args.compiler.resolve()
    records = []

    def run(command, name, expected=0):
        command = list(map(str, command))
        result = subprocess.run(command, capture_output=True, timeout=180)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
        records.append({'name': name, 'command': command, 'returncode': result.returncode,
                        'expected_returncode': expected})
        if result.returncode != expected:
            raise RuntimeError(f'{name}: expected {expected}, got {result.returncode}; inspect log')
        print(f'{name}: exit {result.returncode} (expected {expected})', flush=True)
        return result.stdout.decode('utf-8')

    for name in ['libc++.dll', 'libunwind.dll', 'libwinpthread-1.dll']:
        if (compiler.parent / name).exists():
            shutil.copy2(compiler.parent / name, out / name)
    inputs = ['faithful.h', 'audit_algorithm3.cpp', 'audit_algorithm3.py',
              'paper_batch_scheduler.h', 'paper_batch_scheduler.cpp',
              'paper_batch_reference_model.h', 'paper_batch_reference_model.cpp']
    hashes = {name: hashlib.sha256((src / name).read_bytes()).hexdigest() for name in inputs}
    objects = []
    for name in ['paper_batch_scheduler', 'paper_batch_reference_model']:
        obj = out / (name + '.o')
        run([compiler, '-O3', '-std=c++17', '-c', src / (name + '.cpp'), '-o', obj], 'compile_' + name)
        objects.append(obj)
    baseline = out / 'audit_baseline.exe'
    run([compiler, '-O3', '-std=c++17', src / 'audit_algorithm3.cpp', *objects, '-o', baseline], 'compile_baseline')
    baseline_output = run([baseline], 'baseline_correctness')
    run([baseline, '--require-once'], 'baseline_once_per_pass_FAIL', expected=2)

    # Deliberate negative control, generated only in the output directory.
    # Never patch the production Engine or its passing correctness tests.
    header = (src / 'faithful.h').read_text(encoding='utf-8')
    substitutions = [
        ('    WitnessStates forced;', '    WitnessStates forced;\n    WitnessStates audit_seen;'),
        ('      for(auto& [key,candidate]:pending[level]){',
         '      for(auto& [key,candidate]:pending[level]){\n        if(first_direction!=0&&!audit_seen.insert(key).second)continue;'),
        ('      for(int direction:{1,-1}){', '      for(int direction:{1,-1}){\n        audit_seen.clear();'),
    ]
    for old, new in substitutions:
        if header.count(old) != 1:
            raise RuntimeError('mutation anchor changed; review the negative control')
        header = header.replace(old, new)
    audit = (src / 'audit_algorithm3.cpp').read_text(encoding='utf-8').replace('#include "faithful.h"', '')
    mutant_source = out / 'skip_seen_mutant.cpp'
    mutant_source.write_text('#define TRADER_TEST_HOOKS\n' + header.replace('#pragma once\n', '', 1) + '\n' + audit, encoding='utf-8')
    mutant = out / 'audit_skip_seen.exe'
    run([compiler, '-O3', '-std=c++17', '-I', src, mutant_source, *objects, '-o', mutant], 'compile_skip_seen')
    mutant_output = run([mutant], 'skip_seen_correctness_FAIL', expected=1)
    if 'target=3 oracle_target=3 full_dp_equal=1' not in baseline_output:
        raise RuntimeError('missing baseline three-path result')
    if 'target=9 oracle_target=3 full_dp_equal=0' not in mutant_output:
        raise RuntimeError('missing skip-seen counterexample')
    if any(hashlib.sha256((src / name).read_bytes()).hexdigest() != digest for name, digest in hashes.items()):
        raise RuntimeError('source changed during audit')
    report = {
        'status': 'known_mechanism_gap_and_invalid_fix_reproduced',
        'algorithm3_once_per_pass': 'FAIL', 'baseline_final_dp': 'PASS',
        'skip_seen_final_dp': 'FAIL', 'production_engine_modified': False,
        'commands': records, 'source_sha256': hashes,
        'mutant_source_sha256': hashlib.sha256(mutant_source.read_bytes()).hexdigest(),
        'baseline_output': baseline_output, 'skip_seen_output': mutant_output,
    }
    (out / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('AUDIT COMPLETE: once-per-pass FAIL; naive skip-seen correctness FAIL; no algorithm fix')


if __name__ == '__main__':
    main()
