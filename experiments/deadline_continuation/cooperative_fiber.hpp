#pragma once
// Windows-only execution experiment: preserve the original C++ stack at
// explicit checkpoints. No worker thread and no maintenance after return.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <chrono>
#include <cstdint>
#include <exception>
#include <functional>
#include <stdexcept>

namespace deadline_experiment {
class FiberThreadScope {
    bool converted_ = false;
public:
    FiberThreadScope() {
        if (!IsThreadAFiber()) {
            if (!ConvertThreadToFiber(nullptr)) throw std::runtime_error("ConvertThreadToFiber failed");
            converted_ = true;
        }
    }
    ~FiberThreadScope() { if (converted_) ConvertFiberToThread(); }
    FiberThreadScope(const FiberThreadScope&) = delete;
    FiberThreadScope& operator=(const FiberThreadScope&) = delete;
};

class CooperativeFiber {
public:
    using Clock = std::chrono::steady_clock;
private:
    struct Cancelled {};
    void* fiber_ = nullptr;
    void* caller_ = nullptr;
    DWORD owner_ = GetCurrentThreadId();
    std::function<void()> job_;
    std::exception_ptr error_;
    bool done_ = true, cancel_ = false;
    std::uint64_t remaining_ = 0, steps_ = 0;
    Clock::time_point deadline_;
    inline static thread_local CooperativeFiber* active_ = nullptr;

    static void WINAPI entry(void* ptr) {
        auto& self = *static_cast<CooperativeFiber*>(ptr);
        for (;;) {
            try { self.check(); self.job_(); }
            catch (const Cancelled&) {}
            catch (...) { self.error_ = std::current_exception(); }
            self.job_ = {};
            self.done_ = true;
            SwitchToFiber(self.caller_);
        }
    }
    void check() {
        if (cancel_) throw Cancelled{};
        if (remaining_ == 0 || Clock::now() >= deadline_) {
            SwitchToFiber(caller_);
            if (cancel_) throw Cancelled{};
        }
        --remaining_;
        ++steps_;
    }
    void switch_in() {
        if (GetCurrentThreadId() != owner_ || !IsThreadAFiber() || active_)
            throw std::logic_error("fiber must resume on its owning caller thread");
        caller_ = GetCurrentFiber();
        active_ = this;
        SwitchToFiber(fiber_);
        active_ = nullptr;
    }
public:
    CooperativeFiber() {
        if (!IsThreadAFiber()) throw std::logic_error("FiberThreadScope required");
        fiber_ = CreateFiberEx(0, 0, FIBER_FLAG_FLOAT_SWITCH, entry, this);
        if (!fiber_) throw std::runtime_error("CreateFiberEx failed");
    }
    ~CooperativeFiber() {
        // Unwind suspended C++ locals instead of deleting a live stack.
        // Cancellation abandons the private partially-mutated engine; it must
        // not subsequently be used as a committed engine.
        if (!done_) { cancel_ = true; switch_in(); }
        DeleteFiber(fiber_);
    }
    CooperativeFiber(const CooperativeFiber&) = delete;
    CooperativeFiber& operator=(const CooperativeFiber&) = delete;
    void start(std::function<void()> job) {
        if (!done_) throw std::logic_error("unfinished fiber job");
        job_ = std::move(job); error_ = nullptr; cancel_ = false; done_ = false;
    }
    bool advance_until(Clock::time_point deadline, std::uint64_t max_steps = UINT64_MAX) {
        if (done_) return true;
        if (max_steps == 0 || Clock::now() >= deadline) return false;
        deadline_ = deadline; remaining_ = max_steps;
        switch_in();
        if (error_) std::rethrow_exception(error_);
        return done_;
    }
    bool done() const { return done_; }
    std::uint64_t steps() const { return steps_; }
    static void checkpoint() { if (active_) active_->check(); }
};
inline void trader_checkpoint() { CooperativeFiber::checkpoint(); }
}
