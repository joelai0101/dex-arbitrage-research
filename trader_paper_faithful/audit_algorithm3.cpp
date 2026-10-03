#define TRADER_TEST_HOOKS
#include "faithful.h"
#include <iostream>
#include <tuple>
using namespace trader::faithful;

EdgeUpdate update(VertexId u,VertexId v,double w,std::size_t sequence){return {u,v,w,false,"",sequence};}

int audit(const char* name,DirectedWeightedGraph graph,const ColorMap& colors,
          std::uint32_t k,const std::vector<EdgeUpdate>& updates,StateKey target,bool require_once){
  const auto schedule=build_schedule(updates,graph.edges(),DependencyGraphMode::VertexInduced);
  if(schedule.dags.size()!=1)throw std::runtime_error("audit fixture requires exactly one DAG");
  Engine engine(graph,colors,k);
  std::map<std::tuple<int,VertexId,VertexId,ColorMask>,std::size_t> changes;
  IndexedStates before;
  std::cout<<"CASE "<<name<<" dags="<<schedule.dags.size()<<" initial_target="<<engine.states().at(target).weight<<'\n';
  engine.observe_batch_edge=[&](int direction,DirectedEdge edge,bool completed){
    if(!completed){before=engine.states();return;}
    for(const auto& [key,value]:engine.states()){
      const auto old=before.find(key);
      if(old!=before.end()&&old->second.weight==value.weight)continue;
      ++changes[{direction,key.source,key.destination,key.colors}];
      if(SameState{}(key,target))std::cout<<"TARGET direction="<<direction<<" edge="<<edge.source<<"->"<<edge.destination
        <<" old="<<(old==before.end()?INFINITY:old->second.weight)<<" new="<<value.weight<<'\n';
    }
  };
  engine.apply_batch(updates);
  auto expected=enumerate_state_oracle(engine.graph(),colors,k);
  const auto full=(ColorMask{1}<<k)-1;
  for(auto it=expected.begin();it!=expected.end();){
    if(it->first.colors==full&&!engine.graph().has_edge(it->first.destination,it->first.source))it=expected.erase(it);else ++it;
  }
  const StateTable actual(engine.states().begin(),engine.states().end());
  const auto comparison=compare_state_tables(expected,actual);
  std::size_t repeated=0,maximum=0;
  for(auto [key,count]:changes){if(count>1)++repeated;maximum=std::max(maximum,count);}
  std::cout<<"RESULT "<<name<<" repeated_state_passes="<<repeated<<" max_weight_changes_per_pass="<<maximum
    <<" target="<<engine.states().at(target).weight<<" oracle_target="<<expected.at(target).weight
    <<" full_dp_equal="<<comparison.equal<<'\n';
  if(!comparison.equal)std::cout<<"DIFFERENCE "<<comparison.first_difference<<'\n';
  // A known mechanism gap must not be reported as a correctness failure, or
  // conversely hidden by the fact that the final DP is correct.
  return !comparison.equal?1:require_once&&repeated?2:0;
}

int main(int argc,char** argv){
  if(argc>2||(argc==2&&std::string(argv[1])!="--require-once"))return 3;
  const bool require_once=argc==2;
  std::vector<int> results;
  DirectedWeightedGraph diamond;
  diamond.set_edge(0,1,10);diamond.set_edge(0,2,10);
  diamond.set_edge(1,3,1);diamond.set_edge(2,3,1);
  results.push_back(audit("diamond_induced",diamond,{{0,0},{1,1},{2,1},{3,2}},4,
    {update(0,1,4,1),update(0,2,1,2),update(1,3,1,3),update(2,3,1,4)},{0,3,7},require_once));
  // Vertex 3 and both suffix edges are outside the updated-endpoint DAG.
  results.push_back(audit("diamond_boundary",diamond,{{0,0},{1,1},{2,1},{3,2}},4,
    {update(0,1,4,1),update(0,2,1,2)},{0,3,7},require_once));

  DirectedWeightedGraph three_paths;
  for(auto edge:std::vector<DirectedEdge>{{0,1},{0,2},{0,3}})three_paths.set_edge(edge.source,edge.destination,10);
  for(auto edge:std::vector<DirectedEdge>{{1,4},{2,6},{3,5},{4,7},{5,7},{6,7}})three_paths.set_edge(edge.source,edge.destination,1);
  results.push_back(audit("three_paths",three_paths,{{0,0},{1,1},{2,1},{3,1},{4,2},{5,2},{6,2},{7,3}},5,
    {update(0,1,7,1),update(0,2,4,2),update(0,3,1,3),update(4,7,1,4),update(5,7,1,5),update(6,7,1,6)},{0,7,15},require_once));
  if(std::find(results.begin(),results.end(),1)!=results.end())return 1;
  return *std::max_element(results.begin(),results.end());
}
