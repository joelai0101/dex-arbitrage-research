# TRADER paper reconstruction with Edge Grouping

Status (2026-09-12): this branch passed all four C++ suites and six multi-color stream oracle checks after the alignment change. This branch changes DP storage ordering to destination-major and replaces whole-table witness scans with endpoint-local recurrence seeds. Forward queues handle insertions/decreases, reverse queues handle increases/deletions, and the existing color-layer propagation recomputes downstream states. New validation evidence is in `.research_data/common_benchmark/paper_alignment_20260912/trader/validation.json` in the research workspace. UNI performance remains under bounded pilot evaluation; prior-branch timings below are not results for this branch.

Baseline evidence: commit 7ba763f passed four C++ suites and six multi-color checks. Its UNI1 k=5, ell=1, 16-update pilot used 1998.98 MiB peak and 204.60 ms/update after 100.10 s initialization. This branch must pass the same complete-state and answer oracles before a new timing comparison. All-pairs state count and candidate storage remain unchanged by the first optimization; lower memory is not claimed.

This separate research implementation follows TRADER Sections V-VI, Algorithms 2-4 (ICDE 2026, DOI 10.1109/ICDE65706.2026.00141). It does not overwrite TRADER-corrected, DELTA, the upstream authors' code, or prior measurements. The display label is `TRADER-paper-reconstructed-EG`, not `TRADER-l80 (original)`.

### Online-cost optimization

The diagnostic build can enable `TRADER_PROFILE` to report graph snapshot, DP maintenance and candidate maintenance times. It does not move initialization into the online metric. On the pre-optimization UNI1/16-update/ell=1 pilot, DP maintenance used 6623.44 of 6720.34 online milliseconds; candidate maintenance used 87.01 ms. These are single diagnostic-run totals, not full-stream means.

The matching post-optimization diagnostic pilot completed at 234.38 ms/update (previous diagnostic: 420.02), with 17/17 oracle-checked answers and 1987.65 MiB peak process memory. DP and candidate maintenance totals were 3717.19 and 22.69 ms. This is a one-run diagnostic improvement, not a formal multi-run result or an improvement over the older 204.60 ms/update single pilot. All-pairs memory remains a blocker to scaling the number of resident colorings. Both diagnostic and non-instrumented builds passed four C++ suites (including 4904 Edge Grouping checkpoints) and six multi-color stream checks.

A non-instrumented confirmation on the same 16 updates completed at 226.56 ms/update, 1989.38 MiB peak process memory, with 17/17 correct answers. Initialization was 110367.13 ms and is excluded. This is still a single-color pilot, not the formal ell=80 comparison.

Extending the same non-instrumented binary to the first 64 updates yielded 374.91 ms/update and 2324.32 MiB peak, with 65/65 correct answers. Initialization (112760.92 ms) is excluded. Maintenance increased from 2 to 15 batches, with 1738838 DP states processed. The longer pilot illustrates workload variation; it is not evidence of a speedup without a matching pre-optimization 64-update run. Do not select only the faster short pilot as the formal result.

Forward insertion/decrease work now carries improving state values instead of rescanning every incoming predecessor. An increase/deletion, or a worsened predecessor state, forces the full recurrence; this repair overrides possibly stale forward proposals in mixed batches. Color-cardinality order ensures predecessors settle before successors. Candidate reweighting preserves unchanged edge-incidence entries and updates only the ordered weight index. Tests cover full state equality and candidate reweight/delete/reinsert behavior. The state universe, Algorithm 2 schedule, Algorithm 4 grouping and exact-k query definition are retained.

Selected-witness repair further restricts adverse-update work: recompute a successor only if its stored optimum or queued improvement actually uses the worsened predecessor. A proposal for a previously absent state can also become stale in a mixed increase/insertion batch; it must not be skipped. A regression linked against the prior release objects reproduced unnecessary recomputation of an unaffected optimum. The new implementation passes that test, the mixed-batch counterexample, all existing state tests, and the multi-color stream oracles.

On identical 64-update input hashes, selected-witness repair completed at 223.18 ms/update (previous: 374.91), 2304.16 MiB peak, 65/65 correct answers and 1574576 DP states processed. Maintenance count (15), candidate count (255802) and resident state count (13686062) were unchanged. Initialization (110719.11 ms) is excluded. This single-run result remains far from demonstrating paper-level ell=80 performance; it does not pass the formal performance-alignment gate.

Timing labels must distinguish one answer per arrival from one full maintenance per arrival. Paper Table III uses Edge Grouping (6.66–18.14 ms/update for ell=80); Table IV's TRADER-1 is 314.05–788.58 ms/update. The current adaptive-EG pilots target the former semantics, not an excuse to compare against the slower TRADER-1 column. Initialization is excluded in both cases; a faster short pilot alone does not establish reproduction of Table III.

The current official GitHub main was checked as `8e047fdf35e8c44f189a59f506431b4a180124ca` on 2026-09-12. A runtime claim against that release requires aligned input parsing, per-update answer publication and answer-quality checks; the paper's Table III is not a measurement of that release on this machine. No faster-than-official claim is established here.

## What is implemented

