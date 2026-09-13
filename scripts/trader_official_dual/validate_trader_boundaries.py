"""Check native/service fidelity across interior fixed-batch boundaries."""
import argparse
import csv
import os
from pathlib import Path
import subprocess

from validate_interface import MODES,parse,save,finite
from validate_service import service_parse


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    base=root/'.research_data/common_benchmark';dual=base/'trader_official_dual_20260913'
    case=dual/'DELTA_UNI1_batches_r1/boundary_fixture'
    seeds=base/'trader_common_input_20260913_v2/finite_EG_k5/seeds.txt'
    env=dict(os.environ,PATH=str(base/'trader_official_native_20260913/build')+os.pathsep+os.environ['PATH'])
    def run(command,label):
        with (out/f'{label}.stdout.log').open('wb') as stdout,(out/f'{label}.stderr.log').open('wb') as stderr:
            p=subprocess.run(list(map(str,command)),cwd=root,env=env,stdout=stdout,stderr=stderr,timeout=120)
        if p.returncode:raise RuntimeError(f'{label} failed')
        return (out/f'{label}.stdout.log').read_text()
    checks=[]
    for variant in ['official','oldnew']:
        for mode,batch,eg in MODES:
            label=f'{variant}_{mode}'
            native=parse(run([dual/f'interface_v2/{variant}_audit.exe',case/'graph.txt',case/'updates.txt',
                              5,1,10,seeds,batch,eg],label+'_native'))
            service=service_parse(run([dual/f'service_v1/{variant}_audit.exe',case/'graph.txt',case/'updates.txt',
                                      seeds,5,1,batch,eg,out/f'{label}.trace.tsv'],label+'_service'))
            expected=[(a['trial'],a['row'],a['reported_weight'],a['path']) for a in native['answers'] if a['phase']=='arrival']
            assert len(expected)==1002 and expected==service[0]
            assert native['colors']==service[1] and native['graph']==service[2]
            with (out/f'{label}.trace.tsv').open() as f: traces=list(csv.DictReader(f,delimiter='\t'))
            eof=next(a for a in native['answers'] if a['phase']=='eof')
            result=next(a for a in traces if a['phase']=='eof')
            assert finite(result['weight'])==eof['reported_weight']
            assert list(map(int,result['path'].split()))==eof['path']
            checks.append(dict(variant=variant,mode=mode,arrival_rows=1002,passed=True))
            print('PASSED',label,flush=True)
    save(out/'validation.json',dict(status='passed',checks=checks,core_correctness_claim=False,
         covers=['full B50/100/500/1000 interior boundaries','coalescing repeated edges','N','increase/decrease','future root0','EOF remainder'],
         note='Fidelity check only: original incorrect answers/graph behavior are retained, not repaired.'))


if __name__=='__main__':main()
