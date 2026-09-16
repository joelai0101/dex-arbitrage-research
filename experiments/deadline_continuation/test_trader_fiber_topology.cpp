#include "cooperative_fiber.hpp"
#include "cycle_detector.h"
#include <cassert>
#include <iostream>
#include <memory>
#include <sstream>

using deadline_experiment::CooperativeFiber;
static void equal(const KCycleColorCoding& a,const KCycleColorCoding& b) {
    assert(a.trial_best_weight==b.trial_best_weight && a.trial_best_cycle==b.trial_best_cycle);
    assert(a.full_dp_table==b.full_dp_table && a.node_colors==b.node_colors);
    assert(a.batch_lines==b.batch_lines && a.batch_count==b.batch_count);
    assert(a.num_updates==b.num_updates && a.cumulative_weight==b.cumulative_weight);
    assert(a.batch_weight_threshold_==b.batch_weight_threshold_ && a.gen_==b.gen_);
    assert(a.output_string==b.output_string);
    assert(a.graph.vertices_==b.graph.vertices_ && a.graph.is_valid_vertex_==b.graph.is_valid_vertex_);
    assert(a.graph.out_neighbors_==b.graph.out_neighbors_ && a.graph.in_neighbors_==b.graph.in_neighbors_);
    assert(a.graph.out_weights_==b.graph.out_weights_ && a.graph.in_weights_==b.graph.in_weights_);
    assert(a.graph.out_degree_==b.graph.out_degree_ && a.graph.in_degree_==b.graph.in_degree_);
}
static unsigned covered_seed(unsigned first,unsigned k) {
    for(unsigned seed=first;seed<first+100;++seed) {
        std::mt19937 gen(seed);std::uniform_int_distribution<int> dist(0,k-1);
        unsigned mask=0;for(unsigned i=0;i<10;++i)mask|=1u<<dist(gen);
        if(mask==(1u<<k)-1)return seed;
    }
    throw std::runtime_error("fixture cannot cover colors");
}
int main(int argc,char** argv) {
    deadline_experiment::FiberThreadScope thread;
    using Clock=CooperativeFiber::Clock;
    std::uint64_t checks=0,pauses=0,steps=0;
    if(argc==1) {
        for(unsigned k:{3u,5u})for(unsigned mode:{1u,50u,100u,500u,1000u,0u}) {
            DirectedGraph graph;
            for(unsigned u=0;u<10;++u)for(unsigned v=0;v<10;++v)
                if(u!=v)graph.update_edge(u,v,-0.2-double((u+v)%3)*0.01);
            std::unique_ptr<KCycleColorCoding> original[2],resumed[2];
            CooperativeFiber fibers[2];
            for(unsigned j=0;j<2;++j) {
                auto seed=covered_seed(100+j*100,k);
                original[j]=std::make_unique<KCycleColorCoding>(graph,k,1,1,seed,mode?mode:1,mode==0);
                original[j]->common_start(seed);assert(!original[j]->common_path().empty());
                resumed[j]=std::make_unique<KCycleColorCoding>(*original[j]);
            }
            for(unsigned i=0;i<108;++i) {
                unsigned u=1,v=2;std::string token=std::to_string(-0.3+double(i%17)*0.025);
                switch(i%6) {
                    case 0:u=10+i/6;v=1;break;       // unseen source
                    case 1:u=1;v=100+i/6;break;      // unseen destination
                    case 2:u=200+i;v=300+i;break;    // both unseen
                    case 3:u=10+i/6;v=1;break;       // reweight inserted edge
                    case 4:token="N";break;
                }
                auto line=std::to_string(u)+" "+std::to_string(v)+" "+token;
                for(unsigned j=0;j<2;++j) {
                    original[j]->common_apply(line);
                    fibers[j].start([&,j,line]{resumed[j]->common_apply(line);});
                }
                while(!fibers[0].done()||!fibers[1].done())for(unsigned j=0;j<2;++j) {
                    auto other_steps=fibers[1-j].steps();
                    if(!fibers[j].advance_until(Clock::time_point::max(),1+(i+j)%7))++pauses;
                    assert(fibers[1-j].steps()==other_steps);
                }
                for(unsigned j=0;j<2;++j){equal(*original[j],*resumed[j]);++checks;}
            }
            for(unsigned j=0;j<2;++j) {
                original[j]->common_finish();fibers[j].start([&,j]{resumed[j]->common_finish();});
                while(!fibers[j].advance_until(Clock::time_point::max(),3))++pauses;
                equal(*original[j],*resumed[j]);++checks;steps+=fibers[j].steps();
                assert(resumed[j]->graph.vertices_.size()>10);
            }
        }
        std::cout<<"PASS topology completed_state_checks="<<checks<<" pauses="<<pauses<<" steps="<<steps<<"\n";
    } else {
        if(argc!=4)throw std::runtime_error("graph updates official-seeds");
        DirectedGraph graph;graph.load_edge_list(argv[1]);
        std::ifstream seed_file(argv[3]);std::string line;std::getline(seed_file,line);
        assert(std::getline(seed_file,line));std::istringstream row(line);
        std::vector<unsigned> seeds;unsigned seed;while(row>>seed)seeds.push_back(seed);assert(seeds.size()>=80);
        std::ifstream updates_file(argv[2]);std::vector<std::string> updates;
        while(updates.size()<32&&std::getline(updates_file,line))updates.push_back(line);assert(updates.size()==32);
        // Sequential engine pairs bound memory. This is not an 80-resident
        // service or a timing experiment. No synthetic EOF flush of the prefix.
        for(unsigned trial=0;trial<80;++trial) {
            KCycleColorCoding original(graph,5,1,10,seeds[trial],1,true);
            original.common_start(seeds[trial]);
            assert(!original.common_path().empty());
            KCycleColorCoding resumed=original;CooperativeFiber fiber;
            for(const auto& update:updates) {
                original.common_apply(update);fiber.start([&resumed,update]{resumed.common_apply(update);});
                while(!fiber.advance_until(Clock::time_point::max(),17))++pauses;
                equal(original,resumed);++checks;
            }
            steps+=fiber.steps();std::cout<<"TRIAL "<<trial+1<<" checks="<<checks<<std::endl;
        }
        std::cout<<"PASS UNI1-prefix32 completed_state_checks="<<checks<<" pauses="<<pauses<<" steps="<<steps<<"\n";
    }
}
