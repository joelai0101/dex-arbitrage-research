#include "delta_window.hpp"
#include <cassert>
#include <iostream>
using namespace delta;
using namespace deadline_experiment;
int main() {
    std::vector<std::vector<int>> colors(80,{0,1,2,0});
    std::vector<Update> initial{{0,1,-1,'S'},{1,2,-1,'S'},{2,0,-1,'S'}};
    DeltaServiceContinuation service(colors,3,initial);
    auto initial_steps=service.work_steps();
    std::istringstream input("0 1 D\n0 1 -2\n0 0 N\n");
    WindowPolicy expired{std::chrono::nanoseconds(0),std::chrono::nanoseconds(0)};
    auto start=Clock::now();auto deleted=serve_window(service,input,start,expired);auto returned=Clock::now();
    assert(start<=deleted.parsed&&deleted.parsed<=deleted.accepted&&deleted.accepted<=deleted.maintained);
    assert(deleted.maintained<=deleted.validated&&deleted.validated<=returned);
    assert(!deleted.candidate&&deleted.accepted_version==1&&deleted.committed_version==0&&deleted.backlog==1);
    assert(service.work_steps()==initial_steps&&returned>start);
    start=Clock::now();auto restored=serve_window(service,input,start,expired);returned=Clock::now();
    assert(restored.candidate&&restored.candidate->weight==-4);
    assert(restored.candidate->source_version==0&&restored.candidate->graph_version==2);
    assert(restored.backlog==2&&restored.steps_after==restored.steps_before);
    // A past start also spends no maintenance, even with the normal policy.
    auto noop=serve_window(service,input,Clock::now()-std::chrono::seconds(1));
    assert(noop.accepted_version==3&&noop.backlog==3&&service.work_steps()==initial_steps);
    for(const char* bad:{"0 1 inf","0 1 1junk","0 1 2 extra","bad"}) {
        std::istringstream invalid(bad);bool rejected=false;
        try{serve_window(service,invalid,Clock::now());}catch(const std::exception&){rejected=true;}
        assert(rejected&&service.accepted()==3&&service.work_steps()==initial_steps);
    }
    // Complete the queued operations only in this explicit correctness test.
    while(service.backlog())service.advance_steps(13);
    assert(service.committed()==3&&service.current_candidate()->weight==-4);
    std::cout<<"PASS complete-response timestamps, zero/past budget freeze, FIFO backlog, deletion/revalidation, parse rejection. NOT a timing benchmark.\n";
}
