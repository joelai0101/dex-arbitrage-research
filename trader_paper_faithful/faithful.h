#pragma once
#include "paper_batch_reference_model.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <queue>
#include <stdexcept>

namespace trader::faithful {
using namespace paper_batch;
using Cycle = std::vector<VertexId>;
inline std::size_t cardinality(ColorMask m) { std::size_t n=0;for(;m;m&=m-1)++n;return n; }
inline Cycle canonical(Cycle p) {p.pop_back();std::rotate(p.begin(),std::min_element(p.begin(),p.end()),p.end());p.push_back(p.front());return p;}
// Algorithm 3 source/sink edge queues with explicit predecessor/successor gates.
inline std::vector<std::size_t> ready_edges(const Dag& dag,const std::vector<DirectedEdge>& edges,
                                          bool backward,TieBreakDirection ties){
  auto topology=backward?backward_edge_order(dag,edges,ties):forward_edge_order(dag,edges,ties);
  std::map<VertexId,std::vector<std::size_t>> starts,ends;
  std::map<std::size_t,std::size_t> rank,remaining;
  for(std::size_t i=0;i<topology.size();++i)rank[topology[i]]=i;
  for(auto id:dag.edge_indices){auto e=edges.at(id);if(backward)std::swap(e.source,e.destination);starts[e.source].push_back(id);ends[e.destination].push_back(id);}
  using Ready=std::pair<std::size_t,std::size_t>;
  std::priority_queue<Ready,std::vector<Ready>,std::greater<Ready>> queue;
  for(auto id:dag.edge_indices){auto e=edges.at(id);if(backward)std::swap(e.source,e.destination);remaining[id]=ends[e.source].size();if(!remaining[id])queue.push({rank[id],id});}
  std::vector<std::size_t> order;
  while(!queue.empty()){auto id=queue.top().second;queue.pop();order.push_back(id);
    auto e=edges.at(id);if(backward)std::swap(e.source,e.destination);
    for(auto next:starts[e.destination])if(--remaining.at(next)==0)queue.push({rank[next],next});
  }
  if(order.size()!=dag.edge_indices.size())throw std::logic_error("Algorithm 3 queue coverage");
  return order;
}
struct Metrics {
  std::size_t popped=0, repaired=0, candidate_refreshes=0, maintained=0, deferred=0;
  std::size_t forward_edges=0, backward_edges=0, queue_peak=0;
  double schedule_ms=0, repair_ms=0, propagation_ms=0, candidate_ms=0, classification_ms=0;
};
struct Phase {
#ifdef TRADER_PROFILE
  std::chrono::steady_clock::time_point start=std::chrono::steady_clock::now();
  double& target;
  explicit Phase(double& t):target(t){}
  ~Phase(){target+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();}
#else
  explicit Phase(double&){}
#endif
};

// Section IV all-pairs/color-set DP. No canonical-root restriction or DELTA DAG.
class Engine {
  struct Entry {StateKey key;StateValue value;int direction=0;};
  struct Later {bool operator()(const Entry&a,const Entry&b) const {
    if(a.value.weight!=b.value.weight)return a.value.weight>b.value.weight;
    return b.key<a.key;
  }};
  DirectedWeightedGraph graph_;
  ColorMap colors_;
  std::uint32_t k_;
  ColorMask full_;
  StateTable dp_;
  // Explicit engineering completion of the deletion/increase remark:
  // which selected witnesses actually use a changed edge?
  std::map<DirectedEdge,std::set<StateKey>> witnesses_;
  std::set<DirectedEdge> dirty_closures_;
  std::map<DirectedEdge,Cycle> representatives_;
  std::map<Cycle,std::size_t> references_;
  std::map<Cycle,double> weights_;
  std::set<std::pair<double,Cycle>> ranking_;
  ColorMask bit(VertexId v) const {return ColorMask{1}<<colors_.at(v);}
  void unindex(const StateKey& key,const StateValue& v) {
    for(std::size_t i=1;i<v.path.size();++i){DirectedEdge e{v.path[i-1],v.path[i]};auto it=witnesses_.find(e);
      if(it!=witnesses_.end()){it->second.erase(key);if(it->second.empty())witnesses_.erase(it);}}
  }
  void index(const StateKey& key,const StateValue& v) {
    for(std::size_t i=1;i<v.path.size();++i)witnesses_[{v.path[i-1],v.path[i]}].insert(key);
  }
  void mark(const StateKey& key){if(key.colors==full_)dirty_closures_.insert({key.source,key.destination});}
  void erase(const StateKey& key) {
    auto it=dp_.find(key);if(it==dp_.end())return;unindex(key,it->second);dp_.erase(it);mark(key);
  }
  bool offer(const StateKey& key,const StateValue& value) {
    auto old=dp_.find(key);
    if(old!=dp_.end()&&(old->second.weight<value.weight ||
       (old->second.weight==value.weight&&old->second.path<=value.path)))return false;
    if(old!=dp_.end())unindex(key,old->second);
    dp_[key]=value;index(key,value);mark(key);return true;
  }
  // Algorithm 1: weight-ordered label-correcting queue, NOT Dijkstra.
  // Negative edges are valid; improved labels may be requeued. Colors grow.
  void propagate(std::vector<Entry> seeds) {
    std::priority_queue<Entry,std::vector<Entry>,Later> pending;
    for(auto& e:seeds)pending.push(std::move(e));
    while(!pending.empty()){
      metrics.queue_peak=std::max(metrics.queue_peak,pending.size());
      Entry e=pending.top();pending.pop();++metrics.popped;
      auto it=dp_.find(e.key);
      if(it==dp_.end()||it->second.weight!=e.value.weight||it->second.path!=e.value.path)continue;
      if(cardinality(e.key.colors)>=k_)continue;
      auto extend=[&](VertexId v,double w,bool backward){
        if(e.key.colors&bit(v))return;
        StateKey key{backward?v:e.key.source,backward?e.key.destination:v,e.key.colors|bit(v)};
        StateValue value{e.value.weight+w,e.value.path};
        if(backward)value.path.insert(value.path.begin(),v);else value.path.push_back(v);
        if(offer(key,value))pending.push({key,std::move(value),0});
      };
      if(e.direction>=0)for(auto [v,w]:graph_.outgoing(e.key.destination))extend(v,w,false);
      if(e.direction<=0)for(auto [v,w]:graph_.incoming(e.key.source))extend(v,w,true);
    }
  }
  void remove_rep(const DirectedEdge& key){
    auto it=representatives_.find(key);if(it==representatives_.end())return;
    const Cycle p=it->second;representatives_.erase(it);
    if(--references_.at(p)==0){ranking_.erase({weights_.at(p),p});references_.erase(p);weights_.erase(p);}
  }
  void put_rep(const DirectedEdge& key){
    auto close=graph_.edge_weight(key.destination,key.source);if(!close)return;
    auto state=dp_.find({key.source,key.destination,full_});if(state==dp_.end())return;
    Cycle p=state->second.path;p.push_back(key.source);p=canonical(std::move(p));
    double w=0;for(std::size_t i=1;i<p.size();++i)w+=*graph_.edge_weight(p[i-1],p[i]);
    auto old=weights_.find(p);if(old!=weights_.end())ranking_.erase({old->second,p});
    weights_[p]=w;++references_[p];representatives_[key]=p;ranking_.insert({w,p});
  }
public:
  Metrics metrics;
  Engine(DirectedWeightedGraph graph,ColorMap colors,std::uint32_t k)
      :graph_(std::move(graph)),colors_(std::move(colors)),k_(k),full_(0){
    if(k<2||k>20)throw std::invalid_argument("k outside supported range 2..20");
    full_=(ColorMask{1}<<k)-1;
    for(auto [v,c]:colors_){if(c>=k)throw std::invalid_argument("invalid color");graph_.add_vertex(v);}
    for(auto e:graph_.edges())if(e.source==e.destination)throw std::invalid_argument("self loop");
    dp_=build_static_dp(graph_,colors_,k_);
    for(const auto& [key,value]:dp_)index(key,value);
    for(auto edge:graph_.edges())put_rep({edge.destination,edge.source});
  }
  const StateTable& states() const{return dp_;}
  const DirectedWeightedGraph& graph()const{return graph_;}
  const ColorMap& colors()const{return colors_;}
  CycleAnswer best()const {if(ranking_.empty())return {};return {true,ranking_.begin()->first,ranking_.begin()->second};}
  double gap()const {if(ranking_.empty())return 0;if(ranking_.size()==1)return INFINITY;auto a=ranking_.begin(),b=std::next(a);return b->first-a->first;}
  const auto& ranking()const{return ranking_;}
  std::size_t witness_links()const{std::size_t n=0;for(auto&[e,s]:witnesses_)n+=s.size();return n;}
  void apply_batch(const std::vector<EdgeUpdate>& input,const SchedulePolicy& policy={}) {
    if(input.empty())return;
    Schedule schedule;
    {Phase timer(metrics.schedule_ms);schedule=build_schedule(input,{},DependencyGraphMode::UpdateEdgesOnly,policy);}
    std::set<StateKey> invalid;
    std::map<DirectedEdge,EdgeUpdate> effective;
    std::vector<Entry> repaired;
    {
      Phase timer(metrics.repair_ms);
      for(auto u:schedule.coalesced_updates){
        if(!colors_.count(u.source)||!colors_.count(u.destination))throw std::invalid_argument("undeclared vertex");
        if(!u.erase&&!std::isfinite(u.weight))throw std::invalid_argument("nonfinite weight");
        auto old=graph_.edge_weight(u.source,u.destination);
        if((u.erase&&!old)||(!u.erase&&old&&*old==u.weight))continue;
        DirectedEdge edge{u.source,u.destination};effective[edge]=u;
        if(old&&(u.erase||u.weight>*old)){
          auto hit=witnesses_.find(edge);if(hit!=witnesses_.end())invalid.insert(hit->second.begin(),hit->second.end());
        }
      }
      // Atomic batch-final graph is an explicit completion of undefined apply().
      for(auto [edge,u]:effective){if(u.erase)graph_.remove_edge(u.source,u.destination);else graph_.set_edge(u.source,u.destination,u.weight);
        dirty_closures_.insert({u.destination,u.source});}
      for(auto key:invalid)erase(key);
      std::vector<StateKey> order(invalid.begin(),invalid.end());
      std::sort(order.begin(),order.end(),[](auto a,auto b){auto x=cardinality(a.colors),y=cardinality(b.colors);return x!=y?x<y:a<b;});
      // Re-evaluate only invalidated selected witnesses, shortest color sets first.
      for(auto key:order){++metrics.repaired;std::optional<StateValue> best;
        for(auto [v,w]:graph_.incoming(key.destination)){
          auto pre=dp_.find({key.source,v,key.colors^bit(key.destination)});if(pre==dp_.end())continue;
          StateValue val{pre->second.weight+w,pre->second.path};val.path.push_back(key.destination);
          if(!best||val.weight<best->weight||(val.weight==best->weight&&val.path<best->path))best=std::move(val);
        }
        if(best){offer(key,*best);repaired.push_back({key,*best,0});}
      }
    }
    {
      Phase timer(metrics.propagation_ms);
      propagate(std::move(repaired));
      auto apply=[&](std::size_t id,int direction){
        DirectedEdge e=schedule.dependency_edges.at(id);
        if(direction>0)++metrics.forward_edges;else ++metrics.backward_edges;
        auto update=effective.find(e);if(update==effective.end()||update->second.erase||bit(e.source)==bit(e.destination))return;
        StateKey key{e.source,e.destination,bit(e.source)|bit(e.destination)};
        StateValue value{update->second.weight,{e.source,e.destination}};
        offer(key,value);
        // Run real propagation at each Algorithm-3 apply, not a recorded-only order.
        propagate({{key,value,direction}});
      };
      for(const Dag& dag:schedule.dags){
        for(auto id:ready_edges(dag,schedule.dependency_edges,false,policy.topological_ties))apply(id,1);
        for(auto id:ready_edges(dag,schedule.dependency_edges,true,policy.topological_ties))apply(id,-1);
      }
    }
    {
      Phase timer(metrics.candidate_ms);
      // Section VI: refresh only affected DP closures, never scan every closure.
      metrics.candidate_refreshes+=dirty_closures_.size();
      for(auto key:dirty_closures_)remove_rep(key);
      for(auto key:dirty_closures_)put_rep(key);
      dirty_closures_.clear();
    }
    ++metrics.maintained;
  }
};

// Algorithm 4: adaptive grouping, distinct C1/C2, cached gap. No fixed B in EG.
class Grouped {
  Engine engine_;
  DirectedWeightedGraph live_;
  CycleAnswer anchor_;
  double gap_=0,adverse_=0;
  std::vector<EdgeUpdate> pending_;
public:
  Grouped(DirectedWeightedGraph graph,ColorMap colors,std::uint32_t k)
      :engine_(graph,std::move(colors),k),live_(std::move(graph)),anchor_(engine_.best()),gap_(engine_.gap()){}
  const Engine& engine()const{return engine_;}
  void update(const EdgeUpdate& u){
    bool immediate=false;
    {
      Phase timer(engine_.metrics.classification_ms);
      if(!engine_.colors().count(u.source)||!engine_.colors().count(u.destination)||u.source==u.destination)throw std::invalid_argument("invalid edge");
      if(!u.erase&&!std::isfinite(u.weight))throw std::invalid_argument("nonfinite weight");
      auto old=live_.edge_weight(u.source,u.destination);
      if((u.erase&&!old)||(!u.erase&&old&&*old==u.weight))return;
      bool on=false;for(std::size_t i=1;i<anchor_.cycle.size();++i)on|=anchor_.cycle[i-1]==u.source&&anchor_.cycle[i]==u.destination;
      const bool same=engine_.colors().at(u.source)==engine_.colors().at(u.destination);
      if(!same&&old&&!u.erase)adverse_+=on?std::max(0.0,u.weight-*old):std::max(0.0,*old-u.weight);
      immediate=!same&&(!old||!anchor_.exists||(u.erase&&on)||adverse_>gap_);
      pending_.push_back(u);if(u.erase)live_.remove_edge(u.source,u.destination);else live_.set_edge(u.source,u.destination,u.weight);
      if(!immediate)++engine_.metrics.deferred;
    }
    if(immediate)flush();
  }
  void flush(){if(pending_.empty())return;engine_.apply_batch(pending_);pending_.clear();anchor_=engine_.best();gap_=engine_.gap();adverse_=0;}
  CycleAnswer answer()const {auto a=anchor_;if(!a.exists)return a;a.weight=0;
    for(std::size_t i=1;i<a.cycle.size();++i){auto w=live_.edge_weight(a.cycle[i-1],a.cycle[i]);if(!w)throw std::logic_error("invalid deferred witness");a.weight+=*w;}return a;}
  const DirectedWeightedGraph& live()const{return live_;}
};
}
