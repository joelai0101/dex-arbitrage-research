# Deadline continuation experiment (DELTA window / TRADER primitive)

This is an experimental execution variant, not the official TRADER implementation
and not yet a validated 10 ms end-to-end service. Production files are unchanged.

`DeltaWeightContinuation` reuses the existing DELTA state representation and
recurrence, saving the incoming/outgoing arc cursor and propagation phase across
calls. It accepts finite-edge insertions/reweights, deletions and no-ops within a
fixed precolored vertex universe. Explicit connect/ensure frames preserve the
original depth-first expansion and arc numbering across pauses. New vertices outside
that universe and GraphS continuations are not implemented yet. TRADER has the
separate single-engine primitive described below, not a complete service. The
single-engine primitive alone does not schedule multiple colorings or validate
candidates against later arrivals.
Unsupported operations are rejected before mutation. Partial engine answers cannot
be published. No background worker runs after a resume call returns.

The deterministic test interrupts work every 1–7 small steps over 3400 updates on
k=3/k=5 graphs, including sparse initial graphs, isolated precolored vertices,
insertions, deletions, repeated no-op deletions and reactivations. After each
completed update it compares all DP values, parents, topology/arc numbering,
lookup indexes, queues, candidates, recurrence work counters and recovered answers to the unchanged
engine. Past-deadline and zero-step calls execute no maintenance. These are
continuation correctness tests, not latency or global-optimality benchmarks.

Compile `test_delta_weight_continuation.cpp` with C++17 and run its binary outside
the source tree. Do not use `-DNDEBUG` for these assertion-based tests.

Clock checks are cooperative. A single map/set operation, allocation or OS
descheduling can still overshoot. An eventual service must record that overshoot,
charge input/validation/return costs, version returned candidates against the
current graph and account for old work within later budgets. The current helper
alone does not satisfy that protocol and must not be used for Table VI results.

An optional real-input correctness gate accepts three paths: normalized graph,
normalized update stream, and the frozen 80-row color matrix. It checks the first
32 updates for every coloring, processing one engine pair at a time and comparing
all completed states/indexes/work counts/answers. It uses the unchanged core's
fixed-universe initialization, not the service driver's observed-root activation.
Thus it is not a replay of the official benchmark service, an 80-resident scheduler
test, or a detection-time result. No new colors or graph edges are inferred.

## Multi-color service primitives

`DeltaServiceContinuation` keeps all supplied colorings resident, installs arrivals
into a separate current graph, and replays a FIFO of pending updates into the
engines without background work. An update becomes committed only after every
engine has completed it and published a recovered path. Per-engine cached paths
carry their source version. Candidate queries revalidate only those cached paths
against the latest accepted graph and return a finite negative simple k-cycle,
its freshly summed weight, source version and graph version. No oracle or path
search runs in this query. A stale-version path may remain valid, but is never
returned with an unvalidated old weight.

The service uses observed-root initialization. A previously unseen precolored
vertex gets its seed state just before its first S update is installed, matching
the normal B=1 service order. It has no previous outgoing S edges at that point,
so creating that seed does not run a recursive graph expansion.

`test_delta_service_continuation.cpp` checks 320 arrivals across k3/k5 cases with
80 resident colorings, including 304 backlog arrivals, 1280 completed engine-state
comparisons, no-work calls at zero/expired budgets, and invalidation of a cached
cycle after deletion without maintenance. The original 3400-update engine tests
also pass with the optional observed-root mode added.

These remain service primitives, not the formal 10 ms driver. `accept`, parsing,
candidate validation/copy and the actual caller return all cost time and MUST be
charged alongside `advance_until`. That function's deadline alone is not an
end-to-end latency bound. No per-arrival formal RE/Regret is produced here. A timed
driver with complete-window traces, return/overshoot measurements, a fixed reserve
policy and the real UNI trace gate is the next step. Do not drain backlog for free
between timed arrivals. Empty candidate means no valid negative cached path was
available, not proof that the current graph has no negative cycle.

