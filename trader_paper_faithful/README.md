# TRADER paper reconstruction with explicit correctness completions

This is a **new, separate implementation**, not a rename of TRADER-corrected or
the earlier color-layer batch reconstruction. Its output identifies itself as
`TRADER-paper-reconstruction-terminal-v3`. It implements paper-specified mechanisms
and documents the extra rules needed for an executable correct dynamic algorithm.
It is **not** certified byte-for-byte equivalent to the authors' unpublished code,
and small-graph validation is **not** a UNI performance or global-colorless guarantee.

## Why another version

The old reconstruction at `843cc25` collected DAG-ordered seeds, then used a unified
color-cardinality worklist. That is an explicit correctness completion rather than
the weight-ordered two-direction propagation of Algorithm 1. TRADER-corrected is
different again: its best-edge invalidation can scan all closing-edge candidates.
Neither implementation should silently stand in for the paper in a comparison table.

The earlier v1 executed a separate weight-priority propagation at each edge
application. The source audit found that outer edge ordering alone did not give
the paper's DP-level once-per-pass property. V2 collects both DAG edge frontiers
into a shared color-cardinality state worklist: every state is finalized once
after all smaller masks. It also skips unchanged repairs. This is an explicit
completion of the unspecified batch `apply`, **not** a literal transcription of
Algorithm 1's priority queue, and not evidence of unpublished-author equivalence.
It imports **no DELTA engine**. The retained all-pairs domain and exact top-two
contract distinguish it from earlier root-restricted implementations. V3 omits
only full-color terminal states lacking a closing edge; it retains every shorter
endpoint/color state and materializes terminal states when a closing edge arrives.

## Source-to-code contract

Source: TRADER Technical Report, Sections IV-A/B/C, V, VI and Algorithms 1–4,
PDF pages 4–9. Corresponding IEEE paper DOI: 10.1109/ICDE65706.2026.00141.
Local research source: `6D/doc/extracted_pdf_text/TRADER_Technical_Report.md`.
The following is a targeted method audit, not a new full-paper review.

| Source | Implementation | Status / boundary |
|---|---|---|
| IV-A all-pairs/color-subset DP | `Engine::dp_`, layered forward initialization | Minimum colorful path per ordered endpoints/color set; all shorter masks, terminal masks only for existing closing edges. No minimum-root restriction. The independent `build_static_dp` reference is unchanged. |
| Algorithm 1 bidirectional recurrence | forward append and backward prepend | Recurrence retained; the batch worklist uses color-cardinality dependencies rather than Algorithm 1's weight-priority queue. This is a disclosed implementation difference, not Dijkstra finalization. |
| IV-B increase/deletion remark | witness-to-edge incidence, recurrence repair | **Correctness completion**: flag selected paths using worsened/deleted edges, reevaluate after smaller masks; retain unchanged labels/indexes without propagation. Literal `min(old,new)` cannot handle increases. |
| Algorithm 2 | `decompose_into_dags` | Degree-descending greedy edge-disjoint DAGs, BFS discovery, explicit cycle rejection. Stable ID tie-breaks are engineering choices. |
| Algorithm 3 coalescing | `coalesce_latest` | Last effective write per edge; arrival/event order is explicit. |
| Algorithm 3 edge queues | `ready_edges`, `Engine::apply_batch` | Source/sink edge queues with predecessor/successor gates enqueue contributions to a shared batch state frontier. |
| Algorithm 3 unspecified `apply` | atomic final graph + per-mask recurrence/propagation | **Declared completion**, not literally specified pseudocode. Both-direction contributions are coalesced; each state is finalized once per batch after all shorter dependencies. |
| IV-C and VI C1/C2 extraction | dirty DP closures, canonical cycle references, ordered ranking | At most one minimum full-color path per closing edge. No standalone exhaustive-cycle catalogue and no update-time whole-candidate scan. An ordered set implements an updateable min-priority ranking. |
| Algorithm 4 | `Grouped` | Cache C1/gap, accumulate adverse changes, buffer deferred edges, invoke batch maintainer on new eligible edges or gap violation. |
| Per-arrival result | `Grouped::answer` | Read anchored C1's current live edge weights, so deferred answers do not report stale weights. EOF maintenance is charged to online time. |

### Ambiguities and supported domain

1. Section V Definition V.1 and Algorithm 3 suggest different batch graph inputs.
   V2 explicitly follows **vertex-induced scheduling** in Definition V.1, including
   existing edges among updated endpoints. V1 used coalesced update edges only.
   The textual ambiguity remains; this choice does not identify the author's run.
2. Algorithm 2's starting-vertex wording can select an incident sink with no outgoing
   unassigned edge. The deterministic progress rule picks the first vertex with an
   unassigned **outgoing** edge. This is disclosed, not claimed to be prescribed.
3. The paper leaves `apply` and increase invalidation incomplete. This version cannot
   honestly be called a literal transcription with no supplementary semantics.
