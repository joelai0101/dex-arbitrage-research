#pragma once
#include "trader_service_continuation.hpp"

namespace deadline_experiment {
struct TraderWindowPolicy {
    std::chrono::nanoseconds budget=std::chrono::milliseconds(10);
    std::chrono::nanoseconds reserve=std::chrono::milliseconds(1);
};
struct TraderWindowResponse {
    std::string line;
    std::optional<TraderServiceContinuation::Candidate> candidate;
    TraderServiceContinuation::Clock::time_point read,accepted,maintained,validated;
    uint64_t accepted_version,completed_version,steps_before,steps_after;
    size_t backlog;
};
// Caller clocks before invocation and immediately after the complete response.
// No background thread or maintenance after returning. EG completion is not flush.
inline TraderWindowResponse serve_trader_window(TraderServiceContinuation& service,
    std::istream& input,TraderServiceContinuation::Clock::time_point start,TraderWindowPolicy policy={}) {
    if(policy.budget.count()<0||policy.reserve.count()<0||policy.reserve>policy.budget)
        throw std::invalid_argument("invalid window policy");
    TraderWindowResponse out{};out.steps_before=service.work_steps();
    if(!std::getline(input,out.line))throw std::runtime_error("missing input row");
    out.read=TraderServiceContinuation::Clock::now();
    service.accept(out.line);out.accepted=TraderServiceContinuation::Clock::now();
    service.advance_until(start+policy.budget-policy.reserve);
    out.maintained=TraderServiceContinuation::Clock::now();
    out.candidate=service.current_candidate();out.validated=TraderServiceContinuation::Clock::now();
    out.accepted_version=service.accepted();out.completed_version=service.completed();
    out.steps_after=service.work_steps();out.backlog=service.backlog();return out;
}
}
