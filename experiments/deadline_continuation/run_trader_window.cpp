#include "trader_window.hpp"
#include <cassert>
#include <iomanip>
#include <iostream>

using namespace deadline_experiment;
int main(int argc,char** argv) {
    FiberThreadScope thread;using Clock=TraderServiceContinuation::Clock;
    if(argc==1) {
        DirectedGraph graph;for(unsigned u=0;u<10;++u)for(unsigned v=0;v<10;++v)
            if(u!=v)graph.update_edge(u,v,-0.2);
        TraderServiceContinuation service(graph,3,{100,200});
        std::istringstream input("0 1 -0.3\n0 1 0.4\n0 1 invalid\n");
        auto start=Clock::now();auto response=serve_trader_window(service,input,start,
            TraderWindowPolicy{std::chrono::nanoseconds(0),std::chrono::nanoseconds(0)});
        auto end=Clock::now();
        assert(response.accepted_version==1 && response.completed_version==0 && response.backlog==1);
        assert(response.steps_before==response.steps_after && response.candidate);
        assert(start<=response.read&&response.read<=response.accepted&&response.accepted<=response.maintained);
        assert(response.maintained<=response.validated&&response.validated<=end);
        response=serve_trader_window(service,input,Clock::now()-std::chrono::seconds(1));
        assert(response.accepted_version==2&&response.completed_version==0&&response.backlog==2);
        assert(response.steps_before==response.steps_after);
        bool rejected=false;try{serve_trader_window(service,input,Clock::now());}
        catch(const std::exception&){rejected=true;}assert(rejected&&service.accepted()==2);
        std::cout<<"PASS window zero/expired budgets, parse rejection, ordering, no free maintenance\n";return 0;
    }
    if(argc!=5)throw std::runtime_error("graph updates seeds output-csv; fixed 32-row pilot");
    DirectedGraph graph;graph.load_edge_list(argv[1]);
    std::ifstream seeds_file(argv[3]);std::string line;std::getline(seeds_file,line);assert(std::getline(seeds_file,line));
    std::istringstream row(line);std::vector<unsigned> seeds;unsigned seed;
    while(row>>seed)seeds.push_back(seed);assert(seeds.size()>=80);seeds.resize(80);
    struct Record {TraderWindowResponse response;Clock::time_point start,end;};
    std::vector<Record> records;records.reserve(32);
    uint64_t eof_debt=0;
    {
        TraderServiceContinuation service(graph,5,seeds);
        std::ifstream updates(argv[2]);assert(updates);uint64_t previous_steps=0;
        for(unsigned i=0;i<32;++i) {
            assert(service.work_steps()==previous_steps);
            const auto start=Clock::now();auto response=serve_trader_window(service,updates,start);
            const auto end=Clock::now();previous_steps=response.steps_after;
            records.push_back({std::move(response),start,end});
        }
        eof_debt=service.backlog();
        // Destruction only unwinds/discards an unfinished private job. It does
        // not complete pending arrivals or publish an EOF result.
    }
    // Independent current-graph replay after all timed windows; not used to
    // search for or repair any response during measurement.
    std::map<std::pair<uint32_t,uint32_t>,double> live;
    for(auto u:graph.vertices()) {
        auto [neighbors,weights,degree]=graph.get_out_neighbors(u);
        for(uint32_t i=0;i<degree;++i)live[{u,neighbors[i]}]=weights[i];
    }
    auto ns=[](auto a,auto b){return std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count();};
    std::ofstream out(argv[4]);assert(out);
    out<<"row,accepted_version,completed_version,backlog,steps_before,steps_after,read_ns,accept_ns,maintenance_ns,validation_ns,return_ns,actual_return_ns,late,source_version,weight,path\n";
    size_t late=0,missing=0,older=0,max_debt=0;int64_t maximum=0;
    for(size_t i=0;i<records.size();++i) {
        const auto& r=records[i];const auto& x=r.response;
        uint32_t u,v;std::string token;std::istringstream update(x.line);update>>u>>v>>token;
        if(token!="N")live[{u,v}]=std::stod(token);
        const auto elapsed=ns(r.start,r.end);maximum=std::max(maximum,elapsed);late+=elapsed>10000000;
        max_debt=std::max(max_debt,x.backlog);
        assert(x.accepted_version==i+1&&x.backlog==x.accepted_version-x.completed_version);
        if(i)assert(x.steps_before==records[i-1].response.steps_after);
        assert(r.start<=x.read&&x.read<=x.accepted&&x.accepted<=x.maintained&&x.maintained<=x.validated&&x.validated<=r.end);
        out<<i+1<<','<<x.accepted_version<<','<<x.completed_version<<','<<x.backlog<<','<<x.steps_before<<','<<x.steps_after<<','
           <<ns(r.start,x.read)<<','<<ns(x.read,x.accepted)<<','<<ns(x.accepted,x.maintained)<<','<<ns(x.maintained,x.validated)<<','
           <<ns(x.validated,r.end)<<','<<elapsed<<','<<(elapsed>10000000)<<',';
        if(!x.candidate){++missing;out<<",,\n";continue;}
        const auto& c=*x.candidate;assert(c.path.size()==6&&c.path.front()==c.path.back());
        double w=0;for(size_t j=0;j<5;++j){
            for(size_t m=0;m<j;++m)assert(c.path[j]!=c.path[m]);w+=live.at({c.path[j],c.path[j+1]});
        }
        assert(std::isfinite(w)&&w<0&&w==c.weight&&c.graph_version==i+1&&c.source_version<=i+1);
        older+=c.source_version<c.graph_version;
        out<<c.source_version<<','<<std::setprecision(17)<<c.weight<<",\"";
        for(auto vertex:c.path)out<<vertex<<' ';out<<"\"\n";
    }
    std::cout<<"PASS UNI1-prefix32 full-window pilot late="<<late<<" missing="<<missing
             <<" older_source="<<older<<" max_backlog="<<max_debt<<" eof_backlog="<<eof_debt
             <<" max_return_ns="<<maximum<<"; not full-stream Effectiveness\n";
}