| Paper component | Implementation | Explicit completion / boundary |
|---|---|---|
| Algorithm 2 | Coalescing, greedy edge-disjoint DAG decomposition | Update-edge-only and vertex-induced interpretations remain separately selectable |
| Algorithm 3 | Forward/reverse topological edge queues seed DP work | Atomic final snapshot, selected-witness invalidation, and increasing color-set recomputation define the otherwise unspecified apply operation |
| Candidate C1/C2 | Ordered set of distinct directed exact-k colorful cycles; edge-to-cycle incidence index | Initialize by cycle enumeration, discover new cycles on inserted edges, reweight affected candidates at maintenance boundaries |
| Algorithm 4 | Accumulate adverse changes relative to the last maintained C1 and cycle gap; defer while within gap; trigger on a new edge or gap violation | Per-coloring grouping, immediate selected-cycle deletion, and EOF flush are declared choices |
| Streaming answers | Return C1 identity with its weight recomputed from live edges, even during deferral | O(k) live-weight read avoids a stale price while DP maintenance is deferred |

The DP model actually maintains all-pairs color-subset states. The implementation is not the current canonical-root corrected core merely wrapped in a DAG. The forward/backward orders determine seeds, then all affected states are recomputed by color-set cardinality. This is a documented correctness completion, not proof of identical internal scheduling to the authors' unpublished production code.

The candidate catalogue explicitly enumerates the complete fixed-color cycle universe. It is part of the measured implementation, not an external oracle. This can be expensive in initialization and memory. No UNI-scale suitability is assumed before measurement. The paper describes maintaining all candidate cycles but does not fully specify how to construct or incrementally index that set; the DFS and incidence index here are local completion choices.

## Edge Grouping details

- C1 and C2 are different canonical directed cycles; rotations do not create fake runner-up cycles. Tied distinct cycles have zero gap.
- A gap of positive infinity means there is exactly one candidate. No candidate forces maintenance on effective changes; a new edge always forces maintenance.
- Contributions use consecutive live old/new edge weights. Decreases outside the anchored C1 and increases on C1 increase the accumulated bound. Reverse changes do not subtract earlier contributions, so cancellation can conservatively trigger extra work.
- On maintenance, Algorithm 3 receives the whole pending batch; the candidate index is then synchronized to that final graph. The cumulative bound and gap are reset.
- During deferral the live graph changes but maintained DP/candidate keys remain at the previous maintenance boundary. Returned C1 weight is freshly evaluated, not read from the stale key.
- Each coloring has its own C1/C2 and grouping decision. The driver returns the best answer across the specified colorings after every raw update. This is an explicit interpretation, not a claim that the paper uses the same global/per-instance queue boundary.
- EOF flush cost is included in online time. Initialization, including candidate enumeration and initial DP, is excluded and reported separately.
- The input stream is the existing common normalized domain. `N` rows count as observed updates; formal deletion rows are rejected. Deletion is nevertheless tested as a correctness case in unit tests.

## Verification gates

1. Preserve and re-run the scheduler, layer-wise state/answer, and legal-order tests.
2. Test Algorithm 4 against independent exhaustive cycle answers after every arrival, including deferred arrivals; compare the complete DP state table after every maintenance.
3. Cover equality at the gap, cumulative threshold crossing, repeated-edge coalescing, current-price reporting, new edges, deletion, one/no candidate, different DAG modes, k=3/4/5 and fixed random streams.
4. Run a multi-color stream-driver smoke test against independent Python exhaustive cycles, outside formal timing.
5. Only after these pass, decide an explicit UNI-scale pilot budget. No new full UNI sweep or batch sensitivity run is authorized by these unit gates alone.

The original all-pairs layer-wise source and existing tests are copied without modification from this user's historical reconstruction worktree at commit `1ec5b4266e41f8a05affafd8e7af3b20605568f0`, directory `dynamic_cycle_detection/`. They are not claimed to be original authors' released Algorithms 2-3. The validation manifest records current SHA-256 values.

## Build and run

Use a separate build directory outside the repository:

```text
cmake -S trader_paper_reconstruction -B <private-build-dir> -DCMAKE_BUILD_TYPE=Release
cmake --build <private-build-dir>
ctest --test-dir <private-build-dir> --output-on-failure
<private-build-dir>/trader_paper_eg <case-directory> 5 80 update-only <trace.tsv>
```

The project helper `6D/code/tools/validate_trader_paper_reconstruction.py` uses the existing project-local Clang toolchain. It refuses to compile or run tests while the active formal benchmark supervisor or child is alive. It does not install tools, start a full dataset experiment, or alter existing benchmark output.

Local verification evidence is stored outside Git in `.research_data/common_benchmark/trader_paper_reconstruction_20260912/validation.json` and `build_20260912_164516/`. All six stream checks reported zero nonoptimal answers, invalid paths, or weight/path mismatches. The initial sandbox compilation was denied before producing an executable; its separate failed log is retained. The successful build ran only after a process inventory confirmed the formal supervisor and child were absent.

## Evidence and presentation boundaries

Show performance/Regret values only after executable verification. Keep this variant separate from `TRADER-corrected` and paper-reported numbers. Present English table values to two decimal places, retain full precision in raw results, and compare best/ties using unrounded values. A nonzero positive value smaller than 0.005 should display `<0.01` rather than imply exact zero; explain rounded displays in a table footnote.
