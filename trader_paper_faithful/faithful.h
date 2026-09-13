#pragma once
#include "paper_batch_reference_model.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <queue>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

namespace trader::faithful {
using namespace paper_batch;
using Cycle = std::vector<VertexId>;
// Storage-only optimization; the independently ordered reference DP is unchanged.
struct StateHash {
  std::size_t operator()(const StateKey& key) const {
    std::uint64_t x=(std::uint64_t(key.source)<<32)|key.destination;
    x^=key.colors*0x9e3779b97f4a7c15ULL;
    x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;
    x=(x^(x>>27))*0x94d049bb133111ebULL;
    return x^(x>>31);
  }
};
struct SameState {
  bool operator()(const StateKey& a,const StateKey& b) const {
    return a.source==b.source&&a.destination==b.destination&&a.colors==b.colors;
  }
};
using IndexedStates=std::unordered_map<StateKey,StateValue,StateHash,SameState>;
using WitnessStates=std::unordered_set<StateKey,StateHash,SameState>;
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
  std::size_t changed_states=0, unchanged_repairs=0;
  std::size_t algorithm1_calls=0, dag_forward_passes=0, dag_backward_passes=0;
  std::size_t eg_changed_arrivals=0, eg_immediate=0, eg_gap_triggers=0, eg_new_triggers=0, eg_no_anchor_triggers=0, eg_deleted_best_triggers=0, eg_eof_flushes=0;
  std::size_t eg_grouped_updates=0, eg_group_max=0;
  std::map<std::size_t,std::size_t> eg_group_sizes;
  double schedule_ms=0, repair_ms=0, propagation_ms=0, candidate_ms=0, classification_ms=0;
#ifdef TRADER_PROFILE
  double dp_total_ms=0;
#endif
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
#ifdef TRADER_PROFILE
// Declared before batch-local containers, so destruction runs after their cleanup.
// Candidate timing is nested and subtracted, leaving a complete DP-maintenance
// interval, including scheduling and scratch allocation/deallocation.
struct DPMaintenancePhase {
  Metrics& metrics;
  double candidate_before;
  std::chrono::steady_clock::time_point start=std::chrono::steady_clock::now();
  explicit DPMaintenancePhase(Metrics& m):metrics(m),candidate_before(m.candidate_ms){}
  ~DPMaintenancePhase(){metrics.dp_total_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()-(metrics.candidate_ms-candidate_before);}
};
#endif

// Section IV endpoint/color-set DP. All shorter masks; terminal masks only
// for existing closing edges. No canonical-root restriction or DELTA DAG.
class Engine {
  DirectedWeightedGraph graph_;
  ColorMap colors_;
  std::uint32_t k_;
  ColorMask full_;
  IndexedStates dp_;
  // Explicit engineering completion of the deletion/increase remark:
  // which selected witnesses actually use a changed edge?
  std::map<DirectedEdge,WitnessStates> witnesses_;
  std::set<DirectedEdge> dirty_closures_;
  std::map<DirectedEdge,Cycle> representatives_;
  std::map<Cycle,std::size_t> references_;
  std::map<Cycle,double> weights_;
  std::set<std::pair<double,Cycle>> ranking_;
  ColorMask bit(VertexId v) const {return ColorMask{1}<<colors_.at(v);}
  bool needed(const StateKey& key)const{return key.colors!=full_||graph_.has_edge(key.destination,key.source);}
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
    if(old!=dp_.end()){
      // Weight-only changes do not alter which edges use this selected witness.
      const bool changed_path=old->second.path!=value.path;
      if(changed_path)unindex(key,old->second);
      old->second=value;
      if(changed_path)index(key,value);
    }else {dp_.emplace(key,value);index(key,value);}
    mark(key);return true;
  }
  // Algorithm 1: min-weight priority queue with both endpoint extensions.
  // Repair of invalid increased/deleted witnesses is a separate completion.
  void propagate_priority(const std::vector<EdgeUpdate>& updates){
    struct Entry{StateKey key;StateValue value;};
    struct Later{bool operator()(const Entry&a,const Entry&b)const{
      return a.value.weight!=b.value.weight?a.value.weight>b.value.weight:b.key<a.key;
    }};
    std::priority_queue<Entry,std::vector<Entry>,Later> queue;
    for(auto u:updates){if(u.erase||bit(u.source)==bit(u.destination))continue;
      StateKey key{u.source,u.destination,bit(u.source)|bit(u.destination)};if(!needed(key))continue;
      StateValue value{u.weight,{u.source,u.destination}};offer(key,value);queue.push({key,value});
    }
    ++metrics.algorithm1_calls;
    while(!queue.empty()){
      metrics.queue_peak=std::max(metrics.queue_peak,queue.size());auto entry=queue.top();queue.pop();++metrics.popped;
      auto old=dp_.find(entry.key);if(old==dp_.end()||old->second.weight!=entry.value.weight||old->second.path!=entry.value.path)continue;
      if(cardinality(entry.key.colors)==k_)continue;
      auto extend=[&](VertexId v,double weight,bool backward){
        if(entry.key.colors&bit(v))return;
        StateKey key{backward?v:entry.key.source,backward?entry.key.destination:v,entry.key.colors|bit(v)};if(!needed(key))return;
        StateValue value{entry.value.weight+weight,entry.value.path};
        if(backward)value.path.insert(value.path.begin(),v);else value.path.push_back(v);
        if(offer(key,value)){++metrics.changed_states;queue.push({key,std::move(value)});}
      };
      for(auto [v,w]:graph_.outgoing(entry.key.destination))extend(v,w,false);
      for(auto [v,w]:graph_.incoming(entry.key.source))extend(v,w,true);
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
    // Same forward recurrence as the independent reference, without building
    // terminal paths that cannot close and can never serve as a predecessor.
    IndexedStates layer;
    for(auto v:graph_.vertices())layer.emplace(StateKey{v,v,bit(v)},StateValue{0,{v}});
    for(std::size_t length=1;length<=k_;++length){
      IndexedStates next;
      if(length<k_)for(auto& [key,value]:layer)for(auto [v,w]:graph_.outgoing(key.destination)){
        if(key.colors&bit(v))continue;
        StateKey successor{key.source,v,key.colors|bit(v)};if(!needed(successor))continue;
        StateValue candidate{value.weight+w,value.path};candidate.path.push_back(v);
        auto old=next.find(successor);
        if(old==next.end())next.emplace(successor,std::move(candidate));
        else if(candidate.weight<old->second.weight||(candidate.weight==old->second.weight&&candidate.path<old->second.path))old->second=std::move(candidate);
      }
      while(!layer.empty()){
        auto node=layer.extract(layer.begin());auto inserted=dp_.insert(std::move(node));
        index(inserted.position->first,inserted.position->second);
      }
      layer=std::move(next);
    }
    for(auto edge:graph_.edges())put_rep({edge.destination,edge.source});
  }
  const IndexedStates& states() const{return dp_;}
  const DirectedWeightedGraph& graph()const{return graph_;}
  const ColorMap& colors()const{return colors_;}
  CycleAnswer best()const {if(ranking_.empty())return {};return {true,ranking_.begin()->first,ranking_.begin()->second};}
  double gap()const {if(ranking_.empty())return 0;if(ranking_.size()==1)return INFINITY;auto a=ranking_.begin(),b=std::next(a);return b->first-a->first;}
  const auto& ranking()const{return ranking_;}
  std::size_t witness_links()const{std::size_t n=0;for(auto&[e,s]:witnesses_)n+=s.size();return n;}
  void apply_single(const EdgeUpdate& update){apply_batch({update},{},true);}
  void apply_batch(const std::vector<EdgeUpdate>& input,const SchedulePolicy& policy={},bool incremental=false) {
    if(input.empty())return;
#ifdef TRADER_PROFILE
    DPMaintenancePhase dp_scope(metrics);
#endif
    Schedule schedule;
    {Phase timer(metrics.schedule_ms);
      if(incremental)schedule.coalesced_updates=coalesce_latest(input);
      else schedule=build_schedule(input,graph_.edges(),DependencyGraphMode::VertexInduced,policy);
    }
    WitnessStates invalid;
    std::map<DirectedEdge,EdgeUpdate> effective;
    // Complete the unspecified state-level apply with one shared frontier per
    // DAG/direction pass, not one global pass across all decomposed DAGs.
    std::vector<IndexedStates> pending(k_+1);
    auto enqueue=[&](const StateKey& key,StateValue value){
      if(!needed(key)&&!invalid.count(key))return;
      auto& layer=pending[cardinality(key.colors)];auto it=layer.find(key);
      if(it==layer.end())layer.emplace(key,std::move(value));
      else if(value.weight<it->second.weight||(value.weight==it->second.weight&&value.path<it->second.path))it->second=std::move(value);
    };
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
      for(auto [edge,u]:effective){
        const bool existed=graph_.has_edge(u.source,u.destination);
        if(u.erase)graph_.remove_edge(u.source,u.destination);else graph_.set_edge(u.source,u.destination,u.weight);
        dirty_closures_.insert({u.destination,u.source});
        // A newly present closing edge makes its terminal DP state necessary;
        // deleting it makes that state unnecessary. Shorter masks remain exact.
        if(existed==u.erase&&bit(u.source)!=bit(u.destination))invalid.insert({u.destination,u.source,full_});
      }
      // Keep old witnesses until their layer is finalized: unchanged repairs
      // retain their indexes and must not cause another propagation wave.
      for(auto key:invalid)enqueue(key,{INFINITY,{}});
    }
    WitnessStates forced;
    auto drain=[&](int first_direction){
    for(std::size_t level=2;level<=k_;++level){
      metrics.queue_peak=std::max(metrics.queue_peak,pending[level].size());
      for(auto& [key,candidate]:pending[level]){
        ++metrics.popped;const bool repair=invalid.count(key)!=0;
        std::optional<StateValue> best;
        {
          Phase timer(metrics.repair_ms);
          if(repair){
            ++metrics.repaired;
            // All smaller masks are already final for the atomic batch graph.
            if(needed(key))for(auto [v,w]:graph_.incoming(key.destination)){
              auto pre=dp_.find({key.source,v,key.colors^bit(key.destination)});if(pre==dp_.end())continue;
              StateValue value{pre->second.weight+w,pre->second.path};value.path.push_back(key.destination);
              if(!best||value.weight<best->weight||(value.weight==best->weight&&value.path<best->path))best=std::move(value);
            }
          }else best=std::move(candidate);
        }
        Phase timer(metrics.propagation_ms);
        auto old=dp_.find(key);
        const bool same=best&&old!=dp_.end()&&old->second.weight==best->weight&&old->second.path==best->path;
        const bool worse=!repair&&old!=dp_.end()&&(old->second.weight<best->weight||(old->second.weight==best->weight&&old->second.path<best->path));
        if(same||worse){
          if(repair&&same)++metrics.unchanged_repairs;
          if(!forced.count(key))continue;
          best=old->second;
        }
        if(!best){erase(key);++metrics.changed_states;continue;}
        // Repair may raise a label. Do not erase/reinsert an unchanged witness.
        if(!same&&!worse&&repair&&old!=dp_.end()){
          bool changed_path=old->second.path!=best->path;
          if(changed_path)unindex(key,old->second);
          old->second=*best;if(changed_path)index(key,*best);mark(key);
        }else if(!same&&!worse)offer(key,*best);
        if(!same&&!worse)++metrics.changed_states;
        if(level==k_)continue;
        auto extend=[&](VertexId v,double w,bool backward){
          if(key.colors&bit(v))return;
          StateKey next{backward?v:key.source,backward?key.destination:v,key.colors|bit(v)};
          StateValue value{best->weight+w,best->path};
          if(backward)value.path.insert(value.path.begin(),v);else value.path.push_back(v);
          enqueue(next,std::move(value));
        };
        if(level>2||first_direction>=0)for(auto [v,w]:graph_.outgoing(key.destination))extend(v,w,false);
        if(level>2||first_direction<=0)for(auto [v,w]:graph_.incoming(key.source))extend(v,w,true);
      }
      pending[level].clear();
    }
    };
    drain(0);invalid.clear();
    if(incremental){
      Phase timer(metrics.propagation_ms);std::vector<EdgeUpdate> seeds;
      for(auto [edge,u]:effective)seeds.push_back(u);
      if(!seeds.empty())propagate_priority(seeds);
    }else for(const Dag& dag:schedule.dags){
      for(int direction:{1,-1}){
        {
          Phase timer(metrics.propagation_ms);forced.clear();
          if(direction>0)++metrics.dag_forward_passes;else ++metrics.dag_backward_passes;
          for(auto id:ready_edges(dag,schedule.dependency_edges,direction<0,policy.topological_ties)){
            auto e=schedule.dependency_edges.at(id);
            if(direction>0)++metrics.forward_edges;else ++metrics.backward_edges;
            auto update=effective.find(e);if(update==effective.end()||update->second.erase||bit(e.source)==bit(e.destination))continue;
            StateKey key{e.source,e.destination,bit(e.source)|bit(e.destination)};
            forced.insert(key);enqueue(key,{update->second.weight,{e.source,e.destination}});
          }
        }
        drain(direction);
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
      ++engine_.metrics.eg_changed_arrivals;
      bool on=false;for(std::size_t i=1;i<anchor_.cycle.size();++i)on|=anchor_.cycle[i-1]==u.source&&anchor_.cycle[i]==u.destination;
      const bool same=engine_.colors().at(u.source)==engine_.colors().at(u.destination);
      if(!same&&old&&!u.erase)adverse_+=on?std::max(0.0,u.weight-*old):std::max(0.0,*old-u.weight);
      immediate=!same&&(!old||!anchor_.exists||(u.erase&&on)||adverse_>gap_);
      if(immediate){
        ++engine_.metrics.eg_immediate;
        if(!old)++engine_.metrics.eg_new_triggers;
        else if(!anchor_.exists)++engine_.metrics.eg_no_anchor_triggers;
        else if(u.erase&&on)++engine_.metrics.eg_deleted_best_triggers;
        else ++engine_.metrics.eg_gap_triggers;
      }
      pending_.push_back(u);if(u.erase)live_.remove_edge(u.source,u.destination);else live_.set_edge(u.source,u.destination,u.weight);
      if(!immediate)++engine_.metrics.deferred;
    }
    if(immediate)flush(false);
  }
  void flush(bool eof=true){if(pending_.empty())return;
    if(eof)++engine_.metrics.eg_eof_flushes;
    engine_.metrics.eg_grouped_updates+=pending_.size();
    engine_.metrics.eg_group_max=std::max(engine_.metrics.eg_group_max,pending_.size());
    ++engine_.metrics.eg_group_sizes[pending_.size()];
    engine_.apply_batch(pending_);pending_.clear();anchor_=engine_.best();gap_=engine_.gap();adverse_=0;
  }
  CycleAnswer answer()const {auto a=anchor_;if(!a.exists)return a;a.weight=0;
    for(std::size_t i=1;i<a.cycle.size();++i){auto w=live_.edge_weight(a.cycle[i-1],a.cycle[i]);if(!w)throw std::logic_error("invalid deferred witness");a.weight+=*w;}return a;}
  const DirectedWeightedGraph& live()const{return live_;}
};
}
