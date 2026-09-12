# GraphS paper-aligned experimental adapter

Status (2026-09-12): compilation, independent small-graph oracle/recoloring checks and driver smoke passed. UNI timing is under bounded pilot evaluation; no complete-stream performance claim yet. Evidence: `.research_data/common_benchmark/paper_alignment_20260912/validation.json` in the research workspace.

TRADER Section VII-A describes GraphS using a hot-point path index to enumerate t-to-s paths for an updated edge (s,t), adapting candidates to the weighted kMNC task. This driver uses one uncolored instance, k=5 and one answer per observed update. It does not repeat GraphS over 80 color maps. `colors.txt` is used only to declare vertex count; its color values must not affect output.

The weighted adapter is copied from the user's previously repaired GraphS prototype (`6D/code/tools/graphs_repro/GraphSWeightedBenchmark.java`). Its HP-Index backend derives from third-party NemesLaszlo/GraphS-system, original commit 4a72bfdbbd8be3e3fe2a0921627b0ba9c721ded7 plus the user's repair branch. This is NOT Alibaba's production GraphS code or the TRADER authors' unpublished adapter. Build against the existing pinned backend and JGraphT 1.4.0; do not substitute a different search kernel.

Uncolored exact-k is the explicit common query definition. It searches a larger candidate universe than TRADER's 80-color union; this reflects their different algorithmic guarantees, rather than forcing identical internal work. Validate against the uncolored exact-k oracle, never require equality to a restricted color-union optimum. The paper's exact-k versus at-most-k wording should remain visible in the comparison contract.

HP threshold=40 is retained from the verified local backend and is NOT claimed as a parameter specified by TRADER. No per-dataset tuning to fit Table III. Java/JGraphT versus the paper's server/compiler environment remains a disclosure. Global candidate initialization and cache maintenance are explicit local completion choices.

The driver reports initialization separately and includes input, parsing, maintenance, answer serialization and final flush in online time. A post-timing stdin handshake permits the supervisor to capture Windows process peak memory, including JVM/native allocations. Do not include handshake waiting in detection time.

Acceptance: independent small-graph oracle after every update, invariance under recoloring the same graph, full input/output counts, no 80-instance multiplier, then UNI prefix and complete-stream runs. Paper GraphS references are 37.00, 33.00, 49.98, 46.95, 58.94, 85.69 ms/update (TRADER Table III). They are diagnostic references, not substitute measurements or required pass/fail answers.
