# TRADER EG localized repairs and regression

This diagnostic targets the weight-overwrite defect in upstream commit
`8e047fdf35e8c44f189a59f506431b4a180124ca`. It uses locally supplied frozen
service sources and does not redistribute upstream source code or datasets.

The patch preserves the incoming weight while looking up an existing edge.
It changes both copies of that lookup: the native update loop and the extracted
persistent-service loop. It is identical to the existing `oldnew` diagnostic
variant, not a new EG algorithm or a complete repair of all known defects.

The optional `--witness-fix` stage additionally includes the predecessor's color
in backward-search states and sends destination-zero updates through the normal
graph-update path. These are the two changes from the existing `minpatch`
diagnostic, applied after the `oldnew` repair. The default still tests only the
original weight-accounting repair.

The regression compiles the actual original and patched service against the
same fixtures. The original must fail the weight-accumulation checks; the patch
must pass them. Test-only accessors observe pending updates and accumulated
decrease. Some fixtures set the gap explicitly to isolate this fix from the
known runner-up/cycle-gap defect; a separate witness reports the native gap.
These accessors are disabled in the UNI1 replay binary.

Run from the research workspace, with its existing local frozen inputs:

```powershell
.venv/Scripts/python.exe .worktrees/trader-eg-weight-fix/scripts/trader_eg_weight_fix/verify_weight_fix.py --root . --output .research_data/common_benchmark/trader_eg_weight_fix_20261003/run01 --replay-uni1
```

The output directory must be new. Original sources, prior results, seeds and
reference traces are read-only and checked before/after. UNI1 uses the same
7,628 updates, 80 official colorings, k=5 and EG mode as the frozen E2 run.
The full replay is a single correctness diagnostic, **not a formal timing run**.
The checker distinguishes legal paths, matching reported weights, declared
coloring validity, and global optimality. Global optimality is not required of
color coding. A passed accounting test alone does not accept the whole baseline.

Required local artifacts come from `scripts/trader_official_dual` at project
commit `e11fa93fee25cb1fcb636b67b9f3ab67a2bf2f1b` and the frozen external protocol
`20261002T132042_994973Z`. The existing service driver is reused byte-for-byte.
No E0/E1/E3/E4 results, formal E2 tables, or thesis numerical results are changed.

## 2026-10-03 第一階段：權重覆寫修補

新、舊權重分離的最小修補已通過驗證，但整體 EG 基線尚未通過驗收。

- 實際 C++ 服務的 14 項小型回歸檢查：原版 4 項失敗，修補版全數通過。
- Python 品質檢查器的 5 項單元測試通過。
- 完整 UNI1 品質重播：7,628 筆更新、80 組官方著色、k=5、EG 開啟。
- 原始來源、舊結果、種子、參照及輸入檔案未改動；本輪未重跑正式 E2。

| UNI1 檢查 | 原版既有軌跡 | 本輪最小修補版 |
|---|---:|---:|
| 合法路徑 | 7,628 | 7,628 |
| 回報權重不一致 | 936 | 936 |
| 合法且回報權重一致 | 6,692 | 6,692 |
| 不符合其宣告的官方著色 | 100 | 113 |
| 同時符合路徑、回報權重及宣告著色 | 6,592 | 6,579 |
| 路徑重算值達全域最優 | 7,608 | 7,628 |

最後一列不表示答案整體正確：離線重算值正確，仍可能同時帶有過期的
回報權重或不符合其宣告著色。著色檢查使用官方 C++ RNG 匯出的
`UNI1_all_arrival_colors.json`，不是本研究另一份 common80 顏色表。

兩版的 936 筆權重不一致位於相同到達列。第一筆是第 6,693 列：
路徑 `0 249 1 198 39 0`，回報 `-4.886413756064391`，當前圖重算為
`-4.885149062713739`。因此不能把該批問題全部歸因於此次修補的覆寫錯誤。

另有獨立的兩環反例：兩個合法、符合固定著色的環初始權重為 -10 和 -5，
次佳環的一條邊由 -1 降至 -12 後，最佳值應為 -16。修補版正確累積降權量
11，卻仍因原生差距為無限大而延後更新，回傳 -10。這是不同於變數覆寫的
候選差距問題；本次沒有用全圖重算或其他演算法替換 EG。

診斷產物位於研究工作區：

- `.research_data/common_benchmark/trader_eg_weight_fix_20261003/run03/regression.json`：最終 14 項回歸。
- `.research_data/common_benchmark/trader_eg_weight_fix_20261003/run02/summary.json`：單次完整 UNI1 重播。
- 同一 `run02` 的 `weight_fix.diff`、`trace.tsv` 及兩版 `*_failures.json`：修補及逐列證據。

