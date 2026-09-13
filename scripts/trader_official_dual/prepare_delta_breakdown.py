"""Generate an instrumented COPY of hash-pinned DELTA; no core algorithm edits."""
import argparse
import difflib
import hashlib
from pathlib import Path

from prepare_source import replace_once
from run_delta_uni1 import FROZEN
from validate_interface import save

HEADER = r'''
#include <chrono>
#include <array>
namespace Breakdown {
enum Phase { classification, maintenance, candidates, answer, other, count };
#ifdef COMMON_BREAKDOWN
using Clock = std::chrono::steady_clock;
inline std::array<double,count> times{};
inline bool active=false;
inline Phase current=other;
inline Clock::time_point last;
inline void charge(Clock::time_point now) {
    times[current]+=std::chrono::duration<double,std::milli>(now-last).count();last=now;
}
inline void begin(){current=other;last=Clock::now();active=true;}
inline void end(){charge(Clock::now());active=false;}
struct Scope {
    bool enabled;Phase previous;
    explicit Scope(Phase phase):enabled(active && phase!=current),previous(current) {
        if(enabled){charge(Clock::now());current=phase;}
    }
    ~Scope(){if(enabled){charge(Clock::now());current=previous;}}
};
#define BD_SCOPE(name, phase) Breakdown::Scope name(Breakdown::phase)
#else
inline std::array<double,count> times{};
inline void begin(){}
inline void end(){}
#define BD_SCOPE(name, phase)
#endif
}
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    source=root/'.research_data/common_benchmark/trader_corrected_20260909/build'
    blobs={name:(source/name).read_bytes() for name in FROZEN}
    assert all(hashlib.sha256(blobs[n]).hexdigest()==h for n,h in FROZEN.items())
    out.mkdir(parents=True,exist_ok=False)
    original=blobs['delta_state_benchmark.cpp'].decode('utf-8')
    cpp='#include "breakdown.h"\n'+original
    cpp=replace_once(cpp,'    void propagate(){','    void propagate(){\n        BD_SCOPE(bd_propagate, maintenance);')
    cpp=replace_once(cpp,'                if(level==k+1){','                if(level==k+1){\n                    BD_SCOPE(bd_candidates, candidates);')
    cpp=replace_once(cpp,'        auto t=Clock::now();std::map<std::pair<int,int>,Update> last;',
                     '        BD_SCOPE(bd_apply, classification);\n        auto t=Clock::now();std::map<std::pair<int,int>,Update> last;')
    cpp=replace_once(cpp,'        // All final weights are installed before marking or evaluating states.',
                     '        BD_SCOPE(bd_dependencies, maintenance);\n        // All final weights are installed before marking or evaluating states.')
    cpp=replace_once(cpp,'    std::pair<double,std::vector<int>> query(){',
                     '    std::pair<double,std::vector<int>> query(){\n        BD_SCOPE(bd_query, answer);')
    driver_path=Path(__file__).with_name('delta_service_driver.cpp')
    driver_original=driver_path.read_text(encoding='utf-8')
    driver=replace_once(driver_original,'        const auto begin=Clock::now();auto update=decode(updates[row]);',
                       '        const auto begin=Clock::now();Breakdown::begin();\n        { BD_SCOPE(bd_arrival, classification);auto update=decode(updates[row]);')
    driver=replace_once(driver,'            observed[v]=true;',
                       '            BD_SCOPE(bd_new_root, maintenance);\n            observed[v]=true;')
    driver=replace_once(driver,'        pending.push_back(update);','        pending.push_back(update); }')
    driver=replace_once(driver,'        detection_ms+=ms(begin,Clock::now());',
                       '        Breakdown::end();detection_ms+=ms(begin,Clock::now());')
    driver=replace_once(driver,'    const auto flush_begin=Clock::now();',
                       '    const auto flush_begin=Clock::now();Breakdown::begin();')
    driver=replace_once(driver,'    detection_ms+=ms(flush_begin,Clock::now());',
                       '    Breakdown::end();detection_ms+=ms(flush_begin,Clock::now());')
    driver=replace_once(driver,'        best=select_best();returned_weight=weights[best];returned=paths[best];pending.clear();',
                       '        BD_SCOPE(bd_winner, answer);\n        best=select_best();returned_weight=weights[best];returned=paths[best];pending.clear();')
    driver=replace_once(driver,'    emit("eof",updates.size());',r'''    emit("eof",updates.size());
    std::cout<<std::setprecision(17)<<"BREAKDOWN";
    for(auto value:Breakdown::times)std::cout<<'\t'<<value;
    std::cout<<'\n';''')
    (out/'breakdown.h').write_text(HEADER,encoding='utf-8')
    (out/'delta_state_benchmark.cpp').write_text(cpp,encoding='utf-8')
    (out/'cycle_recovery_benchmark.cpp').write_bytes(blobs['cycle_recovery_benchmark.cpp'])
    (out/'delta_service_driver.cpp').write_text(driver,encoding='utf-8')
    diff=''.join(difflib.unified_diff(original.splitlines(True),cpp.splitlines(True),fromfile='frozen/core',tofile='profile/core'))
    diff+=''.join(difflib.unified_diff(driver_original.splitlines(True),driver.splitlines(True),fromfile='normal/driver',tofile='profile/driver'))
    (out/'instrumentation.diff').write_text(diff,encoding='utf-8')
    save(out/'manifest.json',dict(frozen_sha256=FROZEN,driver_sha256=hashlib.sha256(driver_original.encode()).hexdigest(),
         phases=['classification','maintenance','candidates','answer','other'],exclusive_nested_scopes=True,
         initialization_profiled=False,algorithm_modified=False,formal_timing=False,
         clock_only_on_phase_transition=True,
         generated_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.cpp')}))


if __name__=='__main__':main()
