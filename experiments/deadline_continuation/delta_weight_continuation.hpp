#pragma once
// Experimental stage 1: existing finite-edge reweights only, not a 10 ms service.
// The production DeltaEngine is unchanged. No worker runs between resume calls.
#include "../../delta_terminal/native/delta_engine.hpp"
#include <stdexcept>

namespace deadline_experiment {
class DeltaWeightContinuation {
    enum class Phase { idle, mark, choose, scan, commit, forward };
    delta::DeltaEngine engine_;
    Phase phase_=Phase::idle;
    int edge_=-1,level_=2,state_=-1,parent_=-1;
    std::size_t mark_pos_=0,row_pos_=0,arc_pos_=0;
    double best_=delta::INF;
    std::uint64_t completed_=0;

    void step() {
        switch(phase_) {
        case Phase::idle: return;
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
        // Reject unsupported topology changes before mutating any engine state.
        if(e.op!='S'||!std::isfinite(e.w)||e.u<0||e.v<0||
           e.u>=int(engine_.out.size())||e.v>=int(engine_.out.size()))
            throw std::invalid_argument("stage 1 accepts only existing finite-edge reweights or N");
        auto it=engine_.out[e.u].find(e.v);
        if(it==engine_.out[e.u].end()||!std::isfinite(engine_.edges[it->second].w))
            throw std::invalid_argument("topology continuation not implemented");
        edge_=it->second;
        if(engine_.edges[edge_].w==e.w) {++completed_;return;}
        engine_.edges[edge_].w=e.w;++engine_.changes;
        mark_pos_=row_pos_=arc_pos_=0;level_=2;phase_=Phase::mark;
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
