"""Serial official-EG control/profile diagnostic, not new formal timing."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from run_uni1_official import sha
from validate_interface import save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    base=root/'.research_data/common_benchmark'
    native=base/'trader_official_native_20260913/build'
    dual=base/'trader_official_dual_20260913'
    common=base/'trader_common_input_20260913_v2'
    env=dict(os.environ,PATH=str(native)+os.pathsep+os.environ['PATH'])

    def run(command,label,timeout=120):
        print('START',label,flush=True)
        command=list(map(str,command))
        with (out/f'{label}.stdout.log').open('wb') as stdout,(out/f'{label}.stderr.log').open('wb') as stderr:
            process=subprocess.Popen(command,cwd=root,env=env,stdout=stdout,stderr=stderr)
            state=dict(status='running',phase=label,pid=process.pid,supervisor_pid=os.getpid(),
                       started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),timeout_s=timeout,
                       formal_benchmark=False,command=command)
            save(out/'active.json',state)
            try:code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                print('HARD TIMEOUT',label,'terminating',flush=True)
                process.kill();process.wait();state['status']='timeout';save(out/'active.json',state);raise
        state.update(status='completed' if code==0 else 'failed',returncode=code)
        save(out/f'{label}.process.json',state);save(out/'active.json',state)
        if code:raise RuntimeError(label)
        print('DONE',label,flush=True)
        return (out/f'{label}.stdout.log').read_text(encoding='utf-8')

    build=out/'build'
    run([sys.executable,Path(__file__).with_name('prepare_trader_breakdown.py'),'--root',root,'--output',build],'prepare')
    compiler=root/'.venv/toolchains/llvm-mingw-20260616-ucrt-x86_64/bin/clang++.exe'
    for variant,flags in [('control',[]),('profile',['-DCOMMON_BREAKDOWN'])]:
        run([compiler,'-O3','-std=c++17',*flags,'-include',native/'trader_native_uint_compat.h',
             '-I',build,build/'directed_graph.cpp',build/'cycle_detector.cpp',build/'service_driver.cpp',
             '-lpsapi','-o',build/f'{variant}.exe'],f'compile_{variant}')
    for k,folder in [(3,'finite_EG_test'),(5,'finite_EG_k5')]:
        case=common/folder
        for mode,batch,eg in [('B1',1,0),('B1000',1000,0),('EG',1,1)]:
            for variant in ('control','profile'):
                label=f'k{k}_{mode}_{variant}';trace=out/f'{label}.tsv'
                run([build/f'{variant}.exe',case/'graph.txt',case/'updates.txt',case/'seeds.txt',k,1,batch,eg,trace],label)
                assert trace.read_bytes()==(dual/f'service_v1/k{k}_{mode}_official.trace.tsv').read_bytes()
    reference=dual/'UNI1_official_EG_r1'
    manifest=json.loads((reference/'manifest.json').read_text())
    for path,digest in manifest['files'].items():assert sha(Path(path))==digest
    results=[]
    for variant in ('control','profile'):
        trace=out/f'UNI1_{variant}.tsv'
        raw=run([build/f'{variant}.exe',common/'UNI1/graph.txt',common/'UNI1/updates.txt',
                 root/'6D/code/.upstream/TRADER/seeds.txt',5,80,1,1,trace],f'UNI1_{variant}',3600)
        timing=json.loads(next(line for line in raw.splitlines() if line.startswith('{')))
        assert timing['updates']==7628
        equal=trace.read_bytes()==(reference/'trace.tsv').read_bytes()
        values=[float(x) for x in next(line for line in raw.splitlines() if line.startswith('BREAKDOWN\t')).split('\t')[1:]]
        result=dict(variant=variant,timing=timing,phase_ms=values,trace_matches_completed_run=equal)
        save(out/f'UNI1_{variant}.result.json',result)
        if not equal:raise RuntimeError('Instrumented/control trace differs from completed official run; inspect before continuing')
        results.append(result)
    normal,profile=results
    total=profile['timing']['detection_ms'];residual=total-sum(profile['phase_ms'])
    assert residual>=-1e-7
    phases=dict(zip(['classification','maintenance','candidates','answer','other'],profile['phase_ms']))
    phases['other']+=residual
    assert abs(sum(phases.values())-total)<1e-6
    save(out/'summary.json',dict(status='completed',diagnostic_only=True,formal_average_eligible=False,
         method='TRADER official core',dataset='UNI1',batch_parameter=1,eg=True,ell=80,results=results,
         exclusive_ms=phases,exclusive_pct={k:100*v/total for k,v in phases.items()},
         timer_boundary_residual_ms=residual,profile_over_control_ratio=total/normal['timing']['detection_ms'],
         note='One control/profile pair; all existing core answer defects retained. Main table unchanged.'))
    print('SAVED',out/'summary.json',flush=True)


if __name__=='__main__':main()
