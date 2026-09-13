"""Localize the first UNI1 service coloring discrepancy without retiming a run."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from validate_interface import parse, save
from validate_service import service_parse


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    base=root/'.research_data/common_benchmark'
    dual=base/'trader_official_dual_20260913'
    case=base/'trader_common_input_20260913_v2/UNI1'
    seeds=(root/'6D/code/.upstream/TRADER/seeds.txt').read_text().splitlines()[1].split()
    (out/'seeds.txt').write_text('1\n'+seeds[2]+'\n')
    (out/'updates.txt').write_text('\n'.join((case/'updates.txt').read_text().splitlines()[:769])+'\n')
    env=dict(os.environ,PATH=str(base/'trader_official_native_20260913/build')+os.pathsep+os.environ['PATH'])
    def run(command,label):
        with (out/f'{label}.stdout.log').open('wb') as stdout,(out/f'{label}.stderr.log').open('wb') as stderr:
            result=subprocess.run(list(map(str,command)),env=env,stdout=stdout,stderr=stderr,timeout=120,cwd=root)
        if result.returncode: raise RuntimeError(f'{label} failed')
        return (out/f'{label}.stdout.log').read_text()
    native=parse(run([dual/'interface_v2/official_audit.exe',case/'graph.txt',out/'updates.txt',
                      5,1,10,out/'seeds.txt',1,1],'native'))
    service=service_parse(run([dual/'service_v1/official_audit.exe',case/'graph.txt',out/'updates.txt',
                              out/'seeds.txt',5,1,1,1,out/'trace.tsv'],'service'))
    arrivals=[a for a in native['answers'] if a['phase']=='arrival']
    assert service[0]==[(a['trial'],a['row'],a['reported_weight'],a['path']) for a in arrivals]
    assert service[1]==native['colors'] and service[2]==native['graph']
    expected=json.loads((dual/'interface_v2/UNI1_all_arrival_colors.json').read_text())['2']
    assert all(expected[v]==c for v,c in service[1]['0'].items())
    answer=arrivals[-1]
    path_colors=[service[1]['0'][str(v)] for v in answer['path'][:-1]]
    save(out/'result.json',dict(diagnostic_only=True,trial_index=2,seed=int(seeds[2]),row=769,
         per_color_trace_native_service_equal=True,actual_colors_match_frozen_map=True,
         native_maintained_answer=answer,path_colors=path_colors,
         colorful=len(set(path_colors))==5,
         conclusion='The non-colorful maintained path is reproduced by the native common-input core; it is not caused by multi-color winner selection or a mismatched color file.'))
    print((out/'result.json').read_text(),flush=True)


if __name__=='__main__': main()
