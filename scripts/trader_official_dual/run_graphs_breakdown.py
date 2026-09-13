"""Serial GraphS control/profile pair; reuse completed exact answer traces."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from run_graphs_uni1 import peak
from run_uni1_official import sha
from validate_interface import save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    base=root/'.research_data/common_benchmark';dual=base/'trader_official_dual_20260913'
    previous=dual/'GraphS_UNI1_common_r1'
    gate=json.loads((base/'paper_alignment_20260913/graphs_length_index/validation.json').read_text())
    classes=root/Path(gate['graphs_classes'])
    for name,expected in gate['backend'].items():assert sha(classes/name)==expected
    jar=root/'.venv/java-libs/jgrapht-core-1.4.0.jar';assert sha(jar)==gate['jar_sha256']
    build=out/'build'
    subprocess.run([sys.executable,str(Path(__file__).with_name('prepare_graphs_breakdown.py')),
                    '--root',str(root),'--output',str(build)],cwd=root,check=True,timeout=120)
    newclasses=build/'classes';newclasses.mkdir()
    java=Path('C:/Program Files/Java/jdk-25.0.3/bin/java.exe')
    cp=str(newclasses)+os.pathsep+str(classes)+os.pathsep+str(jar)
    command=list(map(str,[java.with_name('javac.exe'),'-cp',str(classes)+os.pathsep+str(jar),'-d',newclasses,
                          build/'GraphSWeightedBenchmark.java',build/'GraphSCommonDriver.java',build/'GraphSBreakdown.java']))
    print('START compile',flush=True)
    with (build/'compile.stdout.log').open('wb') as stdout,(build/'compile.stderr.log').open('wb') as stderr:
        p=subprocess.run(command,cwd=root,stdout=stdout,stderr=stderr,timeout=120)
    save(build/'compile.json',dict(command=command,returncode=p.returncode))
    if p.returncode:raise RuntimeError('GraphS profiling compilation failed')
    print('DONE compile',flush=True)
    save(build/'classes.json',dict(backend_sha256=gate['backend'],jar_sha256=sha(jar),
         generated_class_sha256={p.name:sha(p) for p in newclasses.glob('*.class')}))

    def execute(case,label,variant,timeout,expected_trace):
        folder=out/label;folder.mkdir()
        command=list(map(str,[java,'-Xmx16g',f'-Dcommon.breakdown={str(variant=="profile").lower()}',
                              '-cp',cp,'GraphSCommonDriver',case,5,folder/'trace.tsv',40]))
        print('START',label,flush=True)
        start=time.perf_counter();observed_peak=0.;ack=False;next_log=30
        with (folder/'stdout.log').open('wb') as stdout,(folder/'stderr.log').open('wb') as stderr:
            child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr,stdin=subprocess.PIPE)
            state=dict(status='running',phase=label,pid=child.pid,supervisor_pid=os.getpid(),
                       started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),timeout_s=timeout,
                       formal_benchmark=False,exclusive_timing=True,command=command,target=str(folder))
            save(out/'active.json',state)
            while child.poll() is None:
                observed_peak=max(observed_peak,peak(child._handle))
                if not ack and (folder/'stdout.log').stat().st_size:
                    lines=(folder/'stdout.log').read_text().splitlines()
                    if lines and lines[-1].startswith('{') and lines[-1].endswith('}'):
                        child.stdin.write(b'\n');child.stdin.flush();ack=True
                elapsed=time.perf_counter()-start
                if elapsed>=timeout:
                    print('HARD TIMEOUT; terminating',label,flush=True)
                    child.kill();child.wait();state['status']='timeout';save(out/'active.json',state);raise RuntimeError('GraphS timeout; no retry')
                if elapsed>=next_log:
                    print('RUNNING',label,'seconds',round(elapsed),'peak_MiB',round(observed_peak),flush=True);next_log+=30
                time.sleep(.25)
        state.update(status='completed' if child.returncode==0 else 'failed',returncode=child.returncode)
        save(folder/'process.json',state);save(out/'active.json',state)
        if child.returncode:raise RuntimeError('GraphS process failure; no retry')
        lines=(folder/'stdout.log').read_text().splitlines()
        timing=json.loads(next(line for line in lines if line.startswith('{')))
        values=[float(x) for x in next(line for line in lines if line.startswith('BREAKDOWN\t')).split('\t')[1:]]
        equal=(folder/'trace.tsv').read_bytes()==expected_trace.read_bytes()
        result=dict(variant=variant,timing=timing,phase_ms=values,peak_rss_mib=observed_peak,
                    process_ms=1000*(time.perf_counter()-start),trace_matches_completed_run=equal)
        save(folder/'result.json',result)
        if not equal:
            state.update(status='validation_failed',reason='trace differs from completed normal run');save(out/'active.json',state)
            raise RuntimeError('Trace mismatch; inspect before continuing')
        print('DONE',label,flush=True)
        return result

    checks=[]
    for variant in ('control','profile'):
        checks.append(execute(previous/'case_small',f'tiny_{variant}',variant,120,
                              previous/'test_threshold40/trace.tsv'))
    save(out/'validation.json',dict(status='passed',checks=checks))
    protocol=json.loads((previous/'protocol.json').read_text())
    case=previous/'case_UNI1'
    assert sha(case/'graph.txt')==protocol['graph_sha256'] and sha(case/'updates.txt')==protocol['updates_sha256']
    results=[]
    for variant in ('control','profile'):
        results.append(execute(case,f'UNI1_{variant}',variant,3600,
                               previous/'UNI1_GraphS_B1_r1/trace.tsv'))
        save(out/'completed_modes.json',results)
    normal,profile=results
    total=profile['timing']['detection_ms'];residual=total-sum(profile['phase_ms'])
    assert residual>=-1e-6
    phases=dict(zip(['classification','maintenance','candidates','answer','other'],profile['phase_ms']))
    phases['other']+=residual
    assert abs(sum(phases.values())-total)<1e-5
    for name,expected in gate['backend'].items():assert sha(classes/name)==expected
    save(out/'summary.json',dict(status='completed',diagnostic_only=True,formal_average_eligible=False,
         method='GraphS third-party locally adapted',dataset='UNI1',batch=1,results=results,
         exclusive_ms=phases,exclusive_pct={k:100*v/total for k,v in phases.items()},
         timer_boundary_residual_ms=residual,profile_over_control_ratio=total/normal['timing']['detection_ms'],
         backend_modified=False,note='One ordered control/profile pair; includes JVM/run variability, not calibrated pure overhead.'))
    save(out/'active.json',dict(status='completed',supervisor_pid=os.getpid(),quality_trace_equal=True))
    print('SAVED',out/'summary.json',flush=True)


if __name__=='__main__':main()
