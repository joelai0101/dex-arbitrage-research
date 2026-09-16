#pragma once
// Experimental continuation on a fixed, precolored vertex universe; not a 10 ms service.
// The production DeltaEngine is unchanged. No worker runs between resume calls.
#include "../../delta_terminal/native/delta_engine.hpp"
#include <stdexcept>

namespace deadline_experiment {
class DeltaWeightContinuation {
    enum class Phase { idle, activate, mark, choose, scan, commit, forward };
    // Mirrors recursive connect/ensure order without leaving work on the C++ stack.
    struct ConnectFrame {
        int from,edge,to=-1,stage=0;
        std::size_t duplicate_pos=0;
        std::map<int,int>::const_iterator next;
    };
    delta::DeltaEngine engine_;
    Phase phase_=Phase::idle;
    int edge_=-1,level_=2,state_=-1,parent_=-1;
    std::size_t mark_pos_=0,row_pos_=0,arc_pos_=0;
    double best_=delta::INF;
    std::uint64_t completed_=0;
    std::vector<ConnectFrame> connect_stack_;
    std::size_t endpoint_pos_=0,endpoint_count_=0;

    void topology_step() {
        if(connect_stack_.empty()) {
            if(endpoint_pos_==endpoint_count_) {phase_=Phase::mark;return;}
            const int u=engine_.edges[edge_].u;
            connect_stack_.push_back({engine_.endpoint[u][endpoint_pos_++],edge_});return;
        }
        auto& f=connect_stack_.back();
        if(f.stage==0) {
            if(f.duplicate_pos<engine_.states[f.from].outgoing.size()) {
                int a=engine_.states[f.from].outgoing[f.duplicate_pos++];
                if(engine_.arcs[a].edge==f.edge)connect_stack_.pop_back();
                return;
            }
            f.stage=1;return;
        }
        if(f.stage==1) {
            const auto& source=engine_.states[f.from];
            const int root=source.root,used=source.mask,u=source.u;
            const int v=engine_.edges[f.edge].v;
            if(used==engine_.full) {
                if(v!=root) {connect_stack_.pop_back();return;}
                f.to=source.terminal;
                if(f.to<0) {
                    f.to=int(engine_.states.size());
                    engine_.states.push_back({root,u,engine_.full,engine_.k+1});
                    engine_.states[f.from].terminal=f.to;
                }
                f.stage=3;return;
            }
            if(v<root||(used&(1<<engine_.color[v]))) {connect_stack_.pop_back();return;}
            const int mask=used|(1<<engine_.color[v]);
            f.to=engine_.lookup[root].find(v,mask);
            if(f.to>=0) {f.stage=3;return;}
            f.to=int(engine_.states.size());
            engine_.states.push_back({root,v,mask,__builtin_popcount(unsigned(mask))});
            engine_.lookup[root].add(v,mask,f.to);engine_.endpoint[v].push_back(f.to);
            if(mask==(1<<engine_.color[root])&&v==root)engine_.states[f.to].w=0;
            f.next=engine_.out[v].begin();f.stage=2;return;
        }
        if(f.stage==2) {
            const int u=engine_.states[f.to].u;
            if(f.next==engine_.out[u].end()) {f.stage=3;return;}
            const int eid=(f.next++)->second;
            if(std::isfinite(engine_.edges[eid].w))connect_stack_.push_back({f.to,eid});
            return;
        }
        const int from=f.from,to=f.to,eid=f.edge,aid=int(engine_.arcs.size());
        engine_.arcs.push_back({from,to,eid});
        engine_.states[from].outgoing.push_back(aid);engine_.states[to].incoming.push_back(aid);
        engine_.edges[eid].arcs.push_back(aid);engine_.mark(to);
        connect_stack_.pop_back();
    }

