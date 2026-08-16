# Common Benchmark Experiment Protocol

Status: **Draft -- freeze before optimization experiments**

## 1. Research objective

Evaluate whether a new negative-cycle maintenance method can preserve the same
answer as a controlled RICH/TRADER reference while improving at least one system
metric on dynamic DEX token graphs.

The benchmark does not assume in advance that memory layout is the final thesis
contribution. Baseline profiling is used to choose and then lock one primary
target, such as DP-state memory, update latency, throughput, or affected-state
propagation.

## 2. Research questions

| ID | Research question | Required evidence |
|---|---|---|
| RQ1 | Can RICH and TRADER be evaluated on identical logical graph states? | Matching dataset hashes, event replay, checkpoints, parameters, and seeds |
| RQ2 | Does the proposed method preserve the reference detection result? | Cycle weight equivalence and relative error at every tested event/checkpoint |
| RQ3 | Does the proposed method reduce online computation cost? | Initialization, median/P95/P99 update time, and throughput |
| RQ4 | Does the proposed method reduce memory cost? | Peak RSS, DP-table memory, and bytes per stored state |
| RQ5 | How do benefits and trade-offs change with graph size and hop bound? | UNI1--UNI6 and k = 3--6 scalability results |

## 3. Inputs and outputs

### Inputs

- one TRADER initial graph and its chronological update stream;
- hop limit `k`;
- identical vertex color assignments and seed manifest;
- number of color-coding instances;
- update mode and checkpoint schedule;
- fixed hardware/compiler configuration.

### Outputs

- detected cycle in canonical rotation/direction form when available;
- cycle weight;
- relative error against the selected reference;
- initialization and detection/update latency;
- maximum process memory and DP-state memory;
- processed updates per second;
- TLE/OOM/failure status and complete run metadata.

## 4. Compared methods

| Method | Role | Modification policy |
|---|---|---|
| Original RICH | Static recomputation baseline at checkpoints | Keep external and unmodified |
| Original TRADER | Dynamic incremental baseline | Keep external and unmodified |
| Independent reference implementation | Makes common seeds/state inspection possible | Written in this repository from paper specifications |
| Proposed method/variants | Thesis contribution | Implement behind the same domain interfaces |

RICH is probabilistic and is not automatically the exact ground truth. For
semantic-preserving optimization, the original/reference method under the same
color assignments is the equivalence target. Small induced graphs additionally
require an exact solver to validate true optimum quality.

## 5. Logical graph and checkpoints

Let `G_t = (V, E_t, w_t)` be the finite graph after atomic event `t`.

1. Load all initial records.
2. Treat `inf` as inactive at the current time.
3. Apply all directed rows sharing an `event_id` as one atomic event.
4. After 0%, 1%, 5%, 10%, 25%, 50%, 75%, and 100% of unique events, export
   the finite graph to RICH CSR and recompute from scratch.
5. TRADER and the proposed dynamic method process every event and retain their
   state between events.

RICH preprocessing, RICH detection, TRADER initialization, and TRADER online
update time must be reported separately. A full-snapshot RICH time must not be
presented as though it were the same task as one TRADER edge update.

## 6. Experimental stages and approval gates

| Stage | Scope | Completion gate |
|---|---|---|
| 1. Data audit | UNI1--UNI6 counts, hashes, finite/`inf` values, event grouping | Manifest matches all local files; no raw data is tracked |
| 2. Baseline smoke and reproduction | UNI1, small k/instance count, then paper-default trend checks | Both baselines run; outputs and timing fields are captured |
| 3. Common benchmark | Same graph states, k, color assignments, seeds, checkpoints | RICH/TRADER/reference outputs are comparable and discrepancies explained |
| 4. Improvement and ablation | Implement one locked primary optimization plus component variants | Correctness gate passes; each component's effect is isolated |
| 5. Final evaluation | All six datasets and locked protocol | All metrics, failures, held-out results, and limitations are reported |

Each stage should be reviewed before the next stage begins.

## 7. Development and final-evaluation split

- **Smoke test:** UNI1.
- **Development/profiling:** UNI1--UNI3.
- **Held-out final scale evaluation:** UNI4--UNI6.

The optimization target is selected using development profiling, then frozen
before examining final held-out results. Final tables still report all six
datasets.

## 8. Parameter matrix

| Experiment | Datasets | k | Coloring instances | Seeds/runs |
|---|---|---|---|---|
| Smoke | UNI1 | 3 | 1, then 5 | 1 |
| Paper-trend reproduction | UNI1--UNI6 | 5 | 40 and 80 | 3 seed sets |
| k sensitivity | UNI1, UNI3, UNI6 | 3, 4, 5, 6 | 40 and 80 | 3 seed sets |
| Final common benchmark | UNI1--UNI6 | 3, 4, 5, 6 as resources permit | locked after reproduction | 3 timed repetitions |

If a configuration exceeds the one-hour limit or available memory, report TLE
or OOM. Do not silently replace it with a smaller configuration.

## 9. Metrics and reporting

| Aspect | Metric | Plain-language interpretation |
|---|---|---|
| Answer quality | Cycle Weight | How negative is the best cycle returned? |
| Correctness | Relative Error | How far is its weight from the selected reference? |
| Computation efficiency | Detection/Update Time | How long does initial detection or one update take? |
| Memory efficiency | Maximum Memory Consumption | What is the highest memory demand? |
| Processing capability | Throughput | How many complete update events are processed per second? |

For dynamic latency report median, P95, and P99, not only the mean. Memory
reports should distinguish whole-process peak RSS from algorithm-specific DP
table memory. Scalability is an analysis across UNI1--UNI6 and k, not a
substitute for a measured metric.

## 10. Correctness and contribution gates

1. Use the same graph state, k, color assignments, and seeds.
2. Require cycle-weight equality within documented floating-point tolerance.
3. Treat different cycles with the same minimum weight as a tie, not an error.
4. Report relative error of zero for a semantics-preserving optimization.
5. Compare every planned metric even if only one is the primary contribution.
6. Claim improvement only on the metric(s) actually improved; disclose all
   latency-memory-quality trade-offs rather than claiming universal dominance.

## 11. Threats to validity

- TRADER UNI1--UNI6 are processed historical Uniswap V2 datasets from one
  repository and do not establish cross-protocol generalization.
- Original RICH and TRADER defaults differ; uncontrolled paper numbers are not
  a fair head-to-head benchmark.
- RICH/TRADER use randomized color coding; seed control is mandatory.
- Windows and Linux memory/timing measurements are not directly interchangeable.
- A faster negative-cycle detector does not prove executable net arbitrage
  profit without CFMM sizing, gas, slippage, competition, and transaction risk.
