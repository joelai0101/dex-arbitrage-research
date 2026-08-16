# Result Record Schema

Every run writes one machine-readable metadata record and one or more metric
records. Raw console text is supplemental and must not be the only result.

| Field | Type | Meaning |
|---|---|---|
| `run_id` | string | Globally unique run identifier |
| `timestamp_utc` | datetime | Run start time |
| `git_commit` | string | Commit of this benchmark implementation |
| `dataset` | enum | UNI1--UNI6 |
| `block` | integer | Initial Ethereum block |
| `checkpoint_event` | integer | Number of complete event IDs applied |
| `checkpoint_percent` | number | Position in the event stream |
| `method` | string | RICH, TRADER, reference, or proposed variant |
| `k` | integer | Hop bound |
| `coloring_instances` | integer | Number of coloring repetitions |
| `seed_set` | string | Seed-manifest identifier |
| `repeat` | integer | Timed repetition number |
| `cycle_nodes` | array/string | Canonical cycle representation |
| `cycle_weight` | float | Returned total weight |
| `reference_weight` | float | Weight used for quality comparison |
| `relative_error` | float | Absolute relative weight difference |
| `preprocess_ms` | float | Format conversion/checkpoint construction time |
| `initialization_ms` | float | Initial state construction time |
| `detection_ms` | float | Static detection time |
| `update_ms` | float | One complete event update time |
| `peak_rss_mb` | float | Whole-process maximum resident memory |
| `dp_memory_mb` | float | DP-state storage memory when measurable |
| `stored_states` | integer | Number of retained algorithm states |
| `throughput_events_s` | float | Complete event IDs processed per second |
| `status` | enum | success, mismatch, TLE, OOM, crash, skipped |
| `hardware_id` | string | Frozen machine configuration identifier |
| `compiler` | string | Compiler and optimization flags |

Aggregated tables must retain a link to the underlying run IDs so every plotted
point can be traced back to raw measurements.
