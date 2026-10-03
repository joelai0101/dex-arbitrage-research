# TRADER paper-aligned implementation

本版本依 TRADER 原文明確描述的機制實作，並揭露必要的正確性補充。
輸出名稱為 `TRADER-paper-aligned-v2`；它不是官方原版、不是 PR #16 的
局部修補版，也不代表已重現作者論文表格中的效能。

2026-10-03：v2 對齊 Algorithm 3 的逐邊控制流程，新增執行中 DP 與
pop/apply 軌跡檢查；小圖／多著色正確性檢查通過。原文未展開的狀態層
`apply` 仍是明列補足，不宣稱整套複雜度等價。未量測 v2 的 UNI 效能或正式 E2。

## 來源與變更範圍

- 主要證據：使用者提供的 IEEE 論文 *TRADER: Real-time Arbitrage Detection
  via Negative Cycles on Dynamic Graphs*，§IV–VI、Algorithms 1–4，PDF pp.4–9，
  DOI `10.1109/ICDE65706.2026.00141`。技術報告 §X 的刪除實驗是補充證據，
  不把它當成失效處理的完整偽碼。
- 本地原文摘錄：研究工作區 `6D/doc/extracted_pdf_text/TRADER_user_pdf_20260913.md`
  與 `TRADER_Technical_Report.md`。原始 PDF 保持唯讀，不放入本 repository。
- 程式基礎：本研究 repository 的 `a792c8e`，原
  `trader_paper_faithful/`（歷史標籤 `TRADER-paper-contract-v5`）。沿用已存在的
  全端點 DP、候選代表、失效索引及 DAG 排程，不宣稱本輪從零提出它們。
- v1 新增：原版失敗案例的具名測試、獨立於正式候選去重函式的環枚舉驗證、
  依 Definitions VI.1–2 不另加同色邊豁免、局部排程取邊、快取 C1 有向邊集合、
  跨平台檢查與 CI。
- v2 以 v1 的 `44fd2a8` 為依賴，只修正 Algorithm 3 的實際執行時機、
  未改權重的誘導邊 apply、相關回歸與版本標籤。完整路徑、witness 索引、
  EG 判定、候選代表與多著色常駐契約不在這輪重設範圍。
- `paper_batch_scheduler.*` 與 `paper_batch_reference_model.*` 保留來源版本；
  後者包含圖結構及獨立 oracle。歷史的 `CorrectnessFirstBatchMaintainer`
  仍在來源中，但正式 `Engine`／串流 driver 不呼叫它或窮舉 oracle。

## 原文到程式的對照

| 原文機制 | 本版本執行路徑 | 驗證 |
|---|---|---|
| §IV-A：端點／顏色集合的最小路徑 DP | `Engine`，`StateKey(source,destination,colors)`；不採最小頂點根限制 | 每次維護後，與獨立簡單 colorful 路徑 DFS 核對完整保留狀態及權重 |
| Algorithm 1：以權重排序的雙向增量傳播 | `apply_single` → `propagate_priority`；只將改善標籤繼續傳播 | 單邊模式 `algorithm1_calls>0`、DAG pass 為 0；混合更新後核對狀態 |
| Algorithm 2：貪婪、邊互斥的 DAG 分解 | `decompose_into_dags`；依總度數、BFS、加入前檢查環 | 有環輸入分解後，每條排程邊恰好出現一次且每個 DAG 無環 |
| §V Definition V.1、Algorithm 3：合併、拓樸雙向批次 | 每個 DAG 先 forward 再 backward；每次 pop 後完成該邊 apply，才釋放相依邊 | 核對真實 pop/apply 軌跡與中途 DP、所有前驅／後繼完成條件、未更新的誘導邊與合法排序變化 |
| §VI：C1 與其餘候選的可更新最小排序，取得 C2 | 受影響的 DP 閉合代表 → 旋轉去重 → `ranking_`；前兩個不同環產生 gap | 獨立枚舉全部 colorful 環核對前兩個權重、同權不同環、旋轉去重與共用 DP 狀態反例 |
| Definitions VI.1–2、Algorithm 4：EG | `Grouped`，快取 C1/gap，累積 C1 外降權及 C1 上增權；新邊或累積量嚴格大於 gap 才觸發一般維護 | 等於 gap 可延後、超過則整批刷新；新邊、重複更新、同色邊與實際有向邊歸屬 |

這是機制對照，不是宣稱每個內部步驟都可逐行照抄原文。特別是下列補充
會影響實際工作量，因此必須保留在方法說明中，不能省略後直接報作官方版。

## 必要補充與明確選擇

1. **增權／刪除失效。** 原文 §IV-B 要求處理這些更新，但只靠
   `min(old,new)` 不足以替換已變差的路徑。本版以邊到已選見證的索引找到
   失效狀態，依顏色集合大小重新評估；後續改善再傳播。沒有每次重建全圖。
