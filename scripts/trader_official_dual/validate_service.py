"""Validate persistent native service, then serial UNI1 resource pilots."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

from prepare_service import prepare_service
from validate_interface import MODES, parse, finite, save


def service_parse(raw):
    answers, colors, graph = [], {}, {}
    for line in raw.splitlines():
        f=line.split('\t')
        if f[0]=='SERVICE_ANSWER':
            answers.append((int(f[1]),int(f[2]),finite(f[3]),[int(v) for v in f[4].split(',') if v]))
        elif f[0]=='SERVICE_COLOR': colors.setdefault(f[1],{})[f[2]]=int(f[3])
        elif f[0]=='SERVICE_EDGE': graph.setdefault(f[1],{})[f'{f[2]},{f[3]}']=float(f[4])
    return answers,colors,graph


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    native=root/'.research_data/common_benchmark/trader_official_native_20260913/build'
    common=root/'.research_data/common_benchmark/trader_common_input_20260913_v2'
    previous=root/'.research_data/common_benchmark/trader_official_dual_20260913/interface_v2'
    scripts=Path(__file__).resolve().parent
    compiler=root/'.venv/toolchains/llvm-mingw-20260616-ucrt-x86_64/bin/clang++.exe'
    env=dict(os.environ,PATH=str(native)+os.pathsep+os.environ['PATH'])
    def run(command,label,timeout=120):
        print('START',label,flush=True)
        with (out/f'{label}.stdout.log').open('wb') as stdout,(out/f'{label}.stderr.log').open('wb') as stderr:
            process=subprocess.Popen(list(map(str,command)),stdout=stdout,stderr=stderr,env=env,cwd=root)
            state=dict(status='running',phase=label,pid=process.pid,supervisor_pid=os.getpid(),
                       started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       timeout_s=timeout,command=list(map(str,command)),formal_benchmark=False)
            save(out/'active.json',state)
            try:
                code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                print('HARD TIMEOUT',label,'terminating authorized diagnostic',flush=True)
                process.kill(); process.wait()
                state.update(status='timeout');save(out/'active.json',state)
                raise
        state.update(status='completed' if code==0 else 'failed',returncode=code)
        save(out/f'{label}.process.json',state); save(out/'active.json',state)
        if code: raise RuntimeError(f'{label} failed: {code}')
        print('DONE',label,flush=True)
        return (out/f'{label}.stdout.log').read_text(encoding='utf-8')
    binaries={}
    for variant in ['official','oldnew']:
        source=out/variant
        prepare_service(native/'official_source',source,variant)
        for audit in [True,False]:
            label=f'{variant}_{"audit" if audit else "normal"}'
            binary=out/f'{label}.exe'
            command=[compiler,'-O3','-std=c++17','-include',native/'trader_native_uint_compat.h',
                     '-I',source,source/'directed_graph.cpp',source/'cycle_detector.cpp',
                     scripts/'service_driver.cpp','-lpsapi','-o',binary]
            if audit: command.append('-DSERVICE_AUDIT')
            run(command,'compile_'+label)
            binaries[variant,audit]=binary
    matched=0
    for variant in ['official','oldnew']:
        for k,folder in [(3,'finite_EG_test'),(5,'finite_EG_k5')]:
            case=common/folder
            for mode,batch,auto in MODES:
                label=f'k{k}_{mode}_{variant}'
                golden=parse((previous/f'{label}.stdout.log').read_text())
                raw=run([binaries[variant,True],case/'graph.txt',case/'updates.txt',case/'seeds.txt',
                         k,1,batch,auto,out/f'{label}.trace.tsv'],label)
                answers,colors,graph=service_parse(raw)
                assert answers==[(a['trial'],a['row'],a['reported_weight'],a['path'])
                                 for a in golden['answers'] if a['phase']=='arrival']
                assert colors==golden['colors'] and graph==golden['graph']
                matched+=1
        for mode,batch,auto in MODES:
            label=f'arrival_{variant}_{mode}'
            golden=parse((previous/f'{label}.stdout.log').read_text())
            raw=run([binaries[variant,True],common/'finite_EG_k5/graph.txt',
                     previous/'arrival_fixture/updates.txt',common/'finite_EG_k5/seeds.txt',
                     5,1,batch,auto,out/f'{label}.trace.tsv'],label)
            answers,colors,graph=service_parse(raw)
            assert answers==[(a['trial'],a['row'],a['reported_weight'],a['path'])
                             for a in golden['answers'] if a['phase']=='arrival']
            assert colors==golden['colors'] and graph==golden['graph']
            matched+=1
    save(out/'service_regression.json',dict(status='passed',trace_color_graph_cases=matched,
         original_DP_not_reimplemented=True,formal_benchmark=False,patched_gap_repaired=False))
    # Full static graph, short stream: resource checks, not UNI1 main results.
    pilot=out/'UNI1_prefix32'; pilot.mkdir()
    (pilot/'updates.txt').write_text('\n'.join((common/'UNI1/updates.txt').read_text().splitlines()[:32])+'\n')
    pilots=[]
    for ell in [1,4,80]:
        if ell==80 and pilots[-1]['peak_rss_mib']*20>24576:
            save(out/'resource_limit.json',dict(status='80_instance_launch_deferred',reason='4-instance projection exceeds 24 GiB',
                                             measured_4_peak_mib=pilots[-1]['peak_rss_mib']))
            break
        label=f'UNI1_EG_ell{ell}_prefix32'
        raw=run([binaries['official',False],common/'UNI1/graph.txt',pilot/'updates.txt',
                 root/'6D/code/.upstream/TRADER/seeds.txt',5,ell,1,1,out/f'{label}.trace.tsv'],label,600)
        result=json.loads(next(line for line in raw.splitlines() if line.startswith('{')))
        assert result['updates']==32 and result['ell']==ell
        result.update(diagnostic_only=True,full_static_graph=True,stream_prefix=32)
        save(out/f'{label}.result.json',result); pilots.append(result)
    save(out/'summary.json',dict(status='completed',service_regression_cases=matched,
         resource_pilots=pilots,formal_benchmark=False,
         binary_sha256={f'{v}_{a}':hashlib.sha256(p.read_bytes()).hexdigest() for (v,a),p in binaries.items()},
         remaining=['paired DELTA service/quality', 'minimal EG gap', 'UNI1 full modes and metrics', 'breakdown']))
    save(out/'active.json',dict(status='completed',supervisor_pid=os.getpid(),formal_benchmark=False))
    print('COMPLETED service validation and available resource pilots',flush=True)


if __name__=='__main__':
    main()
