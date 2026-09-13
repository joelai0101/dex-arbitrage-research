"""Paired DELTA profiling/control diagnostic; excludes both from formal averages."""
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
    common=base/'trader_common_input_20260913_v2/UNI1'
    old=dual/'DELTA_UNI1_batches_r1'
    env=dict(os.environ,PATH=str(native)+os.pathsep+os.environ['PATH'])

    def run(command,label):
        print('START',label,flush=True)
        command=list(map(str,command))
        with (out/f'{label}.stdout.log').open('wb') as stdout,(out/f'{label}.stderr.log').open('wb') as stderr:
            process=subprocess.Popen(command,cwd=root,env=env,stdout=stdout,stderr=stderr)
            state=dict(status='running',phase=label,pid=process.pid,supervisor_pid=os.getpid(),
                       started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),timeout_s=120,
                       formal_benchmark=False,command=command)
            save(out/'active.json',state)
            try:code=process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                print('HARD TIMEOUT',label,'terminating',flush=True)
                process.kill();process.wait();state['status']='timeout';save(out/'active.json',state);raise
        state.update(status='completed' if code==0 else 'failed',returncode=code)
        save(out/f'{label}.process.json',state);save(out/'active.json',state)
        if code:raise RuntimeError(label)
        print('DONE',label,flush=True)
        return (out/f'{label}.stdout.log').read_text(encoding='utf-8')

    build=out/'build'
    run([sys.executable,Path(__file__).with_name('prepare_delta_breakdown.py'),'--root',root,'--output',build],'prepare')
    compiler=root/'.venv/toolchains/llvm-mingw-20260616-ucrt-x86_64/bin/clang++.exe'
    for label,flags in [('control',[]),('profile',['-DCOMMON_BREAKDOWN'])]:
        run([compiler,'-O3','-std=c++17',*flags,build/'delta_service_driver.cpp','-lpsapi','-o',build/f'{label}.exe'],f'compile_{label}')
    summaries=[]
    # Small existing fixture first; no new oracle is necessary.
    tiny=old/'boundary_fixture'
    for batch in (1,1000):
        for variant in ('control','profile'):
            trace=out/f'tiny_{batch}_{variant}.tsv'
            run([build/f'{variant}.exe',tiny/'graph.txt',tiny/'updates.txt',tiny/'colors.txt',5,1,batch,trace],f'tiny_{batch}_{variant}')
            assert trace.read_bytes()==(tiny/f'B{batch}.tsv').read_bytes()
    protocol=json.loads((old/'protocol.json').read_text())
    for path,digest in protocol['input_sha256'].items():assert sha(Path(path))==digest
    for variant in ('control','profile'):
        trace=out/f'UNI1_{variant}.tsv'
        raw=run([build/f'{variant}.exe',common/'graph.txt',common/'updates.txt',old/'colors.txt',5,80,1,trace],f'UNI1_{variant}')
        timing=json.loads(next(line for line in raw.splitlines() if line.startswith('{')))
        assert timing['updates']==7628
        assert trace.read_bytes()==(old/'UNI1_DELTA_B1_r1/trace.tsv').read_bytes()
        values=[float(x) for x in next(line for line in raw.splitlines() if line.startswith('BREAKDOWN\t')).split('\t')[1:]]
        summaries.append(dict(variant=variant,timing=timing,phase_ms=values,trace_matches_completed_run=True))
    normal,profile=summaries
    total=profile['timing']['detection_ms']
    residual=total-sum(profile['phase_ms'])
    assert residual>=-1e-8
    phases=dict(zip(['classification','maintenance','candidates','answer','other'],profile['phase_ms']))
    phases['other']+=residual
    assert abs(sum(phases.values())-total)<1e-7
    save(out/'summary.json',dict(status='completed',diagnostic_only=True,formal_average_eligible=False,
         dataset='UNI1',batch=1,ell=80,results=summaries,exclusive_ms=phases,
         exclusive_pct={k:100*v/total for k,v in phases.items()},timer_boundary_residual_ms=residual,
         profile_over_control_ratio=total/normal['timing']['detection_ms'],
         note='One control/profile pair; instrumentation overhead is observed, not mathematically removed. Main timing table unchanged.'))
    print('SAVED',out/'summary.json',flush=True)


if __name__=='__main__':main()