4. Colors are fixed per run. The stream driver requires the full vertex/color
   catalogue in advance, including not-yet-active vertices. Arbitrary new identifiers
   with online random-color assignment are **not supported** by this driver.
5. Simple directed graph, one finite weight per ordered pair, k=2..20, no self loops.
   Deletion is represented by `D` / removing the edge, equivalent to +infinity in
   finite-path queries. Same-color edges remain in the live graph but cannot enter
   colorful paths. Inputs outside the stated domain are not covered by the claims.
6. EG is per coloring. Multi-color aggregation after every arrival, deterministic
   tie-breaking and conservative cumulative adverse bounds are engineering choices.
   No claim is made that the paper's unpublished multi-color driver uses these choices.

## Correctness argument and tests

**Dynamic DP.** A selected path using a worsened/deleted edge is found through
the witness incidence map. Its old label remains stored only until its mask layer
is processed; recurrence repair reads strictly smaller, already-final masks.
States whose selected witnesses were not invalidated can only improve: a newly
better path uses an updated edge or a changed smaller path, whose contribution is
enqueued. Bidirectional extensions cover both cases. For every mask cardinality,
coalesce candidate paths, repair invalid states from all incoming predecessors,
commit once, and extend only changed labels. A removed state's affected selected
descendants are already in the invalid set. Unchanged labels need no propagation,
including when edge changes cancel within a path. Dependencies grow by one color,
so negative edge weights do not invalidate this topological ordering. This is
within the fixed-color domain, not a zero-error color-coding theorem.

**Candidate top two.** Keep the minimum full-color path per closing edge and dedupe
cycle rotations. This contains a globally best colorful cycle C1. A distinct
runner-up C2 has an edge not in C1. Taking that edge as closing edge yields a DP
representative no heavier than C2 and different from C1, hence a valid runner-up
weight. Tied different cycles give zero gap. This is a local proof under the simple
directed/all-pairs assumptions, not a theorem quoted from the paper. It does not
claim the representatives enumerate every cycle.

**Terminal-state projection.** A full-color state cannot be extended, and without
the reverse closing edge cannot yield a candidate. Omitting it affects neither
shorter recurrences nor any current cycle. On closing-edge insertion, flag and
recompute that terminal state from already-final shorter masks before refreshing
the ranking; on deletion retire it. Thus every current closing edge still has its
minimum path, preserving the top-two argument. This is a disclosed storage/work
optimization, not a claim that the paper specifies this projection. Tests compare
the projected complete state oracle and independently enumerate ALL colorful cycles
for best/runner-up checks; new/deleted closing edges receive explicit regressions.

**EG.** The anchored cycle remains optimal while the accumulated bound on reduction
of competing-cycle differences stays within its gap. Positive increases on C1 and
decreases outside C1 contribute to that bound; cancelling changes do not subtract
earlier contributions. New eligible edges, no current answer, and deletion of C1
force maintenance; the deletion rule avoids the infinity-gap corner case. Equality
at the gap may retain an equally optimal old C1. Recomputing its live weight makes
the published answer valid while DP maintenance is deferred.

`test_faithful.cpp` checks projected complete DP state keys/weights against independent
simple-path DFS, every retained witness, best and second distinct cycle weights,
mixed increase/decrease/insert/delete batches, repeated writes, reversed DAG/tie
orders, per-arrival deferred answers, equal gaps, and the no-global-candidate-scan
regression. It also exposes a small counterexample to literal increase handling.
`validate.py` builds release and profile versions and checks k=2..5, ell=8 streams
against an independent Python permutation oracle, including no-op and B=7 boundary
semantics. B=7 is a correctness test, **not** the postponed batch performance sweep.
Release and profile traces must match byte-for-byte. Finite tests support but do
not replace the stated argument, nor guarantee all future production workloads.

## Build / run

Use a private directory outside the repository; no installation is needed beyond
the existing C++17 toolchain and Python standard library.

```text
python trader_paper_faithful/validate.py --compiler <clang++> --output <new-build-dir>
<new-build-dir>/release_driver.exe <case> 5 80 eg 1 <trace.tsv>
<new-build-dir>/release_driver.exe <case> 5 80 single 1 <trace.tsv>
<new-build-dir>/release_driver.exe <case> 5 80 batch 100 <trace.tsv>
```

The last command documents an interface only; it does not authorize a batch sweep.
Cases contain `graph.txt`, `updates.txt`, `colors.txt`, then `colors_1.txt` etc.
Updates are `u v finite_weight`, `u v D`, or `u v N`. Trace rows include the initial
answer and every single/EG arrival, or batch boundary plus EOF remainder.

## Measurement and release boundary

The historical 2026-09-13 indexed-storage revision kept the full all-pairs state set,
lexicographic witness ties, priority-queue ordering, repair ordering, DAG schedule,
C1/C2 representation and EG trigger rule unchanged. Production DP lookups and
edge-to-witness membership use hash containers. The ordered reference model and
exhaustive oracles remain unchanged; tests convert the production table to an
ordered snapshot only for comparison. Weight-only changes to an identical path
leave its edge-incidence membership intact. Initialization consumes the reference
table node-by-node rather than retaining two full tables. These are local storage
optimizations, not claims about the author's unpublished container choices.