    void step() {
        switch(phase_) {
        case Phase::idle: return;
        case Phase::activate: topology_step();return;
        case Phase::mark:
            if(mark_pos_<engine_.edges[edge_].arcs.size()) {
                engine_.consider(engine_.edges[edge_].arcs[mark_pos_++]);return;
            }
            phase_=Phase::choose;return;
        case Phase::choose:
            if(level_>engine_.k+1) {
                phase_=Phase::idle;++completed_;return;
            }
            if(row_pos_==engine_.dirty[level_].size()) {
                engine_.dirty[level_].clear();++level_;row_pos_=0;return;
            }
            state_=engine_.dirty[level_][row_pos_];
            engine_.states[state_].queued=false;++engine_.recomputed;
            arc_pos_=0;best_=delta::INF;parent_=-1;phase_=Phase::scan;return;
        case Phase::scan:
            if(arc_pos_<engine_.states[state_].incoming.size()) {
                int aid=engine_.states[state_].incoming[arc_pos_++];
                const auto a=engine_.arcs[aid];++engine_.probes;
                double w=engine_.states[a.from].w+engine_.edges[a.edge].w;
                if(w<best_ || (std::isfinite(w)&&w==best_&&(parent_<0||aid<parent_))) {
                    best_=w;parent_=aid;
                }
                return;
            }
            phase_=Phase::commit;return;
        case Phase::commit: {
            auto& s=engine_.states[state_];double old=s.w;s.parent=parent_;
            if(old==best_) {++row_pos_;phase_=Phase::choose;return;}
            ++engine_.value_changed;s.w=best_;
            if(level_==engine_.k+1) {
                if(std::isfinite(old))engine_.candidates.erase({old,state_});
                if(std::isfinite(best_))engine_.candidates.insert({best_,state_});
                ++row_pos_;phase_=Phase::choose;
            } else {arc_pos_=0;phase_=Phase::forward;}
            return;
        }
        case Phase::forward:
            if(arc_pos_<engine_.states[state_].outgoing.size()) {
                engine_.consider(engine_.states[state_].outgoing[arc_pos_++]);return;
            }
            ++row_pos_;phase_=Phase::choose;return;
        }
    }
public:
    DeltaWeightContinuation(std::vector<int> colors,int k,const std::vector<delta::Update>& initial)
        :engine_(std::move(colors),k) {engine_.initialize(initial);}
    bool busy() const {return phase_!=Phase::idle;}
    std::uint64_t completed() const {return completed_;}
    const delta::DeltaEngine& inspect() const {return engine_;}
    void begin(const delta::Update& e) {
        if(busy())throw std::logic_error("resume pending update before accepting another into this engine");
        if(e.op=='N') {++completed_;return;}
        // The graph's complete vertex/color universe must be provided at construction.
        if((e.op!='S'&&e.op!='D')||(e.op=='S'&&!std::isfinite(e.w))||e.u<0||e.v<0||
           e.u>=int(engine_.out.size())||e.v>=int(engine_.out.size()))
            throw std::invalid_argument("expected S with finite weight, D or N within fixed vertex universe");
        auto it=engine_.out[e.u].find(e.v);
        const double old=it==engine_.out[e.u].end()?delta::INF:engine_.edges[it->second].w;
        const double fresh=e.op=='D'?delta::INF:e.w;
        if(old==fresh) {++completed_;return;}
        ++engine_.changes;
        if(std::isfinite(old)!=std::isfinite(fresh))++engine_.topology;
        auto applied=e;applied.w=fresh;edge_=engine_.set_edge(applied);
        mark_pos_=row_pos_=arc_pos_=0;level_=2;phase_=Phase::mark;
        if(!std::isfinite(old)&&std::isfinite(fresh)) {
            endpoint_pos_=0;endpoint_count_=engine_.endpoint[e.u].size();phase_=Phase::activate;
        }
    }
    std::size_t resume_steps(std::size_t max_steps) {
        std::size_t done=0;
        while(busy()&&done<max_steps) {step();++done;}
        return done;
    }
    // Caller charges begin, validation and actual return as well. This only
    // bounds this maintenance call cooperatively; an indivisible step may overshoot.
    std::size_t resume_until(delta::Clock::time_point deadline) {
        std::size_t done=0;
        while(busy()&&delta::Clock::now()<deadline) {step();++done;}
        return done;
    }
    std::pair<double,std::vector<int>> completed_answer() {
        if(busy())throw std::logic_error("partial engine is not a publishable snapshot");
        return engine_.query();
    }
};
}
