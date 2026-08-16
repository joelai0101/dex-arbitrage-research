# Data Provenance and Usage Boundary

## Source

The common benchmark uses the six processed Uniswap V2 datasets distributed in
the public TRADER repository:

- Repository: `https://github.com/Xtra-Computing/TRADER`
- Local source commit: `8e047fdf35e8c44f189a59f506431b4a180124ca`
- Access date: 2026-08-16
- Paper description: each dataset is a Uniswap V2 token graph at a particular
  Ethereum block; subsequent transactions provide chronological edge inserts or
  edge-weight updates.

The raw and transformed datasets are not redistributed in this repository.
Only metadata, hashes, configuration, conversion code, and aggregate results
may be committed.

## Important naming rule

Call these datasets **TRADER UNI1--UNI6**. RICH also reports six datasets named
UNI1--UNI6, but their graph sizes are different. In this study, RICH is executed
on snapshots reconstructed from the TRADER datasets; the data must not be
described as jointly supplied by RICH and TRADER.

## File formats

| File | Row format | Interpretation |
|---|---|---|
| `*_node_mapping.txt` | address and integer ID | Token-address mapping |
| `*_token_graph.txt` | `u v w` | Initial directed edge and processed weight |
| `*_dynamic.txt` | `u v new_weight event_id` | Chronological directed edge update |

`event_id` is the atomic comparison unit. Several directed rows may belong to
one market event; a checkpoint must be generated only after all rows carrying
the same event ID have been applied.

## `inf` policy

The files contain many weights represented by `inf`. The benchmark explicitly
defines these as edges that are inactive in the current finite graph state:

- TRADER replay retains them because a later update can make them finite.
- A RICH static checkpoint exports only currently finite edges, since an
  infinite-weight edge cannot improve a finite most-negative cycle.

This is a benchmark specification derived from the file contents and graph
semantics; it should not be presented as a verbatim statement from the paper.

## Repository audit findings

| Dataset | Mapped nodes | Initial rows | Finite initial rows | Update rows | Unique events |
|---|---:|---:|---:|---:|---:|
| UNI1 | 33,360 | 76,282 | 13,000 | 7,628 | 3,814 |
| UNI2 | 63,335 | 137,194 | 16,116 | 13,719 | 6,860 |
| UNI3 | 135,047 | 282,728 | 22,938 | 28,272 | 14,136 |
| UNI4 | 271,988 | 557,802 | 39,940 | 55,780 | 27,890 |
| UNI5 | 346,529 | 708,200 | 43,924 | 70,820 | 35,410 |
| UNI6 | 414,216 | 845,264 | 45,778 | 84,526 | 42,263 |

The repository sample was also checked against UNI1. Its 13,000 initial rows
are exactly the finite-weight UNI1 initial rows, and its 1,300 updates are the
first 1,300 finite UNI1 update rows with re-indexed event identifiers. This is a
local file comparison result, not an explicit statement in the paper or README.

## Valid claims and limitations

The datasets support claims about graph-algorithm correctness, runtime, memory,
throughput, and scalability on historical Uniswap V2 graphs. They do not by
themselves support claims about:

- realizable profit after gas, slippage, competition, or failed execution;
- Uniswap V3 concentrated liquidity;
- cross-DEX or cross-chain generalization;
- exact regeneration from raw Ethereum records, because the complete upstream
  data-construction pipeline has not yet been verified.
