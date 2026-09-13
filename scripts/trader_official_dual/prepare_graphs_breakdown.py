"""Coarse exclusive GraphS adapter scopes; never instrument per-candidate loops."""
import argparse
import difflib
from pathlib import Path

from prepare_source import replace_once
from prepare_graphs_common import prepare
from run_uni1_official import sha
from validate_interface import save

PROFILER = '''
final class GraphSBreakdown {
    static final boolean ENABLED=Boolean.getBoolean("common.breakdown");
    static final int CLASSIFICATION=0,MAINTENANCE=1,CANDIDATES=2,ANSWER=3,OTHER=4;
    static final long[] nanos=new long[5];
    static boolean active=false;static int current=OTHER;static long last;
    static void charge(long now){nanos[current]+=now-last;last=now;}
    static void begin(){if(ENABLED){current=OTHER;last=System.nanoTime();active=true;}}
    static void end(){if(ENABLED){charge(System.nanoTime());active=false;}}
    static final class Scope implements AutoCloseable {
        final boolean enabled;final int previous;
        Scope(int phase){enabled=ENABLED&&active;previous=current;
            if(enabled){charge(System.nanoTime());current=phase;}}
        public void close(){if(enabled){charge(System.nanoTime());current=previous;}}
    }
    static void print(){StringBuilder s=new StringBuilder("BREAKDOWN");
        for(long n:nanos)s.append('\\t').append(n/1e6);System.out.println(s);}
}
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    source=root/'.worktrees/paper-baseline-alignment/graphs_paper_alignment/GraphSWeightedBenchmark.java'
    target=out/'GraphSWeightedBenchmark.java'
    prepare(source,target)
    original=target.read_text(encoding='utf-8')
    previous=root/'.research_data/common_benchmark/trader_official_dual_20260913/GraphS_UNI1_common_r1/build'
    assert original==(previous/'GraphSWeightedBenchmark.java').read_text(encoding='utf-8')
    text=replace_once(original,'                if(!colorful||colors[u.u]!=colors[u.v])\n                    for(List<CustomVertex> cycle:simulator.insertEdge',
                     '                try(var bd=new GraphSBreakdown.Scope(GraphSBreakdown.MAINTENANCE)) {\n                if(!colorful||colors[u.u]!=colors[u.v])\n                    for(List<CustomVertex> cycle:simulator.insertEdge')
    text=replace_once(text,'            } else if(old.doubleValue()!=u.weight)',
                     '                }\n            } else if(old.doubleValue()!=u.weight)')
    text=replace_once(text,'        for(Update u:weightChanges)dirty.addAll(affected(u.u,u.v));',
                     '        try(var bd=new GraphSBreakdown.Scope(GraphSBreakdown.MAINTENANCE)) {\n        for(Update u:weightChanges)dirty.addAll(affected(u.u,u.v));\n        }')
    text=replace_once(text,'        for(List<Integer> path:dirty)refresh(path);',
                     '        try(var bd=new GraphSBreakdown.Scope(GraphSBreakdown.CANDIDATES)) {\n        for(List<Integer> path:dirty)refresh(path);\n        }')
    driver_path=Path(__file__).with_name('GraphSCommonDriver.java')
    driver_original=driver_path.read_text(encoding='utf-8')
    driver=replace_once(driver_original,'                long begin=System.nanoTime();',
                       '                long begin=System.nanoTime();GraphSBreakdown.begin();\n                try(var bd=new GraphSBreakdown.Scope(GraphSBreakdown.CLASSIFICATION)) {')
    driver=replace_once(driver,'                engine.apply(Collections.singletonList(update));',
                       '                engine.apply(Collections.singletonList(update));\n                }\n                try(var bd=new GraphSBreakdown.Scope(GraphSBreakdown.ANSWER)) {')
    driver=replace_once(driver,'                detection+=(System.nanoTime()-begin)/1e6;',
                       '                } GraphSBreakdown.end();detection+=(System.nanoTime()-begin)/1e6;')
    driver=replace_once(driver,'\n            long begin=System.nanoTime();',
                       '\n            long begin=System.nanoTime();GraphSBreakdown.begin();\n            try(var bd=new GraphSBreakdown.Scope(GraphSBreakdown.ANSWER)) {')
    driver=replace_once(driver,'            detection+=(System.nanoTime()-begin)/1e6;',
                       '            } GraphSBreakdown.end();detection+=(System.nanoTime()-begin)/1e6;')
    driver=replace_once(driver,'            System.out.println("{',
                       '            GraphSBreakdown.print();\n            System.out.println("{')
    target.write_text(text,encoding='utf-8')
    (out/'GraphSCommonDriver.java').write_text(driver,encoding='utf-8')
    (out/'GraphSBreakdown.java').write_text(PROFILER,encoding='utf-8')
    diff=''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='common/adapter',tofile='profile/adapter'))
    diff+=''.join(difflib.unified_diff(driver_original.splitlines(True),driver.splitlines(True),fromfile='common/driver',tofile='profile/driver'))
    (out/'instrumentation.diff').write_text(diff,encoding='utf-8')
    save(out/'profile_manifest.json',dict(algorithm_modified=False,backend_modified=False,
         source_matches_completed_run=True,formal_timing=False,per_candidate_clocks=False,
         phase_definition=dict(classification='Parse/coalesce/graph metadata and arrival vertices',
             maintenance='HP-index insertion and affected-path queries plus canonicalization/dirty-set collection',
             candidates='Whole dirty-candidate refresh/ranking loop',answer='Ranking winner and path copy',other='Residual'),
         deletion_scope='Common UNI input rejects D; deletion subphases are not instrumented separately',
         generated_sha256={p.name:sha(p) for p in out.glob('*.java')}))


if __name__=='__main__':main()
