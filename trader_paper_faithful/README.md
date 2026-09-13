# TRADER paper-faithful mechanisms with explicit correctness completions

This is a **new, separate implementation**, not a rename of TRADER-corrected or
the earlier color-layer batch reconstruction. Its output identifies itself as
`TRADER-paper-faithful-completed-v1`. It implements the paper-specified mechanisms
and documents the extra rules needed for an executable correct dynamic algorithm.
It is **not** certified byte-for-byte equivalent to the authors' unpublished code,
and small-graph validation is **not** a UNI performance or global-colorless guarantee.

## Why another version

The old reconstruction at `843cc25` collected DAG-ordered seeds, then used a unified
color-cardinality worklist. That is an explicit correctness completion rather than
the weight-ordered two-direction propagation of Algorithm 1. TRADER-corrected is
different again: its best-edge invalidation can scan all closing-edge candidates.
Neither implementation should silently stand in for the paper in a comparison table.

This version executes actual propagation at each Algorithm-3 edge application,
uses Algorithm-1 weight-priority labels extending both path ends, and updates only
dirty DP-closure representatives in its ranking. It imports **no DELTA engine** and
retains no DELTA state-transition DAG.

## Source-to-code contract

Source: TRADER Technical Report, Sections IV-A/B/C, V, VI and Algorithms 1–4,
PDF pages 4–9. Corresponding IEEE paper DOI: 10.1109/ICDE65706.2026.00141.
Local research source: `6D/doc/extracted_pdf_text/TRADER_Technical_Report.md`.
The following is a targeted method audit, not a new full-paper review.

| Source | Implementation | Status / boundary |
|---|---|---|
| IV-A all-pairs/color-subset DP | `Engine::dp_`, `build_static_dp` | Minimum colorful path per ordered endpoints and color set; no minimum-root restriction. |
| Algorithm 1 min-priority pending states | `Engine::propagate` | Weight-ordered label-correcting queue; forward append and backward prepend; changed labels may requeue. Negative weights do not justify Dijkstra-style finalization. |
| IV-B increase/deletion remark | witness-to-edge incidence, invalidation and recurrence repair | **Correctness completion**: remove only selected paths using worsened/deleted edges, reevaluate in increasing color cardinality, then propagate repaired labels. Literal `min(old,new)` cannot handle increases. |
| Algorithm 2 | `decompose_into_dags` | Degree-descending greedy edge-disjoint DAGs, BFS discovery, explicit cycle rejection. Stable ID tie-breaks are engineering choices. |
| Algorithm 3 coalescing | `coalesce_latest` | Last effective write per edge; arrival/event order is explicit. |
| Algorithm 3 edge queues | `ready_edges`, `Engine::apply_batch` | Source edges in forward queue / sink edges in reverse queue; predecessor/successor completion gates; each DAG pass actually invokes propagation, not merely records seeds. |
| Algorithm 3 unspecified `apply` | atomic final graph + invalidation phase + directional first extension | **Declared completion**, not literally specified pseudocode. The first extension follows the selected pass, subsequent states use Algorithm 1's two-direction engine. |
| IV-C and VI C1/C2 extraction | dirty DP closures, canonical cycle references, ordered ranking | At most one minimum full-color path per closing edge. No standalone exhaustive-cycle catalogue and no update-time whole-candidate scan. An ordered set implements an updateable min-priority ranking. |
| Algorithm 4 | `Grouped` | Cache C1/gap, accumulate adverse changes, buffer deferred edges, invoke batch maintainer on new eligible edges or gap violation. |
| Per-arrival result | `Grouped::answer` | Read anchored C1's current live edge weights, so deferred answers do not report stale weights. EOF maintenance is charged to online time. |

### Ambiguities and supported domain

1. Section V Definition V.1 and Algorithm 3 suggest different batch graph inputs.
   This executable fixes **coalesced update edges only**, as Algorithm 3's input
   states. It does not silently select vertex-induced scheduling for speed.
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

**Dynamic DP.** A selected path using a worsened or deleted edge is found through
the witness incidence map. Its state is invalidated before any batch-final repair.
All remaining labels are valid paths; decreases can leave valid but nonminimal
upper bounds. Invalid states are repaired from smaller color sets. Seeding every
effective inserted/reweighted edge and expanding both ends supplies paths involving
updated edges; state dominance is sound because extensions depend on endpoints and
used colors. Every extension adds a color, so there is no cycle in the dependency
layers even though the token graph may contain negative cycles. Improved labels are
requeued rather than finalized on the first pop. Tie-witness changes also propagate.
The argument is within the fixed-color domain, not a zero-error color-coding theorem.

**Candidate top two.** Keep the minimum full-color path per closing edge and dedupe
cycle rotations. This contains a globally best colorful cycle C1. A distinct
runner-up C2 has an edge not in C1. Taking that edge as closing edge yields a DP
representative no heavier than C2 and different from C1, hence a valid runner-up
weight. Tied different cycles give zero gap. This is a local proof under the simple
directed/all-pairs assumptions, not a theorem quoted from the paper. It does not
claim the representatives enumerate every cycle.

**EG.** The anchored cycle remains optimal while the accumulated bound on reduction
of competing-cycle differences stays within its gap. Positive increases on C1 and
decreases outside C1 contribute to that bound; cancelling changes do not subtract
earlier contributions. New eligible edges, no current answer, and deletion of C1
force maintenance; the deletion rule avoids the infinity-gap corner case. Equality
at the gap may retain an equally optimal old C1. Recomputing its live weight makes
the published answer valid while DP maintenance is deferred.

`test_faithful.cpp` checks complete DP state keys/weights against independent
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
