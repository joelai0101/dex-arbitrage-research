"""Compile frozen DELTA, test full batch boundaries, then five UNI1 single runs."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess

from run_uni1_official import quality, sha
from validate_interface import save

BATCHES=[1,50,100,500,1000]
FROZEN={
    'delta_state_benchmark.cpp':'d83523afc42420380acf627d7e2dd3062d604782765a63a04a0c99d351db3ebe',
    'cycle_recovery_benchmark.cpp':'1b6dd44916857ced81b6b0ef2c36445cc416f09bf208b95f3eda05bd35ef1dd8',
}


def write_colors(path,maps):
    keys=set(maps['0'])
    assert keys==set(map(str,range(len(keys))))
    assert all(set(m)==keys for m in maps.values())
    path.write_text(''.join(' '.join(str(maps[str(t)][str(v)]) for v in range(len(keys)))+'\n'
                            for t in range(len(maps))),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    base=root/'.research_data/common_benchmark'
    dual=base/'trader_official_dual_20260913'
    common=base/'trader_common_input_20260913_v2/UNI1'
    colors=dual/'interface_v2/UNI1_all_arrival_colors.json'
    native=base/'trader_official_native_20260913/build'
    env=dict(os.environ,PATH=str(native)+os.pathsep+os.environ['PATH'])
    def run(command,label,folder=out,timeout=120,formal=False):
        print('START',label,flush=True)
        with (folder/f'{label}.stdout.log').open('wb') as stdout,(folder/f'{label}.stderr.log').open('wb') as stderr:
            process=subprocess.Popen(list(map(str,command)),cwd=root,env=env,stdout=stdout,stderr=stderr)
            state=dict(status='running',phase=label,pid=process.pid,supervisor_pid=os.getpid(),
                       started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       timeout_s=timeout,formal_benchmark=formal,command=list(map(str,command)))
            save(out/'active.json',state)
            try: code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                print('HARD TIMEOUT',label,'terminating',flush=True)
                process.kill();process.wait();state.update(status='timeout');save(out/'active.json',state);raise
        state.update(status='completed' if code==0 else 'failed',returncode=code)
        save(folder/f'{label}.process.json',state);save(out/'active.json',state)
        if code: raise RuntimeError(f'{label} failed: {code}')
        print('DONE',label,flush=True)
        return (folder/f'{label}.stdout.log').read_text()
    build=out/'build';build.mkdir()
    for name,expected in FROZEN.items():
        source=base/'trader_corrected_20260909/build'/name
        assert sha(source)==expected
        shutil.copy2(source,build/name)
    scripts=Path(__file__).resolve().parent
    shutil.copy2(scripts/'delta_service_driver.cpp',build/'delta_service_driver.cpp')
    binary=build/'delta_service.exe'
    compiler=root/'.venv/toolchains/llvm-mingw-20260616-ucrt-x86_64/bin/clang++.exe'
    run([compiler,'-O3','-std=c++17',build/'delta_service_driver.cpp','-lpsapi','-o',binary],'compile')
    save(build/'manifest.json',dict(core_sha256=FROZEN,binary_sha256=sha(binary),
         driver_sha256=sha(build/'delta_service_driver.cpp'),core_modified=False,
         initialization_adapter='Only initially observed roots; unseen root ensure on first arrival',
         execution_model='persistent_best_of_ell',color_source=str(colors)))
    write_colors(out/'colors.txt',json.loads(colors.read_text()))
    # A future minimum-ID root and updates around every internal batch boundary.
    tiny=out/'boundary_fixture';tiny.mkdir()
    graph={(base+i,base+(i+1)%5):w for base,w in [(1,-2),(6,-1)] for i in range(5)}
    (tiny/'graph.txt').write_text(''.join(f'{u} {v} {w}\n' for (u,v),w in graph.items()))
    updates=['0 0 N']*1002
    events={1:'6 7 -12',2:'1 2 -20',49:'1 2 5',50:'6 7 -1',51:'1 2 -2',
            99:'6 7 -6',100:'6 7 -12',101:'6 7 -12',499:'1 2 -20',500:'1 2 5',
            501:'6 7 -1',999:'1 2 -2',1000:'6 7 -12',1001:'0 2 -30',1002:'5 0 -1'}
    for row,line in events.items():updates[row-1]=line
    (tiny/'updates.txt').write_text('\n'.join(updates)+'\n')
    tiny_colors={'0':{str(v):(v-1)%5 if v else 0 for v in range(11)}}
    save(tiny/'colors.json',tiny_colors);write_colors(tiny/'colors.txt',tiny_colors)
    oracle=base/'alignment_exact5_20260909/exact5.exe'
    run([oracle,tiny,tiny/'oracle.tsv'],'tiny_oracle')
    checks=[]
    for batch in BATCHES:
        trace=tiny/f'B{batch}.tsv'
        raw=run([binary,tiny/'graph.txt',tiny/'updates.txt',tiny/'colors.txt',5,1,batch,trace],f'tiny_B{batch}')
        result=json.loads(next(l for l in raw.splitlines() if l.startswith('{')))
        q=quality(tiny,trace,tiny/'oracle.tsv',tiny/'colors.json',
                  publication_rows=set(range(batch,1003,batch))|{1002},final_eof=True)
        assert result['initial_vertices']==10 and result['final_observed_vertices']==11
        assert q['path_quality_complete'] and abs(q['path_mean_regret'])<1e-10
        assert not q['counts']['reported_weight_mismatch'] and not q['counts']['color_violation']
        assert q['counts']['optimal']==q['scored_snapshots']
        q.pop('details');checks.append(dict(batch=batch,quality=q))
    save(out/'boundary_validation.json',dict(status='passed',checks=checks,
         covers=['interior batch boundaries','repeated edges','increases','decreases','ties','N','future minimum root','EOF remainder']))
    # Reuse the independently rebuilt, same-input full oracle, not new timing.
    reference=dual/'UNI1_official_EG_r1/oracle.tsv'
    original_manifest=json.loads((dual/'UNI1_official_EG_r1/manifest.json').read_text())
    for p in [common/'graph.txt',common/'updates.txt',colors]:
        assert original_manifest['files'][str(p)]==sha(p)
    save(out/'protocol.json',dict(dataset='UNI1',k=5,ell=80,batches=BATCHES,round=1,
         input_sha256={str(p):sha(p) for p in [common/'graph.txt',common/'updates.txt',colors]},
         oracle_sha256=sha(reference),binary_sha256=sha(binary),
         detection_contract='Per-arrival parse/root activation/buffer/apply/query/winner/answer copy plus EOF; external IO and initialization excluded',
         memory_contract='OS whole-process peak through EOF, all 80 instances resident',
         core_modified=False))
    results=[]
    for batch in BATCHES:
        folder=out/f'UNI1_DELTA_B{batch}_r1';folder.mkdir()
        raw=run([binary,common/'graph.txt',common/'updates.txt',out/'colors.txt',5,80,batch,folder/'trace.tsv'],
                f'UNI1_B{batch}',folder,3600,True)
        result=json.loads(next(l for l in raw.splitlines() if l.startswith('{')))
        assert result['updates']==7628 and result['initial_vertices']==4152 and result['final_observed_vertices']==4156
        result['detection_ms_per_update']=result['detection_ms']/7628
        result['updates_per_second']=7628000/result['detection_ms']
        save(folder/'timing_result.json',result)
        arrivals=quality(common,folder/'trace.tsv',reference,colors)
        publications=quality(common,folder/'trace.tsv',reference,colors,
                             publication_rows=set(range(batch,7629,batch))|{7628},final_eof=True)
        save(folder/'quality_details.json',arrivals.pop('details'));publications.pop('details')
        save(folder/'quality_summary.json',dict(per_arrival=arrivals,at_publication=publications))
        results.append(dict(batch=batch,timing=result,per_arrival=arrivals,at_publication=publications))
        print(json.dumps(dict(batch=batch,ms_per_update=result['detection_ms_per_update'],peak_mib=result['peak_rss_mib'],
                              arrival_RE=arrivals['path_relative_error_pct'],publication_RE=publications['path_relative_error_pct'])),flush=True)
    save(out/'summary.json',dict(status='completed',single_run=True,results=results))
    save(out/'active.json',dict(status='completed',supervisor_pid=os.getpid(),completed_batches=BATCHES))


if __name__=='__main__': main()