## Complete-window pilot

`delta_window.hpp` reads/parses one normalized input row, accepts it into the live
graph/FIFO, resumes old/new maintenance, validates cached candidates and constructs
the response. The caller measures from BEFORE entering this function until AFTER
receiving the complete response. The frozen pilot policy is 10 ms total with 1 ms
reserved for validation/return. Cooperative work or OS scheduling may overshoot;
all actual overshoots must be retained, not retried away. `test_delta_window.cpp`
checks zero/expired maintenance budgets, malformed-input rejection, timestamp
ordering, FIFO debt and current-weight revalidation after delete/reinsert.

`run_delta_window.cpp graph updates colors count trace.csv` records per-phase ns,
actual in-process caller receipt, overshoot, accepted/committed/candidate versions,
work counters, backlog and every returned path or missing result. It never drains
backlog between requests or at EOF. Initialization is outside the windows. Diagnostic
trace persistence and unlimited reference replay happen AFTER all timed requests
and destruction of the service. The independent post-run path check uses the live
graph and verifies closure, simplicity, exact-5 length, coloring and actual weight.
Rows with no remaining debt also compare against the unchanged unlimited DELTA core.

The first UNI1 32-row gate passed with 32 legal candidates, 31 complete-reference
comparisons, no late/missing returns, maximum return 9.0418 ms, and maximum debt 1.
One subsequent full 7628-row pilot passed with 7628 legal candidates, 7186 complete
reference comparisons, 0 late/missing returns, maximum return 9.0842 ms, maximum debt
2, and zero EOF debt without a flush. 442 responses had outstanding work; 3 selected
a candidate from an older source version, revalidated against the current graph.
These are single-run observations, not a hard-real-time guarantee, global exact-k
quality certification, or a three-method Effectiveness table. No RE/Regret has yet
been joined to the independent global oracle for this new trace. The normalized N
semantics and frozen coloring universe retain the normal benchmark's limitations.

## TRADER stack-preserving primitive (Windows)

`cooperative_fiber.hpp` saves the existing C++ call stack at explicit loop-entry
checkpoints instead of replacing TRADER's DP recurrence with another algorithm.
Fibers execute cooperatively on the caller thread, not a background worker.
Zero-step or expired calls execute no maintenance. Suspended local containers,
references and recursion frames remain alive. The engine may be internally partial
while suspended: do not inspect/publish it or mutate it from another arrival.
Destruction cancels and unwinds suspended locals; that private partial engine must
then be discarded, never reused as a committed result.

The private gate builder is `6D/code/tools/run_trader_fiber_gate_20260916.py` in
the surrounding research workspace (excluded from this repository). It verifies
the frozen `service_v1/official` hashes from the existing EG protocol, creates an
isolated copy with 37 detector and 3 graph loop checkpoints, and exposes fields
only for testing. Stripping inserted checkpoint markers exactly recovers each
original source text. Official files are not edited or copied into this repository.

`test_trader_fiber.cpp` compares paused execution to the same frozen operations
with inactive checkpoint calls. All DP values, candidate weight/path, pending
batch/counters, threshold, RNG, colors and graph adjacency/weights must match after
each completed update and test-only EOF flush. k3/k5, four deterministic all-color
fixtures, B=1/50/100/500/1000 and EG passed 5,088 comparisons with 59,546 pauses and
165,004 checkpoint steps. Inputs here are reweights and explicit no-ops; insertion,
the real UNI prefix, multiple resident engines, FIFO versions, current-graph cached
candidate validation and complete-window timing are NOT covered yet.

The initial test fixture could omit one color and fail its initial-negative-cycle
precondition. That failed binary is retained; the corrected fixture selects seeds
by full-color coverage before constructing either engine, not by measured speed
or output quality. The completed gate is not a detection-time or Effectiveness
result. Individual allocation/container operations and OS scheduling can still
overshoot a deadline; a later full-window service must charge and record them.