Historical validated_v2 UNI1 ell1/prefix256 measured 682.766415625 ms/update
and 4567.33203125 MiB, with 257 verified answers. Its matched profile attributed
67.88% to propagation and 31.69% to invalidation/repair. New timings require a
fresh build and the same frozen input; neither this prefix nor a lower ell may
replace Table III's full-stream/ell80 measurement. Fixed-batch experiments remain
separate from EG, whose buffered updates are flushed by the safety criterion.

The indexed-storage UNI1 pilot completed at 325.67275703125 ms/update and
4453.140625 MiB (initialization excluded). Its full input hashes, 257-answer
trace and ten non-time counters match the previous version; independent oracle
checks pass. Both release/profile builds again pass 574,241 unit checks and the
24 multi-color streams. The matched new profile reports 323.277526171875
ms/update, with repair 51.93% and propagation 46.60% of online time. These are
single-run prefix diagnostics, not stable speedup estimates or paper-level
performance. Full-stream/ell80 feasibility remains unestablished; do not promote
this version into the main comparison table yet.

The intermediate shared-layer v2 pilot measured 296.093051953125 ms/update,
4389.23828125 MiB, 257/257 correct answers, 47 maintenance batches and 196 deferred
arrivals on that same input. There were zero unchanged repairs on this particular
prefix: do not claim skipping unchanged repairs explains its improvement. V2 kept
13,686,062 states; its 15,322,085 state finalizations have a different definition
from v1 priority-queue pops and must not be compared as the same operation count.
V3 terminal projection requires its own new results, not relabeling V2 timings.

V3 now measures 207.06259609375 ms/update and 2965.05078125 MiB on the identical
UNI1/k5/ell1/256-arrival EG diagnostic, with 257/257 fixed-color oracle answers.
All three revisions have byte-identical UNI traces. State count is 10,809,784;
witness links 25,697,656; maintained batches 47; deferred arrivals 196. Relative
to hash v1 this single-run observation reduces time 36.42% and peak memory 33.42%.
Release/profile each pass 547,624 projected-DP/witness/cycle checks and the same
24 multi-color streams. Fewer witness assertions reflect omitted terminal states,
not removal of the independent exhaustive ALL-cycle best/second checks.

A matched-input GraphS run measures 192.281824609375 ms/update and
5187.9921875 MiB. V3 remains 7.69% slower. Moreover GraphS searches globally while
TRADER ell1 searches one coloring; on these 256 updates none of the ell1 answers
attains the global optimum. Correctness within a coloring does not establish
equal effectiveness. The six-mode UNI1 diagnostic remains paused: neither the
faster-than-GraphS requirement nor the full ell80 paper-performance gate is met.

The author's pinned public source also differs from the paper: at
`cycle_detector.cpp:645` its auto-batch branch passes the incoming weight by
reference to `get_edge_weight`, which overwrites it with the old weight before
the decrease comparison at lines 668–670. A read-only graph-API probe confirms
old=-1/new=-2 becomes -1/-1 and contributes zero instead of one. The threshold
assignment at line 245 uses a successive-best-record improvement, not an explicit
true runner-up gap; and the immediate-edge test checks endpoint membership, not
adjacent directed-edge membership in C1. These facts concern the public version,
not a verified version behind the paper's tables. Do not reproduce these behaviors
merely to make timings resemble Table IV. Official source files remain unchanged.

Initialization (including DP, witness incidence and candidate ranking) is excluded
from `online_ms`. Online includes input parsing, maintenance, queries, serialization
and EOF flush. `core_ms` excludes input/output. Windows peak working set is measured
over the complete process and includes initialization; non-Windows `-1` means this
driver has no OS peak measurement. Do not report it as a numeric memory result.

`TRADER_PROFILE` adds separate schedule, invalidation/repair, propagation, candidate
and EG-classification timers. They do not nest; their sum is checked against core
time. Driver/selection/answer costs form the residual. This supports the newly
prioritized Breakdown time work, but instrumented timings must not replace formal
uninstrumented measurements, and overhead needs a matched UNI-scale assessment.
The witness index can use substantial memory. No full UNI / ell80 feasibility or
paper-level speed claim is established by this implementation release.

## Provenance

`paper_batch_scheduler.{h,cpp}` and `paper_batch_reference_model.{h,cpp}` are copied
unchanged from this research repository's `trader_paper_reconstruction/` at
`843cc25`, preserving tested graph/DP/oracle/scheduler helpers. Those helpers are
local reconstructions, **not** the authors' released Algorithms 2–3. `faithful.h`,
the driver and new tests are a separate implementation. Historical reference
maintainer helpers remain unused by the new execution path.
Validation manifests store all source hashes and commands. Preserve old results;
use a new method label and fresh directories for every experiment.
