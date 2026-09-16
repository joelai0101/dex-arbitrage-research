#include "delta_weight_continuation.hpp"
#include <cassert>
#include <iostream>
#include <random>
#include <fstream>
#include <sstream>

using namespace delta;
using deadline_experiment::DeltaWeightContinuation;
void equal_state(const DeltaEngine& a,const DeltaEngine& b) {
    assert(a.states.size()==b.states.size()&&a.arcs.size()==b.arcs.size());
    assert(a.edges.size()==b.edges.size()&&a.candidates==b.candidates);
    assert(a.dirty==b.dirty);
    assert(a.color==b.color&&a.out==b.out&&a.endpoint==b.endpoint);
    for(size_t i=0;i<a.lookup.size();++i)assert(a.lookup[i].rows==b.lookup[i].rows);
    for(size_t i=0;i<a.arcs.size();++i) {
        assert(a.arcs[i].from==b.arcs[i].from&&a.arcs[i].to==b.arcs[i].to&&a.arcs[i].edge==b.arcs[i].edge);
    }
    for(std::size_t i=0;i<a.states.size();++i) {
        const auto& x=a.states[i];const auto& y=b.states[i];
        assert(x.root==y.root&&x.u==y.u&&x.mask==y.mask&&x.level==y.level);
        assert(x.parent==y.parent&&x.terminal==y.terminal&&x.w==y.w&&x.queued==y.queued);
        assert(x.incoming==y.incoming&&x.outgoing==y.outgoing);
    }
    for(std::size_t i=0;i<a.edges.size();++i) {
        assert(a.edges[i].w==b.edges[i].w&&a.edges[i].u==b.edges[i].u&&a.edges[i].v==b.edges[i].v);
        assert(a.edges[i].arcs==b.edges[i].arcs);
    }
    assert(a.recomputed==b.recomputed&&a.value_changed==b.value_changed);
    assert(a.probes==b.probes&&a.gate_skips==b.gate_skips&&a.changes==b.changes);
    assert(a.topology==b.topology);
}
int uni_prefix(const char* graph_path,const char* updates_path,const char* colors_path) {
    std::ifstream gf(graph_path),uf(updates_path),cf(colors_path);
    assert(gf&&uf&&cf);
    std::vector<Update> initial,updates;int u,v;double w;std::string line,token;
    while(gf>>u>>v>>w)initial.push_back({u,v,w,'S'});
    while(updates.size()<32&&std::getline(uf,line)) {
        std::istringstream row(line);assert(bool(row>>u>>v>>token));
        updates.push_back({u,v,token=="N"?0:std::stod(token),token=="N"?'N':'S'});
    }
    assert(updates.size()==32);
    size_t trials=0,checked=0,steps=0;
    while(std::getline(cf,line)) {
        std::istringstream row(line);std::vector<int> colors;int c;
        while(row>>c){assert(c>=0&&c<5);colors.push_back(c);}
        assert(!colors.empty());
        DeltaEngine original(colors,5);original.initialize(initial);
        DeltaWeightContinuation resumed(colors,5,initial);
        equal_state(original,resumed.inspect());
        for(const auto& e:updates) {
            original.apply(std::vector<Update>{e},0,1);resumed.begin(e);
            while(resumed.busy())steps+=resumed.resume_steps(17);
            equal_state(original,resumed.inspect());
            assert(original.query()==resumed.completed_answer());++checked;
        }
        ++trials;
    }
    assert(trials==80);
    std::cout<<"PASS UNI1 prefix32 x "<<trials<<" colorings: "<<checked<<" update/coloring pairs, "<<steps
             <<" resumable steps; all states and answers equal to original DeltaEngine. Sequential per-color correctness gate, NOT service latency.\n";
    return 0;
}
int main(int argc,char** argv) {
    if(argc==4)return uni_prefix(argv[1],argv[2],argv[3]);
    assert(argc==1);
    std::size_t checked=0;
    for(int k:{3,5}) {
        std::vector<int> colors;
        for(int i=0;i<k+1;++i)colors.push_back(i%k);
        std::vector<Update> graph;
        for(int u=0;u<k+1;++u)for(int v=0;v<k+1;++v)
            if(u!=v)graph.push_back({u,v,(u+v)%3==0?-2.0:0.25,'S'});
        DeltaEngine original(colors,k);original.initialize(graph);
        DeltaWeightContinuation resumed(colors,k,graph);
        equal_state(original,resumed.inspect());
        // Deterministic budgets exercise yields before/after individual state work.
        std::mt19937 rng(821+k);
        for(int i=0;i<200;++i) {
            auto e=graph[rng()%graph.size()];
            e.w=double(int(rng()%41)-20)/4;
            if(i%17==0)e.op='N';
            original.apply(std::vector<Update>{e},0,1);
            resumed.begin(e);
            assert(resumed.resume_steps(0)==0);
            if(resumed.busy()) {
                bool blocked=false;try {resumed.begin(e);}catch(const std::logic_error&){blocked=true;}
                assert(blocked);
                blocked=false;try {resumed.completed_answer();}catch(const std::logic_error&){blocked=true;}
                assert(blocked);
                assert(resumed.resume_until(Clock::now())==0);
            }
            std::size_t work=0;
            while(resumed.busy()) {work+=resumed.resume_steps(1+(rng()%7));assert(work<100000);}
            equal_state(original,resumed.inspect());
            assert(original.query()==resumed.completed_answer());
            assert(resumed.completed()==std::uint64_t(i+1));++checked;
        }
        const auto before=resumed.inspect().changes;
        for(Update e:std::vector<Update>{{0,0,INF,'S'},{0,1,1,'?'},{100,0,1,'S'}}) {
            bool blocked=false;try{resumed.begin(e);}catch(const std::invalid_argument&){blocked=true;}
            assert(blocked&&!resumed.busy()&&resumed.inspect().changes==before);
            equal_state(original,resumed.inspect());
        }
    }
    // Start sparse, including a precolored isolated vertex; introduce edges later.
    for(int k:{3,5})for(unsigned seed:{11,32,99}) {
        std::vector<int> colors;
        for(int i=0;i<k+2;++i)colors.push_back(i%k);
        std::vector<Update> initial{{0,1,-1,'S'},{1,2,.25,'S'}};
        DeltaEngine original(colors,k);original.initialize(initial);
        DeltaWeightContinuation resumed(colors,k,initial);
        std::mt19937 rng(seed+k);
        for(int i=0;i<500;++i) {
            int u=int(rng()%colors.size()),v=int(rng()%colors.size());
            Update e{u,v,double(int(rng()%41)-20)/4,'S'};
            if(i%4==0)e.op='D';else if(i%19==0)e.op='N';
            original.apply(std::vector<Update>{e},0,1);resumed.begin(e);
            size_t steps=0;
            while(resumed.busy()) {
                assert(resumed.resume_until(Clock::now())==0);
                steps+=resumed.resume_steps(1+(rng()%7));assert(steps<1000000);
            }
            equal_state(original,resumed.inspect());
            assert(original.query()==resumed.completed_answer());
            assert(resumed.completed()==std::uint64_t(i+1));++checked;
        }
    }
    std::cout<<"PASS "<<checked<<" updates: k3/k5 pause/resume state, work counts and answers equal; "
             <<"insert/delete/reactivate sparse topology; zero/past-deadline work; unsafe publish/reentry/input rejected\n";
}
