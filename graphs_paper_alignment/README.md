# GraphS paper-aligned experimental adapter

Status (2026-09-12): compilation, independent small-graph oracle/recoloring checks and driver smoke passed. UNI timing is under bounded pilot evaluation; no complete-stream performance claim yet. Evidence: `.research_data/common_benchmark/paper_alignment_20260912/validation.json` in the research workspace.

TRADER Section VII-A describes GraphS using a hot-point path index to enumerate t-to-s paths for an updated edge (s,t), adapting candidates to the weighted kMNC task. This driver uses one uncolored instance, k=5 and one answer per observed update. It does not repeat GraphS over 80 color maps. `colors.txt` is used only to declare vertex count; its color values must not affect output.

The weighted adapter is copied from the user's previously repaired GraphS prototype (`6D/code/tools/graphs_repro/GraphSWeightedBenchmark.java`). Its HP-Index backend derives from third-party NemesLaszlo/GraphS-system, original commit 4a72bfdbbd8be3e3fe2a0921627b0ba9c721ded7 plus the user's repair branch. This is NOT Alibaba's production GraphS code or the TRADER authors' unpublished adapter. Build against the existing pinned backend and JGraphT 1.4.0; do not substitute a different search kernel.

Uncolored exact-k is the explicit common query definition. It searches a larger candidate universe than TRADER's 80-color union; this reflects their different algorithmic guarantees, rather than forcing identical internal work. Validate against the uncolored exact-k oracle, never require equality to a restricted color-union optimum. The paper's exact-k versus at-most-k wording should remain visible in the comparison contract.

HP threshold=40 is retained from the verified local backend and is NOT claimed as a parameter specified by TRADER. No per-dataset tuning to fit Table III. Java/JGraphT versus the paper's server/compiler environment remains a disclosure. Global candidate initialization and cache maintenance are explicit local completion choices.

The driver reports initialization separately and includes input, parsing, maintenance, answer serialization and final flush in online time. A post-timing stdin handshake permits the supervisor to capture Windows process peak memory, including JVM/native allocations. Do not include handshake waiting in detection time.

Acceptance: independent small-graph oracle after every update, invariance under recoloring the same graph, full input/output counts, no 80-instance multiplier, then UNI prefix and complete-stream runs. Paper GraphS references are 37.00, 33.00, 49.98, 46.95, 58.94, 85.69 ms/update (TRADER Table III). They are diagnostic references, not substitute measurements or required pass/fail answers.

## Initial candidate-cache optimization

The first UNI1/16-update pilot exhausted its 120-second process budget after HP-Index construction, while building the global weighted candidate cache. It produced no online detection measurement. The adapter now constructs this initial cache by a single simple-path traversal per minimum vertex, accepting only closed exact-k paths; rotations are not enumerated repeatedly. The traversal reuses a path array and visited flags, materializing only complete candidates. This is an explicit local initialization choice, not a replacement for online HP-Index queries. The backend, online affected-path queries, topology updates and ranking maintenance are unchanged.

All 4920 small-graph/recoloring checkpoints now compare the complete candidate set and every candidate's weight as well as the optimal answer and path legality. They pass, along with the driver smoke. The six pinned backend class hashes and JGraphT jar hash are unchanged.

With identical graph/color/update hashes, the new UNI1/16-update pilot completed initialization in 27770.65 ms (candidate cache: 27217.37 ms), with 6963386 distinct uncolored exact-5 candidates. Online time was 17294.17 ms, or 1080.89 ms/update, and process peak memory was 3055.75 MiB. All 17 answer points match the independent global exact-5 oracle. Initialization and the post-timing handshake are excluded from detection time; this is one prefix pilot, not a formal multi-run result.

The pilot contains 8 N observations and 8 existing-edge weight changes, with no insertion. Online counters show 454444185 HP-index edge visits, 976 base-graph edge visits and 481664 returned-cycle canonicalization attempts. Thus the remaining cost is not initialization or an 80-instance multiplier. The backend's index traversal scans outgoing index paths before rejecting joins exceeding the remaining hop budget; length-aware index access is a concrete next investigation, not yet an implemented fix or a proven sole cause. The new online value remains far from the paper reference; the formal performance gate is not passed.
