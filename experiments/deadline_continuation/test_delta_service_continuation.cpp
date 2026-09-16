#include "delta_service_continuation.hpp"
#include <cassert>
#include <iostream>
#include <random>

using namespace delta;
using deadline_experiment::DeltaServiceContinuation;
void compare(const DeltaEngine& a,const DeltaEngine& b) {
    assert(a.states.size()==b.states.size()&&a.arcs.size()==b.arcs.size());
    assert(a.out==b.out&&a.endpoint==b.endpoint&&a.dirty==b.dirty&&a.candidates==b.candidates);
    assert(a.recomputed==b.recomputed&&a.probes==b.probes&&a.gate_skips==b.gate_skips);
    assert(a.value_changed==b.value_changed&&a.changes==b.changes&&a.topology==b.topology);
    for(size_t i=0;i<a.lookup.size();++i)assert(a.lookup[i].rows==b.lookup[i].rows);
    for(size_t i=0;i<a.states.size();++i) {
        const auto& x=a.states[i];const auto& y=b.states[i];
        assert(x.root==y.root&&x.u==y.u&&x.mask==y.mask&&x.level==y.level);
        assert(x.w==y.w&&x.parent==y.parent&&x.terminal==y.terminal&&x.queued==y.queued);
        assert(x.incoming==y.incoming&&x.outgoing==y.outgoing);
    }
    assert(a.edges.size()==b.edges.size());
    for(size_t i=0;i<a.edges.size();++i) {
        assert(a.edges[i].u==b.edges[i].u&&a.edges[i].v==b.edges[i].v&&a.edges[i].w==b.edges[i].w&&a.edges[i].arcs==b.edges[i].arcs);
    }
    for(size_t i=0;i<a.arcs.size();++i)
        assert(a.arcs[i].from==b.arcs[i].from&&a.arcs[i].to==b.arcs[i].to&&a.arcs[i].edge==b.arcs[i].edge);
}
int main() {
    size_t checked=0,backlogged=0;
    for(int k:{3,5}) {
        const int n=k+2;
        std::vector<std::vector<int>> colors(80,std::vector<int>(n));
        std::mt19937 rng(900+k);
        for(auto& row:colors)for(auto& c:row)c=int(rng()%k);
        // Include one known colorful initial negative cycle.
        for(int i=0;i<n;++i)colors[0][i]=i%k;
        std::vector<Update> initial;
        for(int i=0;i<k;++i)initial.push_back({i,(i+1)%k,-1,'S'});
        std::vector<bool> observed(n,false);
        std::map<std::pair<int,int>,double> live;
        for(auto e:initial){observed[e.u]=observed[e.v]=true;live[{e.u,e.v}]=e.w;}
        std::vector<std::unique_ptr<DeltaEngine>> original;
        for(auto row:colors) {
            auto e=std::make_unique<DeltaEngine>(row,k);
            for(auto edge:initial)e->set_edge(edge);
            for(int v=0;v<n;++v)if(observed[v])e->ensure(v,v,1<<row[v]);
            e->propagate();e->recomputed=e->value_changed=e->probes=e->gate_skips=0;
            original.push_back(std::move(e));
        }
        DeltaServiceContinuation service(colors,k,initial);
        assert(service.current_candidate());
        // Delete an edge of the cached winner with zero maintenance budget:
        // the old candidate must immediately become invalid in the live graph.
        std::vector<Update> updates{{0,1,0,'D'}};
        for(int i=1;i<160;++i) {
            Update e{int(rng()%n),int(rng()%n),double(int(rng()%21)-10)/4,'S'};
            if(i%5==0)e.op='D';else if(i%13==0)e.op='N';updates.push_back(e);
        }
        for(size_t i=0;i<updates.size();++i) {
            auto e=updates[i];service.accept(e);
            if(e.op=='S')live[{e.u,e.v}]=e.w;else if(e.op=='D')live.erase({e.u,e.v});
            if(e.op=='S')for(int v:{e.u,e.v})if(!observed[v]) {
                observed[v]=true;for(size_t t=0;t<80;++t)original[t]->ensure(v,v,1<<colors[t][v]);
            }
            for(auto& engine:original)engine->apply(std::vector<Update>{e},0,1);
            const auto before=service.work_steps();
            assert(service.advance_steps(0)==0&&service.advance_until(Clock::now())==0);
            assert(service.work_steps()==before);
            if(i==0)assert(!service.current_candidate());
            else service.advance_steps(1+(rng()%23));
            if(service.backlog()>1)++backlogged;
            auto answer=service.current_candidate();
            if(answer) {
                assert(answer->graph_version==service.accepted()&&answer->source_version<=answer->graph_version);
                double w=0;for(int j=0;j<k;++j)w+=live.at({answer->path[j],answer->path[j+1]});
                assert(w==answer->weight&&w<0);
            }
            assert(service.accepted()==i+1&&service.backlog()==service.accepted()-service.committed());
            if(i%20==19) {
                size_t steps=0;
                while(service.backlog()){steps+=service.advance_steps(17);assert(steps<10000000);}
                assert(service.accepted()==service.committed());
                double expected=INF;
                for(size_t t=0;t<80;++t){compare(*original[t],service.inspect(t));expected=std::min(expected,original[t]->query().first);++checked;}
                answer=service.current_candidate();
                if(expected<0){assert(answer&&std::abs(answer->weight-expected)<1e-12);}else assert(!answer);
            }
        }
        auto version=service.accepted();bool rejected=false;
        try{service.accept({n,0,1,'S'});}catch(const std::invalid_argument&){rejected=true;}
        assert(rejected&&service.accepted()==version&&!service.backlog());
    }
    assert(backlogged>0);
    std::cout<<"PASS 320 arrivals, 80 resident colorings, "<<checked<<" completed engine-state comparisons; "
             <<backlogged<<" backlog arrivals; observed-root activation, FIFO replay, zero-budget freeze and current-graph candidate validation. NOT formal 10ms.\n";
}
