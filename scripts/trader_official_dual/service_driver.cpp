// Persistent best-of-ell wrapper; the DP/update implementation is upstream code.
#include <functional>
#include <sstream>
#include <limits>
#include <chrono>
#include <memory>
#include <iomanip>
#include <cmath>
#include <windows.h>
#include <psapi.h>
#include "cycle_detector.h"

using Clock = std::chrono::steady_clock;
static double ms(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::milli>(b-a).count();
}
static double peak_mib() {
    PROCESS_MEMORY_COUNTERS memory{};
    if (!GetProcessMemoryInfo(GetCurrentProcess(), &memory, sizeof(memory)))
        throw std::runtime_error("GetProcessMemoryInfo failed");
    return double(memory.PeakWorkingSetSize)/1048576;
}

int main(int argc, char** argv) { try {
    if (argc != 9) throw std::runtime_error("graph updates seeds k ell batch auto trace-or-dash");
    const unsigned k=std::stoul(argv[4]), ell=std::stoul(argv[5]), batch=std::stoul(argv[6]);
    const bool eg=std::stoi(argv[7])!=0;
    if (!ell || !batch) throw std::runtime_error("ell and batch must be positive");
    std::ifstream seed_file(argv[3]);
    std::string line;
    std::getline(seed_file,line); // The pinned format's experiment seed row.
    if (!std::getline(seed_file,line)) throw std::runtime_error("trial seed row missing");
    std::istringstream seed_row(line);
    std::vector<unsigned> seeds; unsigned seed;
    while(seed_row>>seed) seeds.push_back(seed);
    if(seeds.size()<ell) throw std::runtime_error("too few seeds");
    std::ifstream update_file(argv[2]);
    if(!update_file) throw std::runtime_error("update file missing");
    std::vector<std::string> updates;
    while(std::getline(update_file,line)) updates.push_back(line);
    std::ofstream trace;
    if(std::string(argv[8])!="-") {
        trace.open(argv[8]);
        if(!trace) throw std::runtime_error("trace output failed");
        trace<<std::setprecision(17)<<"phase\trow\tweight\tpath\tcoloring\n";
    }
    std::vector<std::unique_ptr<KCycleColorCoding>> engines;
    const auto init_begin=Clock::now();
    {
        DirectedGraph graph;
        std::ifstream graph_check(argv[1]);
        if(!graph_check) throw std::runtime_error("graph file missing");
        graph.load_edge_list(argv[1]);
        for(unsigned trial=0;trial<ell;++trial) {
            auto engine=std::make_unique<KCycleColorCoding>(graph,k,1,10,seeds[trial],batch,eg);
            engine->common_start(seeds[trial]);
            engines.push_back(std::move(engine));
            std::cerr<<"INITIALIZED "<<trial+1<<'/'<<ell<<" peak_mib="<<peak_mib()<<'\n';
        }
    }
    const auto init_end=Clock::now();
    const double init_peak=peak_mib();
    auto select_best=[&] {
        size_t best=0;
        for(size_t trial=1;trial<engines.size();++trial)
            if(engines[trial]->common_weight()<engines[best]->common_weight()) best=trial;
        return best;
    };
    std::vector<uint32_t> returned;
    double returned_weight=INFINITY;
    auto emit=[&](const char* phase, size_t row, size_t best) {
        if(!trace.is_open()) return;
        trace<<phase<<'\t'<<row<<'\t'<<returned_weight<<'\t';
        bool first=true;
        for(auto v:returned) {trace<<(first?"":" ")<<v; first=false;}
        trace<<'\t'<<best<<'\n';
    };
    size_t best=select_best(), publications=0;
    returned=engines[best]->common_path();
    returned_weight=engines[best]->common_weight();
    emit("initial",0,best);
    double detection_ms=0;
    for(size_t row=0;row<updates.size();++row) {
        const auto begin=Clock::now();
        for(auto& engine:engines) engine->common_apply(updates[row]);
        if(eg || (row+1)%batch==0) {best=select_best(); ++publications;}
        // Materialize the selected path inside the charged answer contract.
        // Copies are elided on arrivals that do not publish a new batch answer.
        if(eg || (row+1)%batch==0) {
            returned=engines[best]->common_path();
            returned_weight=engines[best]->common_weight();
        }
        detection_ms+=ms(begin,Clock::now());
        emit("arrival",row+1,best); // File output is outside detection time.
#ifdef SERVICE_AUDIT
        for(size_t t=0;t<engines.size();++t) {
            std::cout<<"SERVICE_ANSWER\t"<<t<<'\t'<<row+1<<'\t'<<std::setprecision(17)<<engines[t]->common_weight()<<'\t';
            for(auto v:engines[t]->common_path()) std::cout<<v<<',';
            std::cout<<'\n';
        }
#endif
    }
    const auto flush_begin=Clock::now();
    for(auto& engine:engines) engine->common_finish();
    best=select_best();
    returned=engines[best]->common_path();
    returned_weight=engines[best]->common_weight();
    detection_ms+=ms(flush_begin,Clock::now());
    emit("eof",updates.size(),best);
    const double peak=peak_mib();
#ifdef SERVICE_AUDIT
    for(size_t t=0;t<engines.size();++t) {
        for(auto [v,c]:engines[t]->common_colors()) std::cout<<"SERVICE_COLOR\t"<<t<<'\t'<<v<<'\t'<<c<<'\n';
        const auto& g=engines[t]->common_graph();
        for(auto u:g.vertices_) {
            auto [vs,ws,n]=g.get_out_neighbors(u);
            for(uint32_t i=0;i<n;++i)
                std::cout<<"SERVICE_EDGE\t"<<t<<'\t'<<u<<'\t'<<vs[i]<<'\t'<<std::setprecision(17)<<ws[i]<<'\n';
        }
    }
#endif
    std::cout<<std::setprecision(17)<<"{\"execution_model\":\"persistent_best_of_ell\",\"ell\":"<<ell
             <<",\"batch\":"<<batch<<",\"eg\":"<<(eg?"true":"false")
             <<",\"updates\":"<<updates.size()<<",\"publications_before_eof\":"<<publications
             <<",\"init_ms\":"<<ms(init_begin,init_end)<<",\"detection_ms\":"<<detection_ms
             <<",\"init_peak_rss_mib\":"<<init_peak<<",\"peak_rss_mib\":"<<peak<<"}\n";
    return 0;
} catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}}
