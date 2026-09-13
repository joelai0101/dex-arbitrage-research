# Official-source TRADER dual-version experiment

Pinned upstream commit: `8e047fdf35e8c44f189a59f506431b4a180124ca`.
Supply the five upstream source blobs locally. They are hash-checked and are not
redistributed in this repository. Original files are never overwritten.

`prepare_source.py` generates two isolated copies:

- `official`: common finite/N input interface and arrival-ordered new-node
  coloring; original DP and EG decisions remain unchanged.
- `oldnew`: the identical interface plus one EG lookup fix that preserves the
  incoming weight. This is a **partial diagnostic patch**, not a completed or
  accepted minimally corrected baseline. It does not repair the C1/C2 gap.

Fixed batches count every arrival including N. N does not change the graph or
trigger EG maintenance. New colors use the official C++ RNG, in first-arrival
source/destination order independent of mode. Future vertices are not added to
the initial graph. This common input protocol intentionally controls a native
mode-dependent coloring difference; it is not advertised as untouched native I/O.

Compile with `COMMON_AUDIT` only for correctness diagnostics. The observer logs
the maintained path/weight without calling the official output routine or
recomputing an answer. Initial, per-arrival, and EOF answers are separate. Audit
executables are not used for formal timing. `COMMON_COLOR_EXPORT` exports the
paired color maps while skipping DP and is likewise never a speed result.

Run `validate_interface.py --root <research-workspace> --output <new-output-dir>`
using the project Python environment. It compiles both variants and checks:

- finite k=3/k=5 traces against an existing observed original executable in all
  six modes;
- strict no-op handling and identical future colors/final graphs across modes;
- UNI1 initial color identity, 80 complete arrival-color maps, and no premature
  insertion of future graph vertices;
- legal-cycle weight, global/colored oracle and quality for known small cases.

The native entry point still uses sequential color trials. Its memory/aggregate
timing must not be presented as a simultaneous best-of-80 online service. The
separate persistent-service stage below provides that lifecycle. No speed matching
or main-table version selection is performed by these scripts.

## Persistent service (second stage)

`prepare_service.py` extracts the native initialization, update-loop body and EOF
maintenance into callable methods, retaining each color's graph/DP/buffer in one
live object. It leaves the native entry point and DP implementation present.
`service_driver.cpp` holds all ell objects, selects the minimum maintained weight,
and materializes the returned path. It does not rerank paths by an offline oracle
or fix stale reported weights. Native internal output-string work is retained.
External trace-file output is outside the detection timer.

`validate_service.py --root <workspace> --output <new-directory>` compares 36
per-color trace/final-color/final-graph cases against the previously validated
interface, then runs serial full-static-UNI1/prefix-32 EG resource pilots at
ell=1/4/80. These resource pilots are not complete UNI1 performance results.

`run_uni1_official.py --root <workspace> --service <validated-service-directory>
--output <new-directory> --mode EG` performs one complete official-core UNI1 run,
then runs the independent global exact-5 oracle separately. Other supported modes
are B1/50/100/500/1000. It records source/input/binary provenance and OS process
peak memory. Full-stream path Relative Error and Regret use the returned path's
actual current weight; mismatch with a stale printed weight is counted separately.
Initial/per-arrival/EOF traces remain separate. A complete execution does not
declare the original core optimal or select the paper's main-table version.

## Paired DELTA and complete batch boundaries

`run_delta_uni1.py` copies hash-pinned local DeltaEngine sources without modifying
their core, compiles `delta_service_driver.cpp`, and validates a 1002-arrival case
at B=1/50/100/500/1000. The fixture includes interior boundaries, repeated edges,
increases/decreases, ties, N rows, a new minimum-ID root and an EOF remainder.
Only initially observed roots are initialized; a future root is materialized on
first arrival using the frozen shared color map. It then runs five complete UNI1
single runs, recording both per-arrival available-answer and publication-point
quality. The latter includes EOF's partial batch; it is not substituted into the
per-arrival trace. The independent same-input oracle is reused after hash checks.

`validate_trader_boundaries.py` uses that fixture for native/persistent fidelity
checks in both variants and all six modes. Once passed,
`run_official_fixed_queue.py` executes the five full official fixed modes serially,
with process state/checkpoints and no automatic failed-run retry. It reuses the
completed EG run's same-input oracle and never reruns EG. Do not compile, profile,
run another oracle, or benchmark another method while this queue is measuring.

## GraphS common-input service

`prepare_graphs_common.py` changes only the hash-pinned weighted adapter's vertex
arrival handling: reserve IDs, initialize observed vertices in ascending order,
and insert new endpoints into the public forward/reverse graphs on arrival.
The existing third-party HP-index backend class files remain hash-identical.
This is a locally adapted third-party implementation, not official GraphS.

`run_graphs_uni1.py` compiles that adapter and `GraphSCommonDriver.java`, checks
thresholds 1/3/40 against the existing 1002-update oracle fixture, then measures
one complete UNI1 run at threshold 40 with a 16 GiB Java heap limit. GraphS is
uncolored exact-5: ell and colorful-path checks are not applicable. The common
timer includes update parsing, maintenance, winner access and answer copying;
initialization and external trace output are excluded. OS peak memory is sampled
before the resident service is released. Full quality uses the same hash-checked
global oracle as DELTA/TRADER, after timing. Run this stage only when the official
fixed queue is complete; keep compilation, profiling and other measurements out
of its timing interval. A passing small fixture is not a completed full result.
