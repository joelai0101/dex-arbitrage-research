#pragma once
#include "delta_service_continuation.hpp"
#include <istream>
#include <sstream>

namespace deadline_experiment {
struct WindowPolicy {
    std::chrono::nanoseconds budget=std::chrono::milliseconds(10);
    std::chrono::nanoseconds reserve=std::chrono::milliseconds(1);
};
struct WindowResponse {
    delta::Update update;
    std::optional<DeltaServiceContinuation::Candidate> candidate;
    delta::Clock::time_point parsed,accepted,maintained,validated;
    std::uint64_t accepted_version,committed_version,steps_before,steps_after;
    size_t backlog;
};
// Common normalized input: u v finite-weight, u v N, or u v D.
inline delta::Update parse_update(const std::string& line) {
    std::istringstream row(line);int u,v;std::string token,extra;
    if(!(row>>u>>v>>token)||(row>>extra))throw std::invalid_argument("malformed update");
    if(token=="N"||token=="D")return {u,v,0,token[0]};
    size_t consumed=0;double w=std::stod(token,&consumed);
    if(consumed!=token.size()||!std::isfinite(w))throw std::invalid_argument("nonfinite or malformed weight");
    return {u,v,w,'S'};
}
// Caller takes start BEFORE this call and actual_return AFTER receiving the
// complete response. No clock is stopped inside the service. Diagnostic logging
// is external; response construction/copy and input read/parse are charged.
inline WindowResponse serve_window(DeltaServiceContinuation& service,std::istream& input,
                                  delta::Clock::time_point start,WindowPolicy policy={}) {
    if(policy.budget.count()<0||policy.reserve.count()<0||policy.reserve>policy.budget)
        throw std::invalid_argument("invalid window policy");
    WindowResponse out{};out.steps_before=service.work_steps();
    std::string line;
    if(!std::getline(input,line))throw std::runtime_error("missing input row");
    out.update=parse_update(line);out.parsed=delta::Clock::now();
    service.accept(out.update);out.accepted=delta::Clock::now();
    service.advance_until(start+policy.budget-policy.reserve);
    out.maintained=delta::Clock::now();
    out.candidate=service.current_candidate();out.validated=delta::Clock::now();
    out.accepted_version=service.accepted();out.committed_version=service.committed();
    out.steps_after=service.work_steps();out.backlog=service.backlog();
    return out;
}
}
