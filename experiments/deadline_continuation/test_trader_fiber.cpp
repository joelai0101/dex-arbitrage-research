#include "cooperative_fiber.hpp"
#include "cycle_detector.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
#include <sstream>

using deadline_experiment::CooperativeFiber;
static void equal(const KCycleColorCoding& a, const KCycleColorCoding& b) {
    assert(a.trial_best_weight == b.trial_best_weight);
    assert(a.trial_best_cycle == b.trial_best_cycle);
    assert(a.full_dp_table == b.full_dp_table);
    assert(a.node_colors == b.node_colors);
    assert(a.batch_lines == b.batch_lines);
    assert(a.batch_count == b.batch_count && a.num_updates == b.num_updates);
    assert(a.cumulative_weight == b.cumulative_weight);
    assert(a.batch_weight_threshold_ == b.batch_weight_threshold_);
    assert(a.output_string == b.output_string);
    assert(a.gen_ == b.gen_);
    assert(a.graph.vertices_ == b.graph.vertices_);
    assert(a.graph.out_neighbors_ == b.graph.out_neighbors_);
    assert(a.graph.in_neighbors_ == b.graph.in_neighbors_);
    assert(a.graph.out_weights_ == b.graph.out_weights_);
    assert(a.graph.in_weights_ == b.graph.in_weights_);
    assert(a.graph.out_degree_ == b.graph.out_degree_);
    assert(a.graph.in_degree_ == b.graph.in_degree_);
}
int main() {
    deadline_experiment::FiberThreadScope thread;
    using Clock = CooperativeFiber::Clock;
    // Locals survive suspension; cancellation unwinds them; exceptions return
    // to caller. None of these tests measures latency.
    int live = 0, calls = 0;
    struct Local { int& live; Local(int& x):live(x){++live;} ~Local(){--live;} };
    {
        CooperativeFiber f;
        f.start([&] { Local guard(live); for(int i=0;i<5;++i){
            deadline_experiment::trader_checkpoint(); ++calls;
        }});
        assert(!f.advance_until(Clock::time_point::max(), 2));
        assert(live == 1 && calls == 1);
        const auto steps = f.steps();
        assert(!f.advance_until(Clock::now(), 10));
        assert(!f.advance_until(Clock::time_point::max(), 0));
        assert(steps == f.steps() && calls == 1);
    }
    assert(live == 0 && calls == 1);
    {
        CooperativeFiber f; f.start([] { throw std::runtime_error("test"); });
        bool caught=false; try { f.advance_until(Clock::time_point::max()); }
        catch(const std::runtime_error&) { caught=true; }
        assert(caught && f.done());
    }
    std::uint64_t checks=0, pauses=0, checkpoint_steps=0;
    for(unsigned k : {3u,5u})for(unsigned seed=1;seed<=4;++seed)
    for(unsigned mode : {1u,50u,100u,500u,1000u,0u}) {
        DirectedGraph graph;
        for(unsigned u=0;u<10;++u)for(unsigned v=0;v<10;++v)
            if(u!=v)graph.update_edge(u,v,-0.2-double((u+v)%3)*0.01);
        // Fixed deterministic fixture rule: a complete negative graph has a
        // colorful k-cycle only if the initialization uses every color. This
        // selects fixture coverage, not a fast run or an experimental answer.
        unsigned init_seed=seed*100;
        for(;;++init_seed) {
            std::mt19937 gen(init_seed);std::uniform_int_distribution<int> dist(0,k-1);
            unsigned mask=0;for(unsigned u=0;u<10;++u)mask|=1u<<dist(gen);
            if(mask==(1u<<k)-1)break;
            assert(init_seed<seed*100+100);
        }
        KCycleColorCoding original(graph,k,1,1,init_seed,mode?mode:1000,mode==0);
        original.common_start(init_seed);
        // Defined initialization requires a found negative cycle, as in UNI.
        assert(!original.trial_best_cycle.empty());
        KCycleColorCoding resumed=original;
        CooperativeFiber f;
        for(unsigned i=0;i<105;++i) {
            unsigned u=(i*7)%10,v=(i*3+1)%10;if(u==v)v=(v+1)%10;
            std::ostringstream row;
            if(i%11==0)row<<u<<' '<<v<<" N";
            else row<<u<<' '<<v<<' '<<(-0.3+double(i%17)*0.025);
            const auto line=row.str();
            original.common_apply(line);
            f.start([&resumed,line]{resumed.common_apply(line);});
            while(!f.advance_until(Clock::time_point::max(),1+i%7))++pauses;
            equal(original,resumed);++checks;
        }
        original.common_finish();
        f.start([&]{resumed.common_finish();});
        while(!f.advance_until(Clock::time_point::max(),3))++pauses;
        equal(original,resumed);++checks;checkpoint_steps+=f.steps();
    }
    std::cout<<"PASS completed_state_checks="<<checks<<" pauses="<<pauses
             <<" checkpoint_steps="<<checkpoint_steps<<"\n";
}