`run01` 的編譯器被 sandbox 拒絕執行，未進入測試；`run02` 在允許的
執行環境完成編譯及重播。後續 `run03` 只補跑小型回歸，加入示範兩環
皆符合著色的檢查與凍結協定核對，沒有再跑完整 UNI1。

## 2026-10-03 第二階段：反向著色與終點 0 更新

本階段修好兩個局部錯誤，UNI1 的回報權重不一致與著色違規均降為 0；
但候選差距反例仍失敗，因此整體 EG 基線仍未驗收。

1. `backword_dfs` 在建立前驅狀態前未加入前驅顏色；現在先加入，
   處理完該前驅後一定移除，避免錯誤遮罩或污染下一個分支。
2. `process_dynamic_batch` 對終點 0 的特殊分支只改 DP、沒有更新圖。
   現在所有終點都走既有 `update_edge_weight`；相同顏色的邊仍更新圖，
   但不加入 colorful 路徑。

執行指令（輸出目錄必須不存在）：

```powershell
.venv/Scripts/python.exe .worktrees/trader-eg-weight-fix/scripts/trader_eg_weight_fix/verify_weight_fix.py --root . --output .research_data/common_benchmark/trader_eg_witness_fix_20261003/run01 --witness-fix --replay-uni1
```

新增 4 項回歸：反向狀態含起點顏色、終點 0 的圖權重更新、終點 0 的
答案權重更新，以及同色邊指向 0 時仍更新圖。三版均執行相同的 18 項檢查：
原版 8 項失敗、只有權重覆寫修補的版本 4 項失敗、兩階段修補版全數通過。

| UNI1 檢查 | 原版既有軌跡 | 第一階段修補 | 第二階段修補 |
|---|---:|---:|---:|
| 合法路徑 | 7,628 | 7,628 | 7,628 |
| 回報權重不一致 | 936 | 936 | 0 |
| 不符合其宣告的官方著色 | 100 | 113 | 0 |
| 同時符合路徑、回報權重及宣告著色 | 6,592 | 6,579 | 7,628 |
| 路徑重算值達全域最優 | 7,608 | 7,628 | 7,628 |

三欄使用同一凍結協定、輸入與官方著色；第一階段欄引用其已完成的單次
重播，第二階段另做一次完整品質重播。這不是效能測量，也不代表其他
資料集或所有合法更新序列都已正確。原始來源、輸入與舊結果雜湊均未改動。

第二階段產物：

- `.research_data/common_benchmark/trader_eg_witness_fix_20261003/run01/summary.json`
- 同目錄 `regression.json`、`witness_fix.diff`、`trace.tsv`、`witness_fixed_failures.json`。
- `witness_fixed_failures.json` 為空陣列；重播程式 SHA-256 為
  `5f5f1a818639bb3c5aacc5bd61e9791ec3001609f4f9b89b976852afd7d897fa`。

重播後將 JSON 中的等價性欄位名稱改為
`weight_stage_matches_existing_oldnew_source`，只表示第一階段與既有
`oldnew` 來源相同；沒有變更測量值，原始 stdout 保留當時的舊欄位名。

### 尚未解決：C1–C2 候選維護

兩階段修補版在兩環反例中仍回傳 -10，而當前最優應為 -16：累積降權量
正確為 11，但原生 gap 仍為無限大，更新被延後。這項反例獨立記錄於
`native_gap_witness`，不算在上述 18 項局部修補的通過項目中。

論文 §VI（Definition VI.2、Algorithm 4，以及 “Extraction of w(C1) and
w(C2)” 段）描述以最佳環 C1 與其他候選環的優先佇列維持次佳環 C2；
官方程式的 `dp_search_k_cycle` 卻只在找到更好的紀錄時，將前後兩個
最佳值的差填入 `batch_weight_threshold_`。那不必然是目前 C1–C2 差距。

也不能只掃描每個 DP 狀態的一個最小值來找 C2：既有反例的兩個不同環
權重為 -10、-9，卻共用結束狀態 `(0, 4, 31)`；單一最小值會丟失次佳環。
此結構反例及增權後未切換到較佳環的既有診斷位於
`.research_data/common_benchmark/trader_official_dual_20260913/minpatch_gaps_20260914/diagnosis.json`。
本階段未修改該候選表示或增權失效處理，也未重新執行那份較早的診斷。

因此下一階段涉及候選表示、去重，以及增權後的失效／重算方式，不能
宣稱是再改一個變數即可完成。此 PR 保留 `baseline_accepted=false`，
不以全圖重算或另一套演算法替換 EG；未重跑正式 E2，未改論文結果表，
未合併至 main。
