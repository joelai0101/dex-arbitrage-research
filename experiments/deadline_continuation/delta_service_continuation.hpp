#pragma once
// Experimental FIFO service primitives. The caller must time the complete
// accept/maintenance/validation/return window; this is not a formal deadline driver.
#include "delta_weight_continuation.hpp"
#include <deque>
#include <memory>
#include <optional>

namespace deadline_experiment {
class DeltaServiceContinuation {
public:
    struct Candidate {
        double weight;
        std::vector<int> path;
        size_t coloring;
        std::uint64_t source_version,graph_version;
    };
private:
    struct Cached {std::vector<int> path;std::uint64_t version=0;};
    int k_;size_t vertices_;
    std::vector<std::unique_ptr<DeltaWeightContinuation>> engines_;
    std::vector<Cached> cached_;
    std::map<std::pair<int,int>,double> live_;
    std::deque<delta::Update> pending_;
    std::uint64_t accepted_=0,committed_=0,steps_=0;
    size_t trial_=0;bool started_=false;

    bool step() {
        if(pending_.empty())return false;
        auto& e=*engines_[trial_];
        if(!started_) {e.begin(pending_.front());started_=true;}
        else if(e.busy())e.resume_steps(1);
        else {
            auto answer=e.completed_answer();cached_[trial_]={std::move(answer.second),committed_+1};
            started_=false;
            if(++trial_==engines_.size()) {
                trial_=0;++committed_;pending_.pop_front();
            }
        }
        ++steps_;return true;
    }
public:
    DeltaServiceContinuation(const std::vector<std::vector<int>>& colors,int k,
                             const std::vector<delta::Update>& initial)
        :k_(k),vertices_(colors.empty()?0:colors.front().size()) {
        if(!vertices_||k<2||k>10)throw std::invalid_argument("invalid service dimensions");
        for(const auto& row:colors) {
            if(row.size()!=vertices_)throw std::invalid_argument("color row size mismatch");
            for(int c:row)if(c<0||c>=k_)throw std::invalid_argument("invalid color");
        }
        for(const auto& e:initial) {
            if(e.op!='S'||e.u<0||e.v<0||size_t(e.u)>=vertices_||size_t(e.v)>=vertices_||!std::isfinite(e.w))
                throw std::invalid_argument("invalid initial edge");
            live_[{e.u,e.v}]=e.w;
        }
        for(const auto& row:colors) {
            auto engine=std::make_unique<DeltaWeightContinuation>(row,k,initial,true);
            auto answer=engine->completed_answer();cached_.push_back({std::move(answer.second),0});
            engines_.push_back(std::move(engine));
        }
    }
    void accept(const delta::Update& e) {
        if(e.op!='N'&&((e.op!='S'&&e.op!='D')||e.u<0||e.v<0||size_t(e.u)>=vertices_||size_t(e.v)>=vertices_||
                     (e.op=='S'&&!std::isfinite(e.w))))throw std::invalid_argument("invalid update");
        if(e.op=='S')live_[{e.u,e.v}]=e.w;
        else if(e.op=='D')live_.erase({e.u,e.v});
        pending_.push_back(e);++accepted_;
    }
    size_t advance_steps(size_t budget) {
        size_t done=0;while(done<budget&&step())++done;return done;
    }
    size_t advance_until(delta::Clock::time_point deadline) {
        size_t done=0;while(delta::Clock::now()<deadline&&step())++done;return done;
    }
    // Revalidate only cached, fully recovered candidates. Never traverse partial
    // DP parents or run a search/oracle here. Cost must be charged by the caller.
    std::optional<Candidate> current_candidate() const {
        std::optional<Candidate> best;
        for(size_t t=0;t<cached_.size();++t) {
            const auto& c=cached_[t];const auto& path=c.path;
            if(path.size()!=size_t(k_+1)||path.front()!=path.back())continue;
            double w=0;bool valid=true;
            for(int i=0;i<k_;++i) {
                for(int j=0;j<i;++j)if(path[i]==path[j])valid=false;
                auto it=live_.find({path[i],path[i+1]});
                if(it==live_.end()||!std::isfinite(it->second)){valid=false;break;}
                w+=it->second;
            }
            if(valid&&std::isfinite(w)&&w<0&&(!best||w<best->weight))
                best=Candidate{w,path,t,c.version,accepted_};
        }
        return best;
    }
    std::uint64_t accepted() const {return accepted_;}
    std::uint64_t committed() const {return committed_;}
    std::uint64_t work_steps() const {return steps_;}
    size_t backlog() const {return pending_.size();}
    const delta::DeltaEngine& inspect(size_t trial) const {return engines_.at(trial)->inspect();}
};
}
