# TRADER EG old/new-weight regression

This diagnostic targets the weight-overwrite defect in upstream commit
`8e047fdf35e8c44f189a59f506431b4a180124ca`. It uses locally supplied frozen
service sources and does not redistribute upstream source code or datasets.

The patch preserves the incoming weight while looking up an existing edge.
It changes both copies of that lookup: the native update loop and the extracted
persistent-service loop. It is identical to the existing `oldnew` diagnostic
variant, not a new EG algorithm or a complete repair of all known defects.

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

## 2026-10-03 驗證結果

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

後續應另外處理候選差距、過期回報權重與見證著色問題，再評估正式 E2。
此 PR 只驗收權重覆寫修補及診斷程序，不宣稱完整修復 TRADER。
