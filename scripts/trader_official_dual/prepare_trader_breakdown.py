"""Instrument a copy of the official persistent service without repairing it."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

from prepare_delta_breakdown import HEADER
from prepare_service import prepare_service
from prepare_source import replace_once
from validate_interface import save


def function_scope(cpp, name, phase):
    start=cpp.index('void KCycleColorCoding::'+name+'(')
    brace=cpp.index('{',start)
    return cpp[:brace+1]+f'\n    BD_SCOPE(bd_function, {phase});'+cpp[brace+1:]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.root.resolve(),args.output.resolve()
    native=root/'.research_data/common_benchmark/trader_official_native_20260913/build'
    prepare_service(native/'official_source',out,'official')
    original=(out/'cycle_detector.cpp').read_text(encoding='utf-8')
    previous=root/'.research_data/common_benchmark/trader_official_dual_20260913/service_v1/official'
    assert original==(previous/'cycle_detector.cpp').read_text(encoding='utf-8')
    assert (out/'cycle_detector.h').read_bytes()==(previous/'cycle_detector.h').read_bytes()
    cpp='#include "breakdown.h"\n'+original
    for name in ['common_apply','common_finish','process_dynamic_update_by_edge','process_dynamic_update_by_batch','update_edge_weight']:
        cpp=function_scope(cpp,name,'classification')
    cpp=function_scope(cpp,'dp_from_a_node','maintenance')
    cpp=function_scope(cpp,'Output_most_negative_cycle','answer')
    start=cpp.index('void KCycleColorCoding::update_edge_weight(')
    end=cpp.index('void KCycleColorCoding::dp_search_k_cycle(',start)
    fragment=replace_once(cpp[start:end],'    int color_set = 1 << node_colors[src_node];',
                          '    BD_SCOPE(bd_dp, maintenance);\n    int color_set = 1 << node_colors[src_node];')
    cpp=cpp[:start]+fragment+cpp[end:]
    assert cpp.count('    if(rescan_dp_table) {')==2
    cpp=cpp.replace('    if(rescan_dp_table) {','    if(rescan_dp_table) {\n        BD_SCOPE(bd_rescan, candidates);')
    cpp=replace_once(cpp,'                if (cycle_weight < local_best_weight) {',
                     '                if (cycle_weight < local_best_weight) {\n                    BD_SCOPE(bd_best, candidates);')
    cpp=replace_once(cpp,'                if(dst_node == 0){',
                     '                if(dst_node == 0){\n                    BD_SCOPE(bd_zero_dp, maintenance);')
    scripts=Path(__file__).parent
    driver_original=(scripts/'service_driver.cpp').read_text(encoding='utf-8')
    driver='#include "breakdown.h"\n'+driver_original
    driver=replace_once(driver,'    auto select_best=[&] {',
                        '    auto select_best=[&] {\n        BD_SCOPE(bd_winner, answer);')
    driver=replace_once(driver,'        const auto begin=Clock::now();',
                        '        const auto begin=Clock::now();Breakdown::begin();')
    driver=replace_once(driver,'        if(eg || (row+1)%batch==0) {\n            returned=',
                        '        if(eg || (row+1)%batch==0) {\n            BD_SCOPE(bd_copy, answer);\n            returned=')
    driver=replace_once(driver,'        detection_ms+=ms(begin,Clock::now());',
                        '        Breakdown::end();detection_ms+=ms(begin,Clock::now());')
    driver=replace_once(driver,'    const auto flush_begin=Clock::now();',
                        '    const auto flush_begin=Clock::now();Breakdown::begin();')
    driver=replace_once(driver,'    best=select_best();',
                        '    { BD_SCOPE(bd_eof_answer, answer);\n    best=select_best();')
    driver=replace_once(driver,'    detection_ms+=ms(flush_begin,Clock::now());',
                        '    } Breakdown::end();detection_ms+=ms(flush_begin,Clock::now());')
    driver=replace_once(driver,'    const double peak=peak_mib();',r'''    const double peak=peak_mib();
    std::cout<<std::setprecision(17)<<"BREAKDOWN";
    for(auto value:Breakdown::times)std::cout<<'\t'<<value;
    std::cout<<'\n';''')
    (out/'breakdown.h').write_text(HEADER,encoding='utf-8')
    (out/'cycle_detector.cpp').write_text(cpp,encoding='utf-8')
    (out/'service_driver.cpp').write_text(driver,encoding='utf-8')
    diff=''.join(difflib.unified_diff(original.splitlines(True),cpp.splitlines(True),fromfile='service/core',tofile='profile/core'))
    diff+=''.join(difflib.unified_diff(driver_original.splitlines(True),driver.splitlines(True),fromfile='service/driver',tofile='profile/driver'))
    (out/'instrumentation.diff').write_text(diff,encoding='utf-8')
    manifest=json.loads((out/'manifest.json').read_text())
    manifest.update(formal_timing=False,algorithm_modified=False,normal_service_source_equal=True,
         phases=['classification','maintenance','candidates','answer','other'],
         candidate_definition='Closing-state rescans and maintained-best updates; not an explicit candidate index',
         recursive_DP_scopes=False,generated_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.cpp')})
    save(out/'manifest.json',manifest)


if __name__=='__main__':main()
