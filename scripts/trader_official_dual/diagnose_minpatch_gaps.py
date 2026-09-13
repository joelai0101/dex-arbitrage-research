"""Reuse built audit binary for unresolved C2 and increased-weight witnesses."""
import argparse
import itertools
import os
from pathlib import Path
import subprocess

from validate_interface import assess, parse, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    base = root/'.research_data/common_benchmark'
    case = base/'trader_common_input_20260913_v2/finite_EG_k5'
    env = dict(os.environ, PATH=str(base/'trader_official_native_20260913/build')+os.pathsep+os.environ['PATH'])
    graph = {(int(u),int(v)):float(w) for u,v,w in
             (line.split() for line in (case/'graph.txt').read_text().splitlines())}
    updates = out/'increase.txt'
    updates.write_text('0 1 5\n0 0 N\n', encoding='utf-8')
    checks = []
    for mode, batch, eg in [('B1',1,0),('B50',50,0),('EG',1,1)]:
        command = list(map(str, [args.binary.resolve(), case/'graph.txt', updates, 5, 1, 10, case/'seeds.txt', batch, eg]))
        with (out/f'{mode}.stdout.log').open('wb') as stdout, (out/f'{mode}.stderr.log').open('wb') as stderr:
            process = subprocess.run(command, env=env, cwd=root, stdout=stdout, stderr=stderr, timeout=120)
        save(out/f'{mode}.process.json', dict(command=command, returncode=process.returncode, diagnostic_only=True))
        if process.returncode: raise RuntimeError(mode)
        result = parse((out/f'{mode}.stdout.log').read_text(encoding='utf-8'))
        live = dict(graph); live[0,1] = 5
        checks.append(dict(mode=mode, answers=result['answers'],
             eof_quality=assess(result['answers'][-1], live, 5, result['colors']['0']),
             final_graph_correct=result['graph']['0']=={f'{u},{v}':w for (u,v),w in live.items()}))

    # Two colorful cycles have the same canonical root, last vertex and full
    # color mask. A single scalar in that closing DP state loses the runner-up.
    shared = {(0,1):-2,(1,2):-2,(2,3):-2,(3,4):-2,(4,0):-2,
              (0,2):-1,(2,1):-2,(1,3):-2}
    cycles = []
    for middle in itertools.permutations([1,2,3,4]):
        path = (0,)+middle+(0,)
        edges = list(zip(path,path[1:]))
        if all(edge in shared for edge in edges):
            cycles.append(dict(path=path, weight=sum(shared[e] for e in edges),
                               closing_key=[0,path[-2],31]))
    cycles.sort(key=lambda c:c['weight'])
    assert len(cycles)==2 and [c['weight'] for c in cycles]==[-10,-9]
    assert cycles[0]['closing_key']==cycles[1]['closing_key']
    save(out/'diagnosis.json', dict(formal_timing=False, increase_checks=checks,
         shared_closing_state=dict(graph=[[*e,w] for e,w in shared.items()],
              colors={str(v):v for v in range(5)}, exact_cycles=cycles, true_gap=1,
              conclusion='Scanning one minimum per closing DP key cannot recover this second cycle.'),
         gap_repaired=False, production_accepted=False))
    print('SAVED', out/'diagnosis.json', flush=True)


if __name__=='__main__':
    main()
