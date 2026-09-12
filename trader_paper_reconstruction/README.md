# TRADER paper reconstruction with Edge Grouping

Status (2026-09-12): compiled with project-local Clang C++17 -O3. All four C++ test executables passed, including 4,898 Algorithm 4 answer/state checkpoints. Six independent Python multi-color stream checks passed (k=3/4/5, ell=8, both DAG modes, 40 updates plus initial answer each). UNI-scale performance and memory validation remain pending. These small-graph checks do not establish full UNI correctness or scalability.

This separate research implementation follows TRADER Sections V-VI, Algorithms 2-4 (ICDE 2026, DOI 10.1109/ICDE65706.2026.00141). It does not overwrite TRADER-corrected, DELTA, the upstream authors' code, or prior measurements. The display label is `TRADER-paper-reconstructed-EG`, not `TRADER-l80 (original)`.

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
