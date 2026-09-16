#pragma once
// Experimental service around the checkpoint-injected, frozen TRADER core.
// Common-apply completion is NOT an EG batch flush or a current-DP guarantee.
#include "cooperative_fiber.hpp"
#include "cycle_detector.h"
#include <cmath>
#include <deque>
#include <map>
#include <memory>
#include <optional>
#include <sstream>

namespace deadline_experiment {
class TraderServiceContinuation {
public:
    struct Candidate {
        double weight;
        std::vector<uint32_t> path;
        size_t coloring;
        uint64_t source_version,graph_version;
    };
    using Clock=CooperativeFiber::Clock;
private:
    struct Cached {std::vector<uint32_t> path;uint64_t version=0;bool colorful=false;};
    unsigned k_,vertex_limit_;
    std::vector<std::unique_ptr<KCycleColorCoding>> engines_;
    std::vector<Cached> cached_;
    std::map<std::pair<uint32_t,uint32_t>,double> live_;
    std::deque<std::string> pending_;
    uint64_t accepted_=0,completed_=0;
    // Last: cancellation must unwind the active job before any captured
    // engines/cache/queue are destroyed.
    CooperativeFiber fiber_;

    void cache(size_t trial,uint64_t version) {
        const auto& e=*engines_[trial];
        auto path=e.common_path();bool colorful=path.size()==size_t(k_+1);
        unsigned mask=0;
        if(colorful)for(unsigned i=0;i<k_;++i) {
            auto it=e.common_colors().find(path[i]);
            if(it==e.common_colors().end()||it->second<0||unsigned(it->second)>=k_){colorful=false;break;}
            const unsigned bit=1u<<it->second;
            if(mask&bit){colorful=false;break;}mask|=bit;
        }
        cached_[trial]={std::move(path),version,colorful};
    }
    void start_front() {
        const auto line=pending_.front();const auto version=completed_+1;
        fiber_.start([this,line,version] {
            for(size_t t=0;t<engines_.size();++t) {
                trader_checkpoint();
                engines_[t]->common_apply(line);
                // No checkpoint while publishing this complete cached record.
                cache(t,version);
            }
            ++completed_;pending_.pop_front();
        });
    }
public:
    TraderServiceContinuation(DirectedGraph graph,unsigned k,const std::vector<unsigned>& seeds)
        :k_(k),vertex_limit_(graph.max_vertex_id_) {
        if(k<2||k>10||seeds.empty())throw std::invalid_argument("invalid service dimensions");
        for(auto u:graph.vertices()) {
            const auto [neighbors,weights,degree]=graph.get_out_neighbors(u);
            for(uint32_t i=0;i<degree;++i)live_[{u,neighbors[i]}]=weights[i];
        }
        for(auto seed:seeds) {
            auto e=std::make_unique<KCycleColorCoding>(graph,k,1,10,seed,1,true);
            e->common_start(seed);engines_.push_back(std::move(e));cached_.push_back({});
            cache(engines_.size()-1,0);
        }
    }
    // Parse/accept cost belongs inside the eventual caller's complete window.
    // Support only the frozen common-input S/N contract, never invent D semantics.
    void accept(const std::string& line) {
        std::istringstream input(line);int64_t u,v;std::string token,extra;
        if(!(input>>u>>v>>token)||(input>>extra)||u<0||v<0||u>=vertex_limit_||v>=vertex_limit_)
            throw std::invalid_argument("malformed or unsupported update");
        double weight=0;
        if(token!="N") {
            size_t used=0;weight=std::stod(token,&used);
            if(used!=token.size()||!std::isfinite(weight)||weight>1000)
                throw std::invalid_argument("update outside normalized contract");
        }
        if(token!="N")live_[{uint32_t(u),uint32_t(v)}]=weight;
        pending_.push_back(line);++accepted_;
    }
    uint64_t advance_until(Clock::time_point deadline,uint64_t budget=UINT64_MAX) {
        const auto before=fiber_.steps();
        while(!pending_.empty()&&fiber_.steps()-before<budget&&Clock::now()<deadline) {
            if(fiber_.done())start_front();
            if(!fiber_.advance_until(deadline,budget-(fiber_.steps()-before)))break;
        }
        return fiber_.steps()-before;
    }
    uint64_t advance_steps(uint64_t budget) {return advance_until(Clock::time_point::max(),budget);}
    std::optional<Candidate> current_candidate() const {
        std::optional<Candidate> best;
        for(size_t t=0;t<cached_.size();++t) {
            const auto& c=cached_[t];const auto& path=c.path;
            if(!c.colorful||path.size()!=size_t(k_+1)||path.front()!=path.back())continue;
            bool valid=true;double w=0;
            for(unsigned i=0;i<k_;++i) {
                for(unsigned j=0;j<i;++j)if(path[i]==path[j])valid=false;
                auto it=live_.find({path[i],path[i+1]});
                if(it==live_.end()||!std::isfinite(it->second)){valid=false;break;}w+=it->second;
            }
            if(valid&&std::isfinite(w)&&w<0&&(!best||w<best->weight))
                best=Candidate{w,path,t,c.version,accepted_};
        }
        return best;
    }
    uint64_t accepted() const {return accepted_;}
    uint64_t completed() const {return completed_;}
    uint64_t work_steps() const {return fiber_.steps();}
    size_t backlog() const {return pending_.size();}
    const KCycleColorCoding& inspect_completed(size_t t) const {
        if(!pending_.empty()||!fiber_.done())throw std::logic_error("partial engine cannot be inspected");
        return *engines_.at(t);
    }
};
}
