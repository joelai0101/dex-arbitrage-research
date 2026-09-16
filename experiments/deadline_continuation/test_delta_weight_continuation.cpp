#include "delta_weight_continuation.hpp"
#include <cassert>
#include <iostream>
#include <random>

using namespace delta;
using deadline_experiment::DeltaWeightContinuation;
void equal_state(const DeltaEngine& a,const DeltaEngine& b) {
    assert(a.states.size()==b.states.size()&&a.arcs.size()==b.arcs.size());
    assert(a.edges.size()==b.edges.size()&&a.candidates==b.candidates);
    assert(a.dirty==b.dirty);
    for(std::size_t i=0;i<a.states.size();++i) {
        const auto& x=a.states[i];const auto& y=b.states[i];
        assert(x.root==y.root&&x.u==y.u&&x.mask==y.mask&&x.level==y.level);
        assert(x.parent==y.parent&&x.terminal==y.terminal&&x.w==y.w&&x.queued==y.queued);
        assert(x.incoming==y.incoming&&x.outgoing==y.outgoing);
    }
    for(std::size_t i=0;i<a.edges.size();++i)assert(a.edges[i].w==b.edges[i].w);
    assert(a.recomputed==b.recomputed&&a.value_changed==b.value_changed);
    assert(a.probes==b.probes&&a.gate_skips==b.gate_skips&&a.changes==b.changes);
}
int main() {
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
        for(Update e:std::vector<Update>{{0,0,1,'S'},{0,1,INF,'D'},{100,0,1,'S'}}) {
            bool blocked=false;try{resumed.begin(e);}catch(const std::invalid_argument&){blocked=true;}
            assert(blocked&&!resumed.busy()&&resumed.inspect().changes==before);
            equal_state(original,resumed.inspect());
        }
    }
    std::cout<<"PASS "<<checked<<" updates: k3/k5 pause/resume state, work counts and answers equal; "
             <<"zero/past-deadline work; unsafe publish/reentry/topology rejected\n";
}
