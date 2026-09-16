#include "delta_window.hpp"
#include <fstream>
#include <iomanip>
#include <iostream>

using namespace delta;
using namespace deadline_experiment;
struct Recorded {Clock::time_point start,returned;WindowResponse response;};
std::int64_t ns(Clock::time_point a,Clock::time_point b) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count();
}
void require(bool ok,const char* what) {if(!ok)throw std::runtime_error(what);}
int main(int argc,char** argv) {
    try {
        require(argc==6,"usage: graph updates colors row-count trace.csv");
        const size_t count=std::stoull(argv[4]);require(count>0,"empty run");
        std::ifstream gf(argv[1]),uf(argv[2]),cf(argv[3]);require(bool(gf&&uf&&cf),"input open failed");
        std::vector<Update> initial;int u,v;double w;
        while(gf>>u>>v>>w)initial.push_back({u,v,w,'S'});
        require(gf.eof()&&!initial.empty(),"invalid graph");
        std::vector<std::vector<int>> colors;std::string line;
        while(std::getline(cf,line)) {
            std::istringstream row(line);std::vector<int> one;int c;
            while(row>>c)one.push_back(c);
            require(row.eof()&&!one.empty(),"invalid colors");colors.push_back(std::move(one));
        }
        require(colors.size()==80,"expected 80 frozen colorings");
        const WindowPolicy policy{}; // Frozen before any run: 10 ms total / 1 ms reserve.
        std::vector<Recorded> records;records.reserve(count);
        {
            DeltaServiceContinuation service(colors,5,initial);
            std::uint64_t last_steps=0;
            for(size_t i=0;i<count;++i) {
                require(service.work_steps()==last_steps,"maintenance outside request");
                const auto start=Clock::now();
                auto response=serve_window(service,uf,start,policy);
                const auto returned=Clock::now(); // Actual in-process caller receipt.
                last_steps=response.steps_after;
                records.push_back({start,returned,std::move(response)});
            }
            require(service.work_steps()==last_steps,"maintenance after last return");
            // Do NOT flush/drain pending work at EOF or between arrivals.
        }
        // Persist every response before offline correctness checks. This phase
        // does no timed service work and is not part of the response latency.
        std::ofstream trace(argv[5]);require(bool(trace),"trace open failed");
        trace<<"row,u,v,op,input_weight,parse_ns,accept_ns,maintenance_ns,validation_ns,return_tail_ns,actual_return_ns,overshoot_ns,accepted,committed,backlog,steps_before,steps_after,missing,weight,coloring,source_version,graph_version,path\n";
        trace<<std::setprecision(17);
        size_t late=0,missing=0,max_backlog=0;std::int64_t max_ns=0;
        for(size_t i=0;i<count;++i) {
            const auto& r=records[i];const auto& a=r.response;const auto& e=a.update;
            const auto elapsed=ns(r.start,r.returned),over=std::max<std::int64_t>(0,elapsed-policy.budget.count());
            late+=over>0;missing+=!a.candidate;max_ns=std::max(max_ns,elapsed);max_backlog=std::max(max_backlog,a.backlog);
            trace<<i+1<<','<<e.u<<','<<e.v<<','<<e.op<<','<<e.w<<','<<ns(r.start,a.parsed)<<','<<ns(a.parsed,a.accepted)<<','
                 <<ns(a.accepted,a.maintained)<<','<<ns(a.maintained,a.validated)<<','<<ns(a.validated,r.returned)<<','
                 <<elapsed<<','<<over<<','<<a.accepted_version<<','<<a.committed_version<<','<<a.backlog<<','
                 <<a.steps_before<<','<<a.steps_after<<','<<!a.candidate;
            if(a.candidate) {
                const auto& c=*a.candidate;
                trace<<','<<c.weight<<','<<c.coloring<<','<<c.source_version<<','<<c.graph_version<<',';
                for(size_t j=0;j<c.path.size();++j){if(j)trace<<';';trace<<c.path[j];}
            } else trace<<",,,,,";
            trace<<'\n';
        }
        trace.close();require(bool(trace),"trace write failed");
        // Offline unlimited reference, after the timed service has been destroyed.
        // Same observed-root ordering; compare complete rows, validate all paths.
        std::map<std::pair<int,int>,double> live;
        std::vector<bool> observed(colors.front().size(),false);
        for(auto e:initial){live[{e.u,e.v}]=e.w;observed[e.u]=observed[e.v]=true;}
        std::vector<std::unique_ptr<DeltaEngine>> original;
        for(const auto& row:colors) {
            auto engine=std::make_unique<DeltaEngine>(row,5);
            for(auto e:initial)engine->set_edge(e);
            for(size_t x=0;x<observed.size();++x)if(observed[x])engine->ensure(int(x),int(x),1<<row[x]);
            engine->propagate();original.push_back(std::move(engine));
        }
        size_t validated=0,complete_compared=0;
        for(size_t i=0;i<count;++i) {
            const auto& r=records[i];const auto& a=r.response;const auto e=a.update;
            require(r.start<=a.parsed&&a.parsed<=a.accepted&&a.accepted<=a.maintained&&
                    a.maintained<=a.validated&&a.validated<=r.returned,"nonmonotone timestamps");
            require(a.accepted_version==i+1&&a.committed_version<=a.accepted_version&&
                    a.backlog==a.accepted_version-a.committed_version,"bad versions");
            if(i)require(a.steps_before==records[i-1].response.steps_after,"uncharged steps");
            if(e.op=='S') {
                live[{e.u,e.v}]=e.w;
                for(int x:{e.u,e.v})if(!observed[x]) {
                    observed[x]=true;
                    for(size_t t=0;t<80;++t)original[t]->ensure(x,x,1<<colors[t][x]);
                }
            } else if(e.op=='D')live.erase({e.u,e.v});
            double expected=INF;
            for(auto& engine:original){engine->apply(std::vector<Update>{e},0,1);expected=std::min(expected,engine->query().first);}
            if(a.candidate) {
                const auto& c=*a.candidate;require(c.path.size()==6&&c.path.front()==c.path.back(),"invalid closure/length");
                require(c.graph_version==i+1&&c.source_version<=c.graph_version&&c.coloring<80,"bad candidate version");
                double actual=0;int mask=0;
                for(int j=0;j<5;++j) {
                    for(int m=0;m<j;++m)require(c.path[m]!=c.path[j],"repeated vertex");
                    actual+=live.at({c.path[j],c.path[j+1]});mask|=1<<colors[c.coloring][c.path[j]];
                }
                require(actual<0&&std::isfinite(actual)&&actual==c.weight&&mask==31,"invalid candidate weight/colors");++validated;
            }
            if(a.backlog==0) {
                if(expected<0)require(a.candidate&&std::abs(a.candidate->weight-expected)<1e-10,"complete answer differs from core");
                else require(!a.candidate,"unexpected negative candidate");
                ++complete_compared;
            }
        }
        std::cout<<"PASS gate rows="<<count<<" validated_candidates="<<validated<<" complete_reference_comparisons="<<complete_compared
                 <<" late="<<late<<" missing="<<missing<<" max_return_ns="<<max_ns<<" max_backlog="<<max_backlog
                 <<" eof_backlog="<<records.back().response.backlog<<" budget_ns="<<policy.budget.count()
                 <<" reserve_ns="<<policy.reserve.count()<<". Serial in-process protocol pilot, NOT a three-method Effectiveness table.\n";
    } catch(const std::exception& e) {std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}
}
