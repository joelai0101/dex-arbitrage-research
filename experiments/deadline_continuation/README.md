# Deadline continuation experiment (stage 1)

This is an experimental execution variant, not the official TRADER implementation
and not yet a validated 10 ms end-to-end service. Production files are unchanged.

`DeltaWeightContinuation` reuses the existing DELTA state representation and
recurrence, saving the incoming/outgoing arc cursor and propagation phase across
calls. It accepts existing finite-edge reweights and no-ops only. Insertions,
deletions, new vertices, multi-color scheduling, current-graph candidate validation,
backlog accounting and TRADER/GraphS continuations are not implemented yet.
Unsupported operations are rejected before mutation. Partial engine answers cannot
be published. No background worker runs after a resume call returns.

The deterministic test interrupts work every 1–7 small steps over 400 updates on
k=3/k=5 graphs. After each completed update it compares all DP values, parents,
queues, candidates, recurrence work counters and recovered answers to the unchanged
engine. Past-deadline and zero-step calls execute no maintenance. These are
continuation correctness tests, not latency or global-optimality benchmarks.

Compile `test_delta_weight_continuation.cpp` with C++17 and run its binary outside
the source tree. Do not use `-DNDEBUG` for these assertion-based tests.

Clock checks are cooperative. A single map/set operation, allocation or OS
descheduling can still overshoot. An eventual service must record that overshoot,
charge input/validation/return costs, version returned candidates against the
current graph and account for old work within later budgets. The current helper
alone does not satisfy that protocol and must not be used for Table VI results.