2. **Algorithm 3 的控制流程與狀態層 `apply`。** v2 的外層直接依
   Lines 7–18 執行 `pop → apply → release`；`apply_ready_edges` 必須等待
   DP callback 返回，才將該邊計為完成並解鎖相依邊。v1「整個方向先收集
   種子、最後才 drain」的方式已移除。每條有效、異色的誘導邊都使用目前
   權重執行 apply，包括該批未改權重的邊；刪除或同色邊只完成結構排程。
   原文未展開狀態層 apply。本版保留合併後批次最終圖與失效修復，對每個
   popped edge 的種子，先按指定方向延伸，再完成較大顏色層的雙端點傳播；
   狀態前沿在該邊 apply 內清空後才返回。這不是再次執行 Algorithm 1 的
   權重 PQ，但仍是本研究的明列補足。**同一 DP 狀態可能在同一 DAG pass
   的不同 edge apply 中再被改善；未證明原文「每個狀態每 pass 至多一次」
   或原文時間上界。**控制流程測試與最終答案測試不能代替這項證明。
3. **批次依賴圖。** 採 §V Definition V.1 的頂點誘導版本：更新端點間的
   原有邊也參與排程。Algorithm 3 直接寫入更新集合的簡寫存在解讀空間，
   此處固定一種並公開；不以測量結果事後挑選。刪除邊仍可作為該批結構依賴。
4. **精簡候選代表。** 每條閉合邊維持一條最小 full-color 路徑代表，
   而非列舉全部環。其前兩個權重完整性證明如下；這是本研究的實作補充，
   不是把證明歸給原作者。C1 保留在同一排序集合的首位，C2 取下一個不同環；
   其查詢語意等同「C1 加其餘候選 PQ」，資料結構為可更新的有序集合。
5. **無閉合邊的終端狀態。** 保留所有較短的端點／顏色狀態，但省略沒有
   閉合邊的 full-color 狀態；插入閉合邊時再建立。它們不能再延伸，也不能
   產生當前候選，因此不影響較短狀態或前兩個環。這是揭露的儲存最佳化。
6. **串流介面。** 每個著色實例獨立 EG，driver 每筆到達取各實例的最佳
   答案。延後期間只沿 C1 讀取當前邊權重，避免回報舊價格；檔尾刷新 pending
   更新。無候選時的有效更新，以及刪除 C1 邊時，即使 gap 無限大也立即維護。
   這些邊界處理、EOF 與多實例彙整都是明列的介面選擇。

### 為什麼一個閉合代表仍能保住 C2？

假設是簡單有向圖、固定著色、恰好 k 個不同頂點的 colorful 環，且所有
需要的全端點 DP 狀態都正確。將同一環的旋轉視為同一個環。

- 對任一最佳環選一條邊作為閉合邊，該端點對的最小 full-color 路徑加上
  此邊，不會比最佳環更差，因此代表集合含有一個真正最佳環 C1。
- 任一不同的次佳環 C2 至少有一條不在 C1 的有向邊 e。以 e 閉合時，
  其 DP 代表不比 C2 差，而且含有 e，故不可能就是 C1。
- 因此代表集合至少含一個不比真正 C2 差的不同環；又不可能比真正的
  次佳權重更小，所以排序中的第二個權重就是正確的次佳權重。同權的不同
  環會給 gap=0，不要求挑選出字典序上指定的那一個 C2。

此論證不適用於把 DP 限制為「只有最小頂點能當根」的版本，也不表示代表
集合枚舉了所有環。測試中的全部環枚舉只作獨立 oracle，不在 driver 更新路徑。
這是精確算術下的結構論證；程式用 `double`，測試另核對數值容差。

### 動態更新與 EG 的不變量

以下是本實作的正確性論證與測試目標，不是引用作者未提供的完整證明。

- **維護完成時的 DP：**每個保留狀態等於該端點／顏色集合的最小路徑權重。
  增權或刪除若影響已選見證，反向索引會標記該狀態；若未影響，原見證仍
  是有效路徑。先按較小顏色集合修復失效路徑，再由已更新邊雙向傳播改善。
  混合批次的改善可能在修復後才出現，故不宣稱修復階段已得到全部最小值。
  所有延伸都增加一種顏色，狀態依賴不會因負權邊形成無限鬆弛迴圈。
- **EG 延後期間：**以最近維護時的 C1 和真實 gap 為錨點。對任何其他環 C，
  一筆更新讓 `w(C)-w(C1)` 減少的量，不會超過 Definition VI.1 累積的
  不利變化。只累加、不扣回相反方向的變化，是保守界。累積量不超過 gap
  時，C1 仍是最優之一；超過則維護整個 pending 批次。C1 的回報值另從
  live graph 重算。新邊、無答案與刪除 C1 的邊界則按前述規則立即處理。
- **驗證方法：**每次維護檢查完整保留 DP 與前兩個不同環；每次 EG 到達
  檢查 live graph 上的答案，包括延後期間。批次排序不變性另外測試，
  不能以只看最終最佳權重來掩蓋錯誤 DP 或錯誤觸發時機。

## 支援範圍與效能界線

- 一對有向端點只有一個有限權重，無 self-loop，k=2..20；刪除以 `D` 表示。
- 輸入著色固定，檔案按頂點 ID 0,1,... 列出顏色。必須預先涵蓋所有可能
  出現的更新端點，包括尚未出現在邊中的頂點。這是可重現 benchmark 介面，
  **不是**任意新 ID 到達時線上抽色的完整 Operation 1 服務。
