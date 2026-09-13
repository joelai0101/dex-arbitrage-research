"""Expose the existing native trial as a persistent per-color service.

Initialization/update/EOF statements are extracted from the hash-checked source,
not reimplemented DP. The original native entry point remains present.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

from prepare_source import prepare, replace_once

DECLARATIONS = r'''
public:
    void common_start(unsigned int seed);
    void common_apply(const std::string& line);
    void common_finish();
    double common_weight() const { return trial_best_weight; }
    const std::vector<uint32_t>& common_path() const { return trial_best_cycle; }
    const std::unordered_map<uint32_t, int>& common_colors() const { return node_colors; }
    const DirectedGraph& common_graph() const { return graph; }
private:
    double trial_best_weight;
    std::vector<uint32_t> trial_best_cycle;
    uint32_t num_updates = 0;
    uint batch_count = 0;
    std::vector<std::string> batch_lines;
    double cumulative_weight = 0;
    std::string output_string;
'''


def prepare_service(source, output, variant):
    prepare(source, output, variant)
    cpp_path, header_path = output/'cycle_detector.cpp', output/'cycle_detector.h'
    cpp, header = cpp_path.read_text(), header_path.read_text()
    original_cpp, original_header = cpp, header
    start_anchor = '        for(auto start_node: graph.vertices()) {'
    init = cpp.split(start_anchor, 1)[1].split('        auto end_time =', 1)[0]
    init = start_anchor + init
    loop_start = '        while (std::getline(dynamic_file, line)) {\n'
    loop_end = '        if(batch_lines.size() > 0) {'
    body = cpp.split(loop_start, 1)[1].split(loop_end, 1)[0]
    if not body.endswith('        }\n'):
        raise ValueError('Unexpected native loop ending')
    body = body[:-len('        }\n')]
    # Native-only observer captures local trial variables. The persistent driver
    # observes getters after each call instead; neither observer modifies answers.
    while '#ifdef COMMON_AUDIT' in body:
        before, rest = body.split('#ifdef COMMON_AUDIT', 1)
        _, after = rest.split('#endif', 1)
        body = before + after
    finish = loop_end + cpp.split(loop_end, 1)[1].split('        dynamic_file.close();', 1)[0]
    finish = finish.split('#ifdef COMMON_AUDIT', 1)[0]
    methods = r'''
void KCycleColorCoding::common_start(unsigned int seed) {
    gen_.seed(seed);
    assign_colors();
    full_dp_table.clear();
    trial_best_weight = std::numeric_limits<double>::infinity();
    trial_best_cycle.clear();
    num_updates = 0;
    batch_count = 0;
    batch_lines.clear();
    cumulative_weight = 0;
    output_string.clear();
''' + init + r'''
}
void KCycleColorCoding::common_apply(const std::string& line) {
    auto common_arrival_colors = [&](const CommonUpdate& update) {
        if (update.noop) return;
        for (auto v : {update.u, update.v})
            if (node_colors.find(v) == node_colors.end()) node_colors[v] = dist(gen_);
    };
    // Preserve native top-level continue semantics without a streaming file loop.
    do {
''' + body + r'''
    } while (false);
}
void KCycleColorCoding::common_finish() {
''' + finish + '\n}\n'
    cpp += methods
    header = replace_once(header, '\nprivate:\n', '\n' + DECLARATIONS + '\nprivate:\n')
    cpp_path.write_text(cpp, encoding='utf-8')
    header_path.write_text(header, encoding='utf-8')
    patch = ''.join(difflib.unified_diff(original_cpp.splitlines(True), cpp.splitlines(True),
                                       fromfile='common/cycle_detector.cpp', tofile='service/cycle_detector.cpp'))
    patch += ''.join(difflib.unified_diff(original_header.splitlines(True), header.splitlines(True),
                                        fromfile='common/cycle_detector.h', tofile='service/cycle_detector.h'))
    (output/'service.diff').write_text(patch, encoding='utf-8')
    manifest = json.loads((output/'manifest.json').read_text())
    manifest['execution_model'] = 'persistent one-color service; driver can retain ell instances'
    manifest['service_change'] = 'Extract native init, update-loop body and EOF maintenance into callable methods'
    manifest['generated_sha256'] = {name: hashlib.sha256((output/name).read_bytes()).hexdigest()
                                    for name in manifest['generated_sha256']}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variant', choices=['official', 'oldnew', 'minpatch'], required=True)
    args = parser.parse_args()
    prepare_service(args.source, args.output, args.variant)
