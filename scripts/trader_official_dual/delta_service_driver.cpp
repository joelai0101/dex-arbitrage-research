// Common-input persistent DELTA service; frozen DeltaEngine is supplied locally.
#include <memory>
#include "delta_state_benchmark.cpp"

static double peak_mib() {
    PROCESS_MEMORY_COUNTERS memory{};
    if(!GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory)))
        throw std::runtime_error("GetProcessMemoryInfo failed");
    return double(memory.PeakWorkingSetSize)/1048576;
}

int main(int argc,char** argv) {try {
    if(argc!=8)throw std::runtime_error("graph updates colors k ell batch trace");
    const int k=std::stoi(argv[4]);
    const size_t ell=std::stoul(argv[5]),batch=std::stoul(argv[6]);
    if(!ell||!batch)throw std::runtime_error("ell and batch must be positive");
    std::ifstream colors_file(argv[3]);
    std::string line;
    std::vector<std::vector<int>> colors;
    for(size_t t=0;t<ell;++t) {
        if(!std::getline(colors_file,line))throw std::runtime_error("missing color row");
        std::istringstream in(line);int c;std::vector<int> row;
        while(in>>c) {if(c<0||c>=k)throw std::runtime_error("invalid color");row.push_back(c);}
        if(row.empty()||(!colors.empty()&&row.size()!=colors[0].size()))throw std::runtime_error("color size mismatch");
        colors.push_back(std::move(row));
    }
    std::vector<bool> observed(colors[0].size(),false);
    auto decode=[&](const std::string& line) {
        std::istringstream input(line);int u,v;std::string token;
        if(!(input>>u>>v>>token))throw std::runtime_error("malformed input");
        if(token=="N")return Update{u,v,0,'N'};
        size_t used=0;double w=std::stod(token,&used);
        if(used!=token.size()||!std::isfinite(w)||w>1000||u<0||v<0||size_t(u)>=observed.size()||size_t(v)>=observed.size())
            throw std::runtime_error("input is not normalized");
        return Update{u,v,w,'S'};
    };
    std::ifstream update_file(argv[2]);if(!update_file)throw std::runtime_error("updates missing");
    std::vector<std::string> updates;
    while(std::getline(update_file,line))updates.push_back(line);
    std::ofstream trace(argv[7]);if(!trace)throw std::runtime_error("trace output failed");
    trace<<std::setprecision(17)<<"phase\trow\tweight\tpath\tcoloring\n";
    std::vector<std::unique_ptr<DeltaEngine>> engines;
    std::vector<double> weights(ell,INF);
    std::vector<std::vector<int>> paths(ell);
    const auto init_begin=Clock::now();
    std::vector<Update> initial;
    std::ifstream graph_file(argv[1]);if(!graph_file)throw std::runtime_error("graph missing");
    while(std::getline(graph_file,line)) {
        auto edge=decode(line);if(edge.op!='S')throw std::runtime_error("N in static graph");
        initial.push_back(edge);observed[edge.u]=observed[edge.v]=true;
    }
    size_t initial_vertices=std::count(observed.begin(),observed.end(),true);
    for(size_t t=0;t<ell;++t) {
        auto engine=std::make_unique<DeltaEngine>(colors[t],k);
        // Same initialize operations, but only observed roots are materialized.
        // The full color/index address space does not create future graph edges.
        for(auto edge:initial)engine->set_edge(edge);
        for(size_t v=0;v<observed.size();++v)if(observed[v])engine->ensure(int(v),int(v),1<<colors[t][v]);
        engine->propagate();engine->recomputed=engine->value_changed=engine->probes=engine->gate_skips=0;
        auto answer=engine->query();weights[t]=answer.first;paths[t]=std::move(answer.second);
        engines.push_back(std::move(engine));
    }
    const auto init_end=Clock::now();
    const double init_peak=peak_mib();
    std::cerr<<"INITIALIZED ell="<<ell<<" vertices="<<initial_vertices<<" peak_mib="<<init_peak<<'\n';
    auto select_best=[&] {size_t best=0;for(size_t t=1;t<ell;++t)if(weights[t]<weights[best])best=t;return best;};
    size_t best=select_best(),publications=0;
    double returned_weight=weights[best];std::vector<int> returned=paths[best];
    auto emit=[&](const char* phase,size_t row) {
        trace<<phase<<'\t'<<row<<'\t'<<returned_weight<<'\t';
        for(size_t i=0;i<returned.size();++i)trace<<(i?" ":"")<<returned[i];
        trace<<'\t'<<best<<'\n';
    };
    emit("initial",0);
    std::vector<Update> pending;pending.reserve(batch);
    auto flush=[&] {
        for(size_t t=0;t<ell;++t) {
            engines[t]->apply(pending,0,pending.size());
            auto answer=engines[t]->query();weights[t]=answer.first;paths[t]=std::move(answer.second);
        }
        best=select_best();returned_weight=weights[best];returned=paths[best];pending.clear();
    };
    double detection_ms=0;
    for(size_t row=0;row<updates.size();++row) {
        const auto begin=Clock::now();auto update=decode(updates[row]);
        if(update.op=='S')for(int v:{update.u,update.v})if(!observed[v]) {
            observed[v]=true;
            for(size_t t=0;t<ell;++t)engines[t]->ensure(v,v,1<<colors[t][v]);
        }
        pending.push_back(update);
        if(pending.size()==batch) {flush();++publications;}
        detection_ms+=ms(begin,Clock::now());
        emit("arrival",row+1);
    }
    const auto flush_begin=Clock::now();
    if(!pending.empty())flush();
    else {best=select_best();returned_weight=weights[best];returned=paths[best];}
    detection_ms+=ms(flush_begin,Clock::now());
    emit("eof",updates.size());
    std::cout<<std::setprecision(17)<<"{\"method\":\"DELTA\",\"execution_model\":\"persistent_best_of_ell\",\"ell\":"<<ell
             <<",\"batch\":"<<batch<<",\"eg\":false,\"updates\":"<<updates.size()
             <<",\"publications_before_eof\":"<<publications<<",\"initial_vertices\":"<<initial_vertices
             <<",\"final_observed_vertices\":"<<std::count(observed.begin(),observed.end(),true)
             <<",\"init_ms\":"<<ms(init_begin,init_end)<<",\"detection_ms\":"<<detection_ms
             <<",\"init_peak_rss_mib\":"<<init_peak<<",\"peak_rss_mib\":"<<peak_mib()<<"}\n";
    return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
