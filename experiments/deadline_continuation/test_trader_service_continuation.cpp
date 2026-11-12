#include "trader_service_continuation.hpp"
#include <cassert>
#include <iostream>

using deadline_experiment::TraderServiceContinuation;
static void equal(const KCycleColorCoding& a,const KCycleColorCoding& b) {
    assert(a.full_dp_table==b.full_dp_table && a.node_colors==b.node_colors);
    assert(a.trial_best_weight==b.trial_best_weight && a.trial_best_cycle==b.trial_best_cycle);
    assert(a.batch_lines==b.batch_lines && a.batch_count==b.batch_count && a.num_updates==b.num_updates);
    assert(a.cumulative_weight==b.cumulative_weight && a.batch_weight_threshold_==b.batch_weight_threshold_);
    assert(a.gen_==b.gen_ && a.output_string==b.output_string);
    assert(a.graph.vertices_==b.graph.vertices_ && a.graph.is_valid_vertex_==b.graph.is_valid_vertex_);
    assert(a.graph.out_neighbors_==b.graph.out_neighbors_ && a.graph.in_neighbors_==b.graph.in_neighbors_);
    assert(a.graph.out_weights_==b.graph.out_weights_ && a.graph.in_weights_==b.graph.in_weights_);
    assert(a.graph.out_degree_==b.graph.out_degree_ && a.graph.in_degree_==b.graph.in_degree_);
}
int main() {
    deadline_experiment::FiberThreadScope thread;
    using Clock=TraderServiceContinuation::Clock;
    size_t checks=0,arrivals=0,debt_rows=0,stale_answers=0;
    for(unsigned k:{3u,5u}) {
        DirectedGraph graph;std::map<std::pair<uint32_t,uint32_t>,double> live;
        for(unsigned u=0;u<10;++u)for(unsigned v=0;v<10;++v)if(u!=v) {
            graph.update_edge(u,v,-0.2);live[{u,v}]=-0.2;
        }
        std::vector<unsigned> seeds;
        for(unsigned seed=1;seeds.size()<80;++seed) {
            std::mt19937 rng(seed);std::uniform_int_distribution<int> dist(0,k-1);
            unsigned mask=0;for(unsigned i=0;i<10;++i)mask|=1u<<dist(rng);
            if(mask==(1u<<k)-1)seeds.push_back(seed);
        }
        TraderServiceContinuation service(graph,k,seeds);
        std::vector<std::unique_ptr<KCycleColorCoding>> reference;
        for(auto seed:seeds) {
            auto e=std::make_unique<KCycleColorCoding>(graph,k,1,10,seed,1,true);
            e->common_start(seed);reference.push_back(std::move(e));
        }
        assert(service.current_candidate());
        auto check_candidate=[&] {
            auto c=service.current_candidate();if(!c)return;
            assert(c->graph_version==service.accepted() && c->source_version<=c->graph_version);
            double w=0;for(unsigned i=0;i<k;++i)w+=live.at({c->path[i],c->path[i+1]});
            assert(w==c->weight&&w<0);if(c->source_version<c->graph_version)++stale_answers;
        };
        auto accept=[&](unsigned u,unsigned v,const std::string& token) {
            const auto line=std::to_string(u)+" "+std::to_string(v)+" "+token;
            service.accept(line);if(token!="N")live[{u,v}]=std::stod(token);
            for(auto& e:reference)e->common_apply(line);
            ++arrivals;if(service.backlog()>1)++debt_rows;
            const auto steps=service.work_steps();
            assert(service.advance_steps(0)==0 && service.advance_until(Clock::now())==0);
            assert(steps==service.work_steps());
            assert(service.backlog()==service.accepted()-service.completed());
            check_candidate();
        };
        auto drain_for_test=[&] {
            uint64_t steps=0;while(service.backlog()) {
                steps+=service.advance_steps(17);assert(steps<10000000);check_candidate();
            }
            for(size_t t=0;t<80;++t){equal(*reference[t],service.inspect_completed(t));++checks;}
        };
        // No maintenance: all old cached negative paths become nonnegative.
        // This validates current-graph filtering, not an oracle search.
        for(unsigned u=0;u<10;++u)for(unsigned v=0;v<10;++v)if(u!=v)accept(u,v,"0.5");
        assert(!service.current_candidate() && service.completed()==0 && service.backlog()==90);
        bool blocked=false;try{service.inspect_completed(0);}catch(const std::logic_error&){blocked=true;}
        assert(blocked);drain_for_test();
        for(unsigned i=0;i<80;++i) {
            auto u=i%5==0?10+i/5:i%10;auto v=(i*3+1)%10;
            accept(u,v,i%11==0?"N":std::to_string(-0.4+double(i%13)*0.1));
            service.advance_steps(1+i%13);check_candidate();
            if(i%20==19)drain_for_test();
        }
        const auto version=service.accepted();
        for(auto line:{"-1 0 1","0 1 D","0 1 inf","0 1 1 extra","100000 0 1"}) {
            bool rejected=false;try{service.accept(line);}catch(const std::exception&){rejected=true;}
            assert(rejected && service.accepted()==version && service.backlog()==0);
        }
        // Destroy a service while its core is suspended; cancellation unwinds
        // the job before the engine storage is destroyed, without draining.
        { TraderServiceContinuation abandoned(graph,k,{seeds[0]});
          abandoned.accept("0 1 -0.6");abandoned.advance_steps(2);assert(abandoned.backlog()==1); }
    }
    assert(debt_rows>0&&stale_answers>0);
    std::cout<<"PASS arrivals="<<arrivals<<" full_engine_checks="<<checks
             <<" backlog_arrivals="<<debt_rows<<" stale_valid_queries="<<stale_answers
             <<"; 80 resident engines, FIFO, current-graph cache, no formal timing\n";
}
