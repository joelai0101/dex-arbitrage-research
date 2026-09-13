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

Native execution still uses sequential color trials. Its memory/aggregate timing
must not be presented as a simultaneous best-of-80 online service. Such an adapter
and full quality/timing runs are pending. No speed matching or main-table version
selection is performed by these scripts.
