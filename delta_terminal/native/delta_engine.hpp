#pragma once
// Extracted unchanged from the validated delta_state_benchmark.cpp (2026-09-11).
// CLI, RPC and serialization deliberately live outside the recurrence.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <limits>
#include <map>
#include <set>
#include <unordered_map>
#include <utility>
#include <vector>

namespace delta {
using Clock = std::chrono::steady_clock;
constexpr double INF = std::numeric_limits<double>::infinity();
using Key = uint64_t;
inline Key key(int v, int mask) { return (uint64_t(uint32_t(mask)) << 32) | uint32_t(v); }
inline double ms(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::milli>(b-a).count();
}
struct Update { int u, v; double w; char op; };
struct Lookup {
#ifdef DELTA_CCSS
    using Small=absl::InlinedVector<std::pair<int,int>,1>;
    std::unordered_map<int,Small> rows;
    int find(int u,int mask) const {
        auto p=rows.find(u);if(p==rows.end())return -1;
        for(auto [m,id]:p->second)if(m==mask)return id;return -1;
    }
    void add(int u,int mask,int id){rows[u].push_back({mask,id});}
#else
    std::unordered_map<Key,int> rows;
    int find(int u,int mask) const {auto p=rows.find(key(u,mask));return p==rows.end()?-1:p->second;}
    void add(int u,int mask,int id){rows.emplace(key(u,mask),id);}
#endif
};
struct DeltaState {
    int root,u,mask,level,parent=-1,terminal=-1;
    double w=INF;
    bool queued=false;
    std::vector<int> incoming,outgoing;
};
struct DeltaEdge {int u,v;double w;std::vector<int> arcs;};
struct DeltaArc {int from,to,edge;};
class DeltaEngine {
public:
    int k,full;
    std::vector<int> color;
    std::vector<Lookup> lookup;
    std::vector<std::map<int,int>> out;
    std::vector<std::vector<int>> endpoint,dirty;
    std::vector<DeltaState> states;
    std::vector<DeltaEdge> edges;
    std::vector<DeltaArc> arcs;
    std::set<std::pair<double,int>> candidates;
    uint64_t recomputed=0,value_changed=0,probes=0,gate_skips=0,changes=0,topology=0;
    double update_ms=0,query_ms=0;
    explicit DeltaEngine(std::vector<int> c,int hops):k(hops),full((1<<k)-1),color(std::move(c)),
        lookup(color.size()),out(color.size()),endpoint(color.size()),dirty(k+2){}
    void mark(int id){if(!states[id].queued){states[id].queued=true;dirty[states[id].level].push_back(id);}}
    void consider(int aid){
        auto a=arcs[aid];auto& to=states[a.to];double w=states[a.from].w+edges[a.edge].w;
#ifdef DELTA_UNGATED
        mark(a.to);
#else
        if(to.parent==aid || w<to.w || (std::isfinite(w)&&w==to.w&&(to.parent<0||aid<to.parent)))mark(a.to);
        else ++gate_skips;
#endif
    }
    void connect(int from,int eid){
        // Topology-only duplicate check, including reactivated historical edges.
        for(int a:states[from].outgoing)if(arcs[a].edge==eid)return;
        auto edge=edges[eid];int root=states[from].root,used=states[from].mask,u=states[from].u,to=-1;
        if(used==full){
            if(edge.v!=root)return;
            to=states[from].terminal;
            if(to<0){to=int(states.size());states.push_back({root,u,full,k+1});states[from].terminal=to;}
        }else{
            if(edge.v<root || (used&(1<<color[edge.v])))return;
            to=ensure(root,edge.v,used|(1<<color[edge.v]));
        }
        int aid=int(arcs.size());arcs.push_back({from,to,eid});
        states[from].outgoing.push_back(aid);states[to].incoming.push_back(aid);edges[eid].arcs.push_back(aid);mark(to);
    }
    int ensure(int root,int u,int used){
        int found=lookup[root].find(u,used);if(found>=0)return found;
        int id=int(states.size());states.push_back({root,u,used,__builtin_popcount(unsigned(used))});
        lookup[root].add(u,used,id);endpoint[u].push_back(id);
        if(used==(1<<color[root])&&u==root)states[id].w=0;
        // Only edges already observed and currently active are expanded.
        for(auto [v,eid]:out[u])if(std::isfinite(edges[eid].w))connect(id,eid);
        return id;
    }
    int set_edge(Update e){
        auto p=out[e.u].find(e.v);int id;
        if(p==out[e.u].end()){
            id=int(edges.size());edges.push_back({e.u,e.v,e.w,{}});out[e.u][e.v]=id;
        }else{id=p->second;edges[id].w=e.w;}
        return id;
    }
    void propagate(){
#ifdef DELTA_FULL
        // Same compiled dependency graph and candidate tree; only work selection differs.
        for(int id=0;id<int(states.size());++id)if(states[id].level>1)mark(id);
#endif
        for(int level=2;level<=k+1;++level){
            for(int id:dirty[level]){
                auto& s=states[id];s.queued=false;++recomputed;
                double best=INF;int parent=-1;
                for(int aid:s.incoming){++probes;auto a=arcs[aid];double w=states[a.from].w+edges[a.edge].w;
                    if(w<best || (std::isfinite(w)&&w==best&&(parent<0||aid<parent))){best=w;parent=aid;}}
                double old=s.w;s.parent=parent;
                if(old==best)continue;
                ++value_changed;s.w=best;
                if(level==k+1){
                    if(std::isfinite(old))candidates.erase({old,id});
                    if(std::isfinite(best))candidates.insert({best,id});
                }else for(int aid:s.outgoing)consider(aid);
            }
            dirty[level].clear();
        }
    }
    void initialize(const std::vector<Update>& initial){
        for(auto e:initial)if(e.op=='S')set_edge(e);
        for(int s=0;s<int(color.size());++s)ensure(s,s,1<<color[s]);
        propagate();recomputed=value_changed=probes=gate_skips=0;
    }
    void apply(const std::vector<Update>& updates,size_t begin,size_t end){
        auto t=Clock::now();std::map<std::pair<int,int>,Update> last;
        for(size_t i=begin;i<end;++i)if(updates[i].op!='N')last[{updates[i].u,updates[i].v}]=updates[i];
        std::vector<int> changed,activated;
        for(auto [pair,e]:last){
            auto p=out[e.u].find(e.v);double old=p==out[e.u].end()?INF:edges[p->second].w;
            double fresh=e.op=='D'?INF:e.w;if(old==fresh)continue;
            ++changes;if(std::isfinite(old)!=std::isfinite(fresh))++topology;
            e.w=fresh;int id=set_edge(e);changed.push_back(id);
            if(!std::isfinite(old)&&std::isfinite(fresh))activated.push_back(id);
        }
        if(changed.empty()){update_ms+=ms(t,Clock::now());return;}
        // All final weights are installed before marking or evaluating states.
        for(int eid:activated){int u=edges[eid].u;size_t count=endpoint[u].size();
            for(size_t i=0;i<count;++i)connect(endpoint[u][i],eid);}
        for(int eid:changed)for(int aid:edges[eid].arcs)consider(aid);
        propagate();update_ms+=ms(t,Clock::now());
    }
    std::pair<double,std::vector<int>> query(){
        auto t=Clock::now();std::vector<int> path;double w=INF;
        if(!candidates.empty()){
            auto [weight,id]=*candidates.begin();w=weight;int root=states[id].root;
            id=arcs[states[id].parent].from;
            while(true){path.push_back(states[id].u);if(states[id].parent<0)break;id=arcs[states[id].parent].from;}
            std::reverse(path.begin(),path.end());path.push_back(root);
        }
        query_ms+=ms(t,Clock::now());return {w,path};
    }
};
} // namespace delta
