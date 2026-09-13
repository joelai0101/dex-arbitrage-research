#include "faithful.h"
#include <functional>
#include <iostream>
#include <random>
using namespace trader::faithful;
std::size_t checks=0;
void require(bool ok,const char* message){++checks;if(!ok)throw std::runtime_error(message);}
StateTable ordered(const IndexedStates& states){return {states.begin(),states.end()};}
std::set<std::pair<double,Cycle>> cycles(const DirectedWeightedGraph& g,const ColorMap& colors,int k){
  std::set<std::pair<double,Cycle>> result;
  for(auto root:g.vertices()){
    Cycle path{root};std::set<VertexId> used{root};
    std::function<void(VertexId,double,ColorMask)> visit=[&](VertexId v,double weight,ColorMask mask){
      if(path.size()==static_cast<std::size_t>(k)){
        auto close=g.edge_weight(v,root);if(close){Cycle p=path;p.push_back(root);result.insert({weight+*close,canonical(p)});}return;
      }
      for(auto [n,w]:g.outgoing(v))if(!used.count(n)&&!(mask&(ColorMask{1}<<colors.at(n)))){
        used.insert(n);path.push_back(n);visit(n,weight+w,mask|(ColorMask{1}<<colors.at(n)));path.pop_back();used.erase(n);
      }
    };visit(root,0,ColorMask{1}<<colors.at(root));
  }return result;
}
void check(const Engine& e,int k){
  auto expected=enumerate_state_oracle(e.graph(),e.colors(),k);
  // Only terminal nonclosing states are projected out; the oracle itself and
  // independent exhaustive best/second-cycle checks remain unchanged.
  for(auto it=expected.begin();it!=expected.end();){
    if(cardinality(it->first.colors)==static_cast<std::size_t>(k)&&!e.graph().has_edge(it->first.destination,it->first.source))it=expected.erase(it);else ++it;
  }
  auto comparison=compare_state_tables(expected,ordered(e.states()));
  if(!comparison.equal)throw std::runtime_error(comparison.first_difference);
  require(comparison.equal,"complete state table");
  for(auto& [key,value]:e.states()){
    double w=0;ColorMask mask=0;bool legal=value.path.front()==key.source&&value.path.back()==key.destination;
    for(std::size_t i=0;i<value.path.size();++i){auto bit=ColorMask{1}<<e.colors().at(value.path[i]);legal&=!(mask&bit);mask|=bit;
      if(i){auto edge=e.graph().edge_weight(value.path[i-1],value.path[i]);legal&=bool(edge);if(edge)w+=*edge;}}
    require(legal&&mask==key.colors&&std::abs(w-value.weight)<1e-9,"state witness invalid");
  }
  auto all=cycles(e.graph(),e.colors(),k);auto best=e.best();
  require(best.exists==!all.empty(),"best existence");
  if(!all.empty()){
    require(std::abs(best.weight-all.begin()->first)<1e-9,"best weight");
    require(is_legal_colorful_cycle(e.graph(),e.colors(),k,best.cycle,best.weight),"best witness");
    const double gap=all.size()==1?INFINITY:std::next(all.begin())->first-all.begin()->first;
    require((std::isinf(gap)&&std::isinf(e.gap()))||std::abs(gap-e.gap())<1e-9,"distinct runner-up gap");
  }
}
EdgeUpdate upd(int u,int v,double w,std::size_t seq,bool erase=false){return {static_cast<VertexId>(u),static_cast<VertexId>(v),w,erase,"",seq};}
int main(){try{
  // Two improved branches meet in one state; coalesce within each DAG pass.
  DirectedWeightedGraph diamond;ColorMap dc{{0,0},{1,1},{2,1},{3,2}};
  diamond.set_edge(0,1,10);diamond.set_edge(0,2,10);diamond.set_edge(1,3,1);diamond.set_edge(2,3,1);diamond.set_edge(3,0,3);
  Engine shared(diamond,dc,3);
  shared.apply_batch({upd(0,1,2,1),upd(0,2,1,2),upd(1,3,0,3),upd(2,3,0,4)});check(shared,3);
  require(shared.states().at({0,3,7}).weight==1,"diamond join must include both branches before finalization");
  require(shared.metrics.popped<14&&shared.metrics.changed_states==9&&shared.metrics.nonimproving_rejected>0,"reject nonimproving labels before queue insertion; retain both DAG direction passes");
  require(shared.metrics.dag_forward_passes>0&&shared.metrics.dag_forward_passes==shared.metrics.dag_backward_passes&&shared.metrics.algorithm1_calls==0,"batch must execute separate DAG direction passes");
  DirectedWeightedGraph cancel;ColorMap cc{{0,0},{1,1},{2,2}};
  cancel.set_edge(0,1,1);cancel.set_edge(1,2,1);cancel.set_edge(2,0,1);Engine stable(cancel,cc,3);
  stable.apply_batch({upd(0,1,2,1),upd(1,2,0,2)});check(stable,3);
  require(stable.metrics.unchanged_repairs==1&&stable.metrics.changed_states==4,"unchanged repaired path must retain its label without propagation");
  DirectedWeightedGraph open;open.set_edge(0,1,-2);open.set_edge(1,2,-2);Engine closing(open,cc,3);
  require(!closing.states().count({0,2,7}),"unclosed terminal path retained");
  closing.apply_batch({upd(2,0,-2,1)});check(closing,3);
  require(closing.best().weight==-6&&closing.states().count({0,2,7}),"new closing edge must materialize terminal state");
  closing.apply_batch({upd(2,0,0,2,true)});check(closing,3);
  require(!closing.best().exists&&!closing.states().count({0,2,7}),"removed closure must retire terminal state");
  // A literal min(old,new) weight-increase treatment leaves -2 instead of +3.
  DirectedWeightedGraph g;g.set_edge(0,1,-1);g.set_edge(1,2,-1);g.set_edge(2,0,-1);
  ColorMap c{{0,0},{1,1},{2,2}};Engine e(g,c,3);
  auto literal=ordered(e.states());g.set_edge(0,1,4);literal[{0,1,3}].weight=4;
  require(!compare_state_tables(enumerate_state_oracle(g,c,3),literal).equal,"literal increase counterexample disappeared");
  e.apply_batch({upd(0,1,4,1)});check(e,3);
  e.apply_batch({upd(0,1,0,2,true)});check(e,3);
  e.apply_batch({upd(0,1,-4,3)});check(e,3);
  Engine single(g,c,3);single.apply_single(upd(1,2,-5,4));check(single,3);
  require(single.metrics.algorithm1_calls==1&&single.metrics.dag_forward_passes==0,"single edge must route through Algorithm 1");
  // Equal-weight distinct cycles, repeated edge writes, mutually dependent DAGs.
  std::mt19937 rng(9132026);
  for(int k=2;k<=5;++k)for(int sample=0;sample<16;++sample){
    int n=k+2;DirectedWeightedGraph graph;ColorMap colors;
    for(int v=0;v<n;++v){graph.add_vertex(v);colors[v]=v%k;}
    for(int u=0;u<n;++u)for(int v=0;v<n;++v)if(u!=v&&rng()%3==0)graph.set_edge(u,v,static_cast<int>(rng()%17)-8);
    Engine one(graph,colors,k),other(graph,colors,k);Grouped grouped(graph,colors,k);
    check(one,k);std::size_t seq=0;
    for(int step=0;step<36;++step){
      std::vector<EdgeUpdate> batch;
      for(int j=0;j<1+step%5;++j){int u=rng()%n,v=rng()%n;while(v==u)v=rng()%n;
        auto update=upd(u,v,static_cast<int>(rng()%21)-10,++seq,rng()%9==0);batch.push_back(update);
        grouped.update(update);auto answer=grouped.answer();auto all=cycles(grouped.live(),colors,k);
        require(answer.exists==!all.empty(),"EG arrival existence");
        if(answer.exists)require(std::abs(answer.weight-all.begin()->first)<1e-9&&is_legal_colorful_cycle(grouped.live(),colors,k,answer.cycle,answer.weight),"EG deferred/immediate answer");
      }
      one.apply_batch(batch);check(one,k);
      SchedulePolicy policy;policy.reverse_dag_order=true;policy.vertex_ties=TieBreakDirection::Descending;policy.edge_ties=TieBreakDirection::Descending;policy.topological_ties=TieBreakDirection::Descending;
      other.apply_batch(batch,policy);check(other,k);
      require(compare_state_tables(ordered(one.states()),ordered(other.states())).equal,"DAG ordering changed DP");
      grouped.flush();check(grouped.engine(),k);
    }
  }
  // Equal gap must permit safe deferral; insertion/same-color and EOF are covered.
  DirectedWeightedGraph tied;ColorMap colors{{0,0},{1,1},{2,2},{3,1}};
  for(auto [v,col]:colors)tied.add_vertex(v);
  for(auto edge:std::vector<DirectedEdge>{{0,1},{1,2},{2,0},{0,3},{3,2}})tied.set_edge(edge.source,edge.destination,-1);
  Engine tied_engine(tied,colors,3);check(tied_engine,3);require(tied_engine.gap()==0,"tied runner-up");
  Grouped eg(tied,colors,3);eg.update(upd(1,3,-100,1));require(eg.engine().metrics.maintained==0,"same-color insertion triggered");eg.flush();check(eg.engine(),3);
  DirectedWeightedGraph isolated;ColorMap ic;
  for(int i=0;i<20;++i){int a=3*i;for(int j=0;j<3;++j){ic[a+j]=j;isolated.set_edge(a+j,a+(j+1)%3,i==0?-3:-2);}}
  Engine local(isolated,ic,3);auto before=local.metrics.candidate_refreshes;
  local.apply_batch({upd(0,1,20,1)});check(local,3);
  require(local.metrics.candidate_refreshes-before<local.ranking().size(),"best-edge update scanned all candidates");
  Grouped boundary(isolated,ic,3);
  boundary.update(upd(0,1,0,1)); // old best -9 + 3 equals runner-up -6
  require(boundary.engine().metrics.maintained==0&&boundary.answer().weight==-6,"gap equality should defer safely");
  boundary.update(upd(0,1,1,2));
  require(boundary.engine().metrics.maintained==1&&boundary.answer().weight==-6,"gap crossing should maintain and replace best");
  check(boundary.engine(),3);
  require(boundary.engine().metrics.eg_gap_triggers==1&&boundary.engine().metrics.eg_grouped_updates==2&&boundary.engine().metrics.eg_group_sizes.at(2)==1,"EG gap trigger must flush the whole deferred group");
  std::cout<<"PASS "<<checks<<" checks; full DP, legal witnesses, top-two, EG arrivals, mixed batches and schedule permutations\n";
  return 0;
}catch(const std::exception& ex){std::cerr<<"FAIL after "<<checks<<" checks: "<<ex.what()<<'\n';return 1;}}
