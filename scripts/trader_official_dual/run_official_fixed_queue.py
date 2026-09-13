"""Serial full UNI1 fixed modes after boundary fidelity passes; no EG rerun."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from validate_interface import save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    base=root/'.research_data/common_benchmark/trader_official_dual_20260913'
    assert json.loads((base/'trader_boundary_validation/validation.json').read_text())['status']=='passed'
    out.mkdir(parents=True,exist_ok=False)
    script=Path(__file__).resolve().with_name('run_uni1_official.py')
    completed=[]
    for mode in ['B1','B50','B100','B500','B1000']:
        folder=out/f'UNI1_official_{mode}_r1'
        command=[sys.executable,str(script),'--root',str(root),'--service',str(base/'service_v1'),
                 '--output',str(folder),'--mode',mode,'--reuse-oracle-from',str(base/'UNI1_official_EG_r1')]
        print('START',mode,flush=True)
        with (out/f'{mode}.stdout.log').open('wb') as stdout,(out/f'{mode}.stderr.log').open('wb') as stderr:
            p=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr)
            state=dict(status='running',mode=mode,child_supervisor_pid=p.pid,supervisor_pid=os.getpid(),
                       started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       child_active_file=str(folder/'active.json'),completed=completed,
                       timeout_contract='Each child enforces 3600s core timeout; no automatic retries')
            save(out/'active.json',state)
            code=p.wait()
        if code:
            state.update(status='failed',returncode=code);save(out/'active.json',state)
            raise RuntimeError(f'{mode} failed; remaining modes not automatically retried')
        result=json.loads((folder/'timing_result.json').read_text())
        q=json.loads((folder/'quality_summary.json').read_text())
        completed.append(dict(mode=mode,timing=result,quality=q))
        save(out/'completed_modes.json',completed)
        print('DONE',mode,result['detection_ms_per_update'],flush=True)
    save(out/'active.json',dict(status='completed',supervisor_pid=os.getpid(),completed_modes=5))


if __name__=='__main__':main()
