"""Validate the GraphS common-input/timer adapter, then one full UNI1 run."""
import argparse
import ctypes as ct
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from prepare_graphs_common import prepare,SOURCE_SHA
from run_uni1_official import quality,sha
from validate_interface import save


class Memory(ct.Structure):
    _fields_=[('cb',ct.c_ulong),('faults',ct.c_ulong)]+[(n,ct.c_size_t) for n in
        ['peak','working','quota_peak_paged','quota_paged','quota_peak_nonpaged','quota_nonpaged','pagefile','peak_pagefile']]


def peak(handle):
    get=ct.windll.psapi.GetProcessMemoryInfo
    get.argtypes=[ct.c_void_p,ct.POINTER(Memory),ct.c_ulong];get.restype=ct.c_int
    memory=Memory();memory.cb=ct.sizeof(memory)
    if not get(int(handle),ct.byref(memory),ct.sizeof(memory)):raise RuntimeError('OS peak sampling failed')
    return memory.peak/1048576


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    base=root/'.research_data/common_benchmark';dual=base/'trader_official_dual_20260913'
    assert json.loads((dual/'official_fixed_UNI1_r1/active.json').read_text())['status']=='completed'
    out.mkdir(parents=True,exist_ok=False)
    gate=json.loads((base/'paper_alignment_20260913/graphs_length_index/validation.json').read_text())
    classes=root/Path(gate['graphs_classes'])
    for name,expected in gate['backend'].items():assert sha(classes/name)==expected
    jar=root/'.venv/java-libs/jgrapht-core-1.4.0.jar';assert sha(jar)==gate['jar_sha256']
    source=root/'.worktrees/paper-baseline-alignment/graphs_paper_alignment/GraphSWeightedBenchmark.java'
    build=out/'build';build.mkdir();newclasses=build/'classes';newclasses.mkdir()
    prepare(source,build/'GraphSWeightedBenchmark.java')
    shutil.copy2(Path(__file__).with_name('GraphSCommonDriver.java'),build/'GraphSCommonDriver.java')
    java=Path('C:/Program Files/Java/jdk-25.0.3/bin/java.exe')
    javac=java.with_name('javac.exe')
    cp=str(newclasses)+os.pathsep+str(classes)+os.pathsep+str(jar)
    compile_command=[javac,'-cp',str(classes)+os.pathsep+str(jar),'-d',newclasses,
                     build/'GraphSWeightedBenchmark.java',build/'GraphSCommonDriver.java']
    with (build/'compile.stdout.log').open('wb') as stdout,(build/'compile.stderr.log').open('wb') as stderr:
        p=subprocess.run(list(map(str,compile_command)),stdout=stdout,stderr=stderr,timeout=120,cwd=root)
    if p.returncode:raise RuntimeError('GraphS common adapter compilation failed')
    save(build/'manifest.json',dict(source_sha256=SOURCE_SHA,backend_classes_unchanged=gate['backend'],
         generated_source_sha256=sha(build/'GraphSWeightedBenchmark.java'),driver_sha256=sha(build/'GraphSCommonDriver.java'),
         class_sha256={p.name:sha(p) for p in newclasses.glob('*.class')},jar_sha256=sha(jar),
         source_change='Only initially observed vertices; add future endpoints through public forward/reverse graph API',
         backend_modified=False,compiler_command=list(map(str,compile_command))))
    def execute(case,folder,threshold,formal=False):
        folder.mkdir(parents=True,exist_ok=False)
        command=[java,'-Xmx16g','-cp',cp,'GraphSCommonDriver',case,5,folder/'trace.tsv',threshold]
        start=time.perf_counter();observed_peak=0.;ack=False;next_log=30
        timeout=3600 if formal else 120
        print('START',folder.name,flush=True)
        with (folder/'stdout.log').open('wb') as stdout,(folder/'stderr.log').open('wb') as stderr:
            child=subprocess.Popen(list(map(str,command)),cwd=root,stdout=stdout,stderr=stderr,stdin=subprocess.PIPE)
            state=dict(status='running',phase=folder.name,pid=child.pid,supervisor_pid=os.getpid(),
                       started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       timeout_s=timeout,formal_benchmark=formal,command=list(map(str,command)),target=str(folder))
            save(out/'active.json',state)
            while child.poll() is None:
                observed_peak=max(observed_peak,peak(child._handle))
                if not ack and (folder/'stdout.log').stat().st_size:
                    lines=(folder/'stdout.log').read_text().splitlines()
                    if lines and lines[-1].startswith('{') and lines[-1].endswith('}'):
                        observed_peak=max(observed_peak,peak(child._handle))
                        child.stdin.write(b'\n');child.stdin.flush();ack=True
                elapsed=time.perf_counter()-start
                if elapsed>=timeout:
                    print('HARD TIMEOUT; terminating',folder.name,flush=True)
                    child.kill();child.wait();state.update(status='timeout');save(out/'active.json',state);raise RuntimeError('GraphS timeout; no retry')
                if elapsed>=next_log:
                    print('RUNNING',folder.name,'seconds',round(elapsed),'peak_MiB',round(observed_peak),flush=True);next_log+=30
                time.sleep(.25)
        state.update(status='completed' if child.returncode==0 else 'failed',returncode=child.returncode)
        save(folder/'process.json',state);save(out/'active.json',state)
        if child.returncode:raise RuntimeError('GraphS process failed; no retry')
        result=json.loads((folder/'stdout.log').read_text().splitlines()[-1])
        result.update(peak_rss_mib=observed_peak,process_ms=1000*(time.perf_counter()-start),formal_benchmark=formal)
        result['detection_ms_per_update']=result['detection_ms']/result['updates']
        result['updates_per_second']=1000*result['updates']/result['detection_ms']
        save(folder/'timing_result.json',result)
        print('DONE',folder.name,flush=True)
        return result
    tiny=out/'case_small';tiny.mkdir()
    old_tiny=dual/'DELTA_UNI1_batches_r1/boundary_fixture'
    for name in ['graph.txt','updates.txt']:shutil.copy2(old_tiny/name,tiny/name)
    (tiny/'colors.txt').write_text('0\n'*11)
    checks=[]
    for threshold in [1,3,40]:
        folder=out/f'test_threshold{threshold}'
        result=execute(tiny,folder,threshold)
        q=quality(tiny,folder/'trace.tsv',old_tiny/'oracle.tsv',old_tiny/'colors.json',check_colors=False)
        assert result['initial_vertices']==10 and result['final_vertices']==11 and result['updates']==1002
        assert q['path_quality_complete'] and q['counts']['optimal']==1002 and q['counts']['reported_weight_mismatch']==0
        q.pop('details');checks.append(dict(threshold=threshold,quality=q))
    save(out/'validation.json',dict(status='passed',checks=checks,backend_modified=False))
    common=base/'trader_common_input_20260913_v2/UNI1'
    colors=dual/'interface_v2/UNI1_all_arrival_colors.json'
    case=out/'case_UNI1';case.mkdir()
    reference=dual/'UNI1_official_EG_r1'
    refmanifest=json.loads((reference/'manifest.json').read_text())
    for name in ['graph.txt','updates.txt']:
        assert refmanifest['files'][str(common/name)]==sha(common/name)
        shutil.copy2(common/name,case/name)
    (case/'colors.txt').write_text('0\n'*4156) # ID capacity only; all color filters are off.
    save(out/'protocol.json',dict(dataset='UNI1',round=1,k=5,batch=1,ell=None,instances=1,hp_threshold=40,
         graph_sha256=sha(case/'graph.txt'),updates_sha256=sha(case/'updates.txt'),oracle_sha256=sha(reference/'oracle.tsv'),
         detection_contract='Per-arrival parse, graph/index/candidate maintenance, winner lookup and answer copy, plus EOF; init and external IO excluded',
         memory_contract='OS PeakWorkingSetSize; complete live service through EOF, sampled before Java stdin acknowledgement',
         source_label='GraphS third-party implementation, locally adapted; not author official code'))
    measured=out/'UNI1_GraphS_B1_r1'
    result=execute(case,measured,40,True)
    assert result['updates']==7628 and result['initial_vertices']==4152 and result['final_vertices']==4156
    q=quality(case,measured/'trace.tsv',reference/'oracle.tsv',colors,check_colors=False)
    save(measured/'quality_details.json',q.pop('details'));save(measured/'quality_summary.json',q)
    for name,expected in gate['backend'].items():assert sha(classes/name)==expected
    save(out/'active.json',dict(status='completed',supervisor_pid=os.getpid(),quality_complete=q['path_quality_complete']))
    save(out/'summary.json',dict(status='completed',single_run=True,timing=result,quality=q,backend_modified=False))
    print(json.dumps(dict(timing=result,quality=q),indent=2),flush=True)


if __name__=='__main__':main()