- `N` 是無效應到達：計入到達數與固定批次邊界，但不寫入 pending 更新。
- 固定著色域內的最優不代表無顏色限制的全域最優。不同環同權時可保留
  任一合法最優見證；不要求與其他實作的路徑 ID 完全相同。
- EG 的同色邊也依 Definitions VI.1–2 計算與觸發，再由 DP 排除不相容路徑。
  C1 成員判斷使用快取的真正有向邊，而非僅檢查兩端點是否出現在 C1。
- 排程只讀取批次端點的 outgoing 鄰接表；不是每次掃描全部圖邊。候選只
  更新 dirty closures；仍可能有某次更新實際影響很多狀態，不能保證每批很小。
- 原文的時間／空間上界不自動成為本程式的測量結果或已證明上界：本版
  保存完整見證與反向索引，需計入 O(k) 的路徑／索引因子；圖使用有序容器，
  查邊有對數成本；C1 回報重算是 O(k)。不宣稱整段介面達到每筆 O(1)。
- 初始化不計入 `online_ms`；online 包含更新解析、維護、查詢、輸出與 EOF。
  `core_ms` 不含輸入輸出。Windows peak working set 含初始化；非 Windows
  的 `peak_rss_mib=-1` 表示沒有量測，不是負的記憶體使用量。
- profile 與 release 必須逐位元產生相同軌跡。profile 計時不能替代正式
  release 效能，也不能把過去 v5 的耗時重新標成此版的結果。

## 執行與驗證

只需 C++17 編譯器與 Python 標準函式庫。完整小圖驗證：

```powershell
.venv/Scripts/python.exe .worktrees/trader-algorithm3-alignment/trader_paper_faithful/validate.py --compiler .venv/toolchains/llvm-mingw-20260616-ucrt-x86_64/bin/clang++.exe --output .research_data/common_benchmark/trader_algorithm3_alignment_20261003/new_run
```

輸出目錄必須尚不存在。其他平台可將 `--compiler` 換為 C++17 編譯器的
絕對路徑。Repository CI 在 Linux／macOS 執行同一驗證，不下載研究資料。
另可用 CMake 建置與 `ctest` 執行 C++ 單元檢查。

```text
release_driver.exe <case> <k> <ell> single 1 <trace.tsv>
release_driver.exe <case> <k> <ell> batch 7 <trace.tsv>
release_driver.exe <case> <k> <ell> eg 1 <trace.tsv>
```

case 內含 `graph.txt`、`updates.txt`、`colors.txt`、`colors_1.txt` 等。
圖／更新每列為 `u v weight`，更新另支援 `D` 和 `N`。EG 的最後數字 1
只是介面占位，不是維護組大小；結果明列 `fixed_batch_size=null`，並輸出
觸發原因、實際維護組大小直方圖與 DAG pass 數量。

### v2 本輪證據（2026-10-03）

- release 與 profile **各 548,106 項** C++ 檢查通過。包含保留 DP 狀態、
  見證合法性、前兩個不同環權重、混合增／降／插／刪及合法排程變化。
- 新增 4 個 Algorithm 3 gate：逐邊 DP apply 完成後才繼續、反向 apply
  確實更新前綴狀態、未改權重的誘導邊也被 apply、匯合相依條件與失敗邊界。
  原有 7 個具名 gate 與混合更新／獨立 oracle 檢查保留。
- 軌跡觀察器僅在單元測試的 `TRADER_TEST_HOOKS` 下存在，不進入正式 driver。
  同一 DAG 的測試前提由 fixture 明確檢查；不能要求跨 DAG 的固定邊順序。
- 獨立對照將 Engine 恢復成「整個方向收集種子後才 drain」，其餘 fixture
  不變，會在第 3 項檢查失敗：`must apply the previous edge before popping
  another`。這證明測試能攔截舊控制流程，而不是只核對預先計算的邊順序。
- k=2,3,4,5，各 8 組著色、60 筆更新，single／batch／EG 共 12 組情境；
  release/profile 共 24 次。每個輸出答案與獨立 Python permutation oracle
  核對，並檢查路徑、著色、當前權重與模式路由；兩建置軌跡逐位元相同。
- `validation.json` 記錄命令、來源 SHA-256、原始測試輸出與情境結果。
  本地通過證據在 `.research_data/common_benchmark/trader_algorithm3_alignment_20261003/green02/`；
  舊控制流程對照在同層 `red02/`。README 在本地測試後補齊數字；程式／建置
  檔雜湊不變，CI 另對整個最終提交執行相同驗證。
- 上述有限測試支持本次驗收，不是所有輸入的形式化證明。
  v2 尚未執行 UNI 效能／記憶體評估或正式 E2，不納入論文主效能表。
  v1 的 1／2 組著色試跑數字不得轉標為 v2，也不宣稱本修正會減少記憶體。

後續若進入實證，先使用新標籤與新輸出目錄做有界規模評估；官方原版、
局部修補版與本版必須分開。不得自行合併 PR 或覆寫既有論文數值。
