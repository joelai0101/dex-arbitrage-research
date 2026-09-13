"""Reproducible interface patch over pinned, locally supplied TRADER sources.

No upstream source is vendored. The oldnew and minpatch variants are diagnostic
stages, NOT completed/corrected Edge Grouping implementations.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

COMMIT = '8e047fdf35e8c44f189a59f506431b4a180124ca'
HASHES = {
    'directed_graph.cpp': 'ba40efd2296d464928869a7a7d5ccb60ef191182bc253965a94c6d08dd32fe6a',
    'directed_graph.h': '496464a14aaf550e2c337c81a5dccbf0a9519201daad8361f6d60f24a7d0e2bd',
    'cycle_detector.cpp': '339a41ef6b1a21188370f63835b5c659c77ed3def932e23a6568604eb66ccf87',
    'cycle_detector.h': '70850c9dfc08ec7937e1ab4fccf301d893bb94ed1a45996ef3656e5453910b3a',
    'dp_with_filter_full.cpp': 'f1751d9f0b280840fa6b4b45260f62f8fc1eebb472f3f0f000a7d413de9527e3',
}

PREAMBLE = r'''
#include <functional>
#include <cmath>
#include <stdexcept>
// Shared input interface: normalized finite updates or an explicit no-op.
struct CommonUpdate { uint32_t u, v; bool noop; };
static CommonUpdate common_decode(const std::string& line) {
    std::istringstream input(line);
    uint32_t u, v;
    std::string token;
    if (!(input >> u >> v >> token)) throw std::runtime_error("Malformed common update");
    if (token == "N") return {u, v, true};
    size_t consumed = 0;
    double w = std::stod(token, &consumed);
    if (consumed != token.size() || !std::isfinite(w) || w > 1000)
        throw std::runtime_error("Input is not normalized");
    return {u, v, false};
}
'''

COLOR_INTERFACE = r'''
        // Fix future colors in first-arrival order, independent of batching.
        // This updates colors only; future vertices are NOT added to the graph.
        auto common_arrival_colors = [&](const CommonUpdate& update) {
            if (update.noop) return;
            for (auto v : {update.u, update.v})
                if (node_colors.find(v) == node_colors.end()) node_colors[v] = dist(gen_);
        };
#ifdef COMMON_COLOR_EXPORT
        for (auto v : graph.vertices())
            std::cout << "COMMON_INITIAL_COLOR\t" << trial << '\t' << v << '\t' << node_colors.at(v) << '\n';
        std::ifstream color_input(dynamic_graph_file);
        std::string color_line;
        while (std::getline(color_input, color_line)) common_arrival_colors(common_decode(color_line));
        for (auto [v, c] : node_colors)
            std::cout << "COMMON_FINAL_COLOR\t" << trial << '\t' << v << '\t' << c << '\n';
        std::cout << "COMMON_INITIAL_VERTEX_COUNT\t" << trial << '\t' << graph.vertices().size() << '\n';
        continue; // Color export is never a timing run.
#endif
'''

OBSERVER = r'''
#ifdef COMMON_AUDIT
        auto common_emit = [&](const char* phase, uint32_t row) {
            std::cout << "COMMON_ANSWER\t" << trial << '\t' << phase << '\t' << row
                      << '\t' << std::setprecision(17) << trial_best_weight << '\t';
            for (auto v : trial_best_cycle) std::cout << v << ',';
            std::cout << '\t' << batch_weight_threshold_ << '\n';
        };
        common_emit("initial", 0);
#endif
'''

ROW_INTERFACE = r'''
            const auto common_update = common_decode(line);
            common_arrival_colors(common_update);
#ifdef COMMON_AUDIT
            // Destructor observes every exit (including EG continue), without
            // calling Output_most_negative_cycle or modifying core state.
            struct CommonScope { std::function<void()> emit; ~CommonScope(){emit();} };
            CommonScope common_scope{[&]{common_emit("arrival", num_updates);}};
#endif
            if (enable_auto_batch_ && common_update.noop) continue;
'''

END_OBSERVER = r'''
#ifdef COMMON_AUDIT
        common_emit("eof", num_updates);
        for (auto [v, c] : node_colors)
            std::cout << "COMMON_FINAL_COLOR\t" << trial << '\t' << v << '\t' << c << '\n';
        for (auto u : graph.vertices()) {
            auto [vs, ws, degree] = graph.get_out_neighbors(u);
            for (uint32_t i = 0; i < degree; ++i)
                std::cout << "COMMON_FINAL_EDGE\t" << trial << '\t' << u << '\t' << vs[i]
                          << '\t' << std::setprecision(17) << ws[i] << '\n';
        }
#endif
'''


def replace_once(text, anchor, replacement):
    if text.count(anchor) != 1:
        raise ValueError(f'Expected one source anchor: {anchor!r}')
    return text.replace(anchor, replacement)


def transform(original, variant):
    cpp = replace_once(original, 'using CycleInfo =', PREAMBLE + '\nusing CycleInfo =')
    cpp = replace_once(cpp, '        assign_colors();', '        assign_colors();\n' + COLOR_INTERFACE)
    cpp = replace_once(cpp, '        auto start_dynamic_time =', OBSERVER + '\n        auto start_dynamic_time =')
    cpp = replace_once(cpp, '            num_updates++;', '            num_updates++;\n' + ROW_INTERFACE)
    cpp = replace_once(cpp, '        dynamic_file.close();', END_OBSERVER + '\n        dynamic_file.close();')
    edge_anchor = ') {\n    std::istringstream iss(line);\n    uint32_t src_node, dst_node;'
    cpp = replace_once(cpp, edge_anchor, ') {\n    if (common_decode(line).noop) return;\n    std::istringstream iss(line);\n    uint32_t src_node, dst_node;')
    cpp = replace_once(cpp, '    for(auto line: batch_lines) {',
                       '    for(auto line: batch_lines) {\n        if (common_decode(line).noop) continue;')
    cpp = replace_once(cpp, '                        for (const auto& batch_line : batch_lines) {',
                       '                        for (const auto& batch_line : batch_lines) {\n                            if (common_decode(batch_line).noop) continue;')
    if variant in ('oldnew', 'minpatch'):
        cpp = replace_once(cpp, '                if(!graph.get_edge_weight(src_node, dst_node, weight)) {',
                           '                double lookup_old_weight = 0.0;\n                if(!graph.get_edge_weight(src_node, dst_node, lookup_old_weight)) {')
    if variant == 'minpatch':
        # Scope mask edits to backward DFS, not the forward search.
        begin = cpp.index('void KCycleColorCoding::backword_dfs(')
        end = cpp.index('void KCycleColorCoding::get_all_back_dfs_nodes(', begin)
        backward = cpp[begin:end]
        backward = replace_once(backward, '        if(pre < dst_node) {',
                                '        if(pre < dst_node) {\n            color_set |= pre_color;')
        backward = replace_once(backward, '                color_set &= ~pre_color;\n            }',
                                '            }\n            color_set &= ~pre_color;')
        cpp = cpp[:begin] + backward + cpp[end:]
        begin = cpp.index('                if(dst_node == 0){')
        end = cpp.index('\n            }\n        } else {', begin)
        cpp = cpp[:begin] + '                update_edge_weight(src_node, dst_node, weight, trial_best_weight, trial_best_cycle);' + cpp[end:]
    return cpp


def prepare(source, output, variant):
    blobs = {name: (source / name).read_bytes() for name in HASHES}
    for name, expected in HASHES.items():
        if hashlib.sha256(blobs[name]).hexdigest() != expected:
            raise ValueError(f'Upstream source hash mismatch: {name}')
    original = blobs['cycle_detector.cpp'].decode('utf-8')
    patched = transform(original, variant)
    output.mkdir(parents=True, exist_ok=False)
    for name, blob in blobs.items():
        (output / name).write_bytes(patched.encode('utf-8') if name == 'cycle_detector.cpp' else blob)
    (output / 'source.diff').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), patched.splitlines(True),
        fromfile='official/cycle_detector.cpp', tofile=f'{variant}/cycle_detector.cpp')), encoding='utf-8')
    (output / 'manifest.json').write_text(json.dumps({
        'commit': COMMIT, 'variant': variant, 'upstream_sha256': HASHES,
        'generated_sha256': {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in HASHES},
        'common_interface': ['strict finite/N input', 'future colors assigned in arrival order',
                             'compile-time read-only answer/color/final-graph observer'],
        'core_patch': ([] if variant == 'official' else ['preserve incoming EG weight across old-weight lookup']) +
                      (['include predecessor color in backward DFS and restore for every sibling',
                        'use normal graph/DP update for destination zero'] if variant == 'minpatch' else []),
        'gap_repaired': False, 'production_accepted': False,
        'execution_model': 'native sequential trials; not a simultaneous best-of-colors service',
    }, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variant', choices=['official', 'oldnew', 'minpatch'], required=True)
    args = parser.parse_args()
    prepare(args.source, args.output, args.variant)


if __name__ == '__main__':
    main()
