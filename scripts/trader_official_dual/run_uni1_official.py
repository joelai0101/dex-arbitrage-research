"""One full UNI1 official-core mode, followed by separate exact quality checks."""
import argparse
import csv
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess

from validate_interface import MODES, save


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quality(case, trace_path, oracle_path, color_path):
    live={(int(u),int(v)):float(w) for u,v,w in
          (line.split() for line in (case/'graph.txt').read_text().splitlines())}
    updates=[line.split() for line in (case/'updates.txt').read_text().splitlines()]
    colors=json.loads(color_path.read_text())
    with trace_path.open() as f: trace=list(csv.DictReader(f,delimiter='\t'))
    with oracle_path.open() as f: refs=list(csv.DictReader(f,delimiter='\t'))
    arrivals=[a for a in trace if a['phase']=='arrival']
    assert len(arrivals)==len(updates) and len(refs)==len(updates)+1
    counts=dict(missing=0,invalid_path=0,reported_weight_mismatch=0,color_violation=0,
                below_oracle=0,no_finite_reference=0,near_zero_reference=0,optimal=0)
    gaps,relative,details=[],[],[]
    for row,(update,answer) in enumerate(zip(updates,arrivals),1):
        assert int(answer['row'])==row and int(refs[row]['row'])==row
        u,v,w=update
        if w!='N': live[int(u),int(v)]=float(w)
        path=[int(v) for v in answer['path'].split()]
        actual=None
        if not path: counts['missing']+=1
        elif len(path)!=6 or path[0]!=path[-1] or len(set(path[:-1]))!=5 or not all((u,v) in live for u,v in zip(path,path[1:])):
            counts['invalid_path']+=1
        else:
            actual=math.fsum(live[u,v] for u,v in zip(path,path[1:]))
            if len({colors[answer['coloring']][str(v)] for v in path[:-1]})!=5: counts['color_violation']+=1
        reported=float(answer['weight'])
        ref=float(refs[row]['weight']) if refs[row]['weight']!='none' else None
        if actual is not None and (not math.isfinite(reported) or abs(actual-reported)>1e-10): counts['reported_weight_mismatch']+=1
        if ref is None or not math.isfinite(ref): counts['no_finite_reference']+=1
        elif actual is not None:
            gap=actual-ref
            if gap < -1e-10: counts['below_oracle']+=1
            gaps.append(gap)
            counts['optimal']+=abs(gap)<=1e-10
            if abs(ref)>1e-12: relative.append(abs(gap)/abs(ref))
            else: counts['near_zero_reference']+=1
        details.append(dict(row=row,reported_weight=reported if math.isfinite(reported) else None,
                            actual_weight=actual,oracle_weight=ref))
    complete=not any(counts[k] for k in ['missing','invalid_path','below_oracle','no_finite_reference'])
    return dict(updates=len(updates),counts=counts,path_quality_complete=complete,
                path_relative_error_pct=100*statistics.fmean(relative) if complete and relative else None,
                path_mean_regret=statistics.fmean(gaps) if complete else None,
                path_cumulative_regret=math.fsum(gaps) if complete else None,
                optimal_hit_pct=100*counts['optimal']/len(updates),
                reference='independent global exact-5 oracle on the same input',
                quality_basis='Actual weight of the returned legal path, not a possibly stale reported weight',
                reported_weight_correct=counts['reported_weight_mismatch']==0,
                details=details)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--service',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=[m[0] for m in MODES],required=True)
    args=parser.parse_args()
    root,service,out=args.root.resolve(),args.service.resolve(),args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    base=root/'.research_data/common_benchmark'
    case=base/'trader_common_input_20260913_v2/UNI1'
    colors=base/'trader_official_dual_20260913/interface_v2/UNI1_all_arrival_colors.json'
    native=base/'trader_official_native_20260913/build'
    seeds=root/'6D/code/.upstream/TRADER/seeds.txt'
    binary=service/'official_normal.exe'
    regression=json.loads((service/'service_regression.json').read_text())
    assert regression['status']=='passed'
    build=json.loads((service/'summary.json').read_text())
    assert sha(binary)==build['binary_sha256']['official_False']
    mode,batch,eg=next(m for m in MODES if m[0]==args.mode)
    manifest=dict(dataset='UNI1',method='TRADER official core',mode=mode,k=5,ell=80,
                  batch_parameter=batch,eg_enabled=bool(eg),round=1,
                  binary_sha256=sha(binary),core_commit='8e047fdf35e8c44f189a59f506431b4a180124ca',
                  files={str(p):sha(p) for p in [case/'graph.txt',case/'updates.txt',seeds,colors]},
                  execution_model='persistent best-of-80 service',
                  detection_contract='Sum per-arrival core calls, winner selection and answer copy, plus EOF flush; excludes initialization, file IO and offline quality',
                  memory_contract='OS PeakWorkingSetSize, entire process through EOF, all 80 instances resident',
                  quality_contract='Per-arrival available path, initialized answer retained between fixed batches; EOF separate',
                  baseline_status='official-core measurement; final main-table selection pending')
    save(out/'manifest.json',manifest)
    env=dict(os.environ,PATH=str(native)+os.pathsep+os.environ['PATH'])
    def run(command,label,timeout):
        print('START',label,flush=True)
        with (out/f'{label}.stdout.log').open('wb') as stdout,(out/f'{label}.stderr.log').open('wb') as stderr:
            process=subprocess.Popen(list(map(str,command)),cwd=root,env=env,stdout=stdout,stderr=stderr)
            state=dict(status='running',phase=label,pid=process.pid,supervisor_pid=os.getpid(),
                       started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),timeout_s=timeout)
            save(out/'active.json',state)
            try: code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                print('HARD TIMEOUT',label,'terminating',flush=True)
                process.kill(); process.wait();state.update(status='timeout');save(out/'active.json',state);raise
        state.update(status='completed' if code==0 else 'failed',returncode=code)
        save(out/f'{label}.process.json',state);save(out/'active.json',state)
        if code: raise RuntimeError(f'{label} failed: {code}')
        print('DONE',label,flush=True)
        return (out/f'{label}.stdout.log').read_text()
    raw=run([binary,case/'graph.txt',case/'updates.txt',seeds,5,80,batch,eg,out/'trace.tsv'],'timing',3600)
    result=json.loads(next(line for line in raw.splitlines() if line.startswith('{')))
    assert result['updates']==7628 and result['ell']==80
    result['detection_ms_per_update']=result['detection_ms']/result['updates']
    result['updates_per_second']=1000*result['updates']/result['detection_ms']
    save(out/'timing_result.json',result)
    oracle=base/'alignment_exact5_20260909/exact5.exe'
    manifest['oracle_sha256']=sha(oracle)
    save(out/'manifest.json',manifest)
    run([oracle,case,out/'oracle.tsv'],'offline_oracle',360)
    q=quality(case,out/'trace.tsv',out/'oracle.tsv',colors)
    save(out/'quality_details.json',q.pop('details'))
    save(out/'quality_summary.json',q)
    save(out/'active.json',dict(status='completed',mode=mode,supervisor_pid=os.getpid(),
                               result='full_single_run_with_path_quality',main_table_selection_pending=True))
    print(json.dumps(dict(timing=result,quality=q),indent=2),flush=True)


if __name__=='__main__':
    main()
