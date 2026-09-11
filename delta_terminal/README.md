# DELTA 終端機

提供離線圖與唯讀 RPC 兩個入口，共用同一個常駐 C++ DELTA 引擎；本版保留原有狀態遞推，不做演算法改版。

## 啟動

在 repository 根目錄使用專案 Python（本機為外層研究專案的 `.venv/Scripts/python.exe`）：

```powershell
python -m delta_terminal build
python -m delta_terminal
```

本機工作樹可直接執行 `delta_terminal/start.ps1`，它會向上尋找專案 `.venv`，不更動系統 PATH。選單提供離線範例／自訂圖、RPC 測試、編譯與退出。未建置時選 3；本次交付已在本機編譯。

也可使用非互動命令：

```powershell
python -m delta_terminal offline
python -m delta_terminal offline --case PATH_TO_CASE --k 5 --batch 100 --output NEW_OUTPUT
python -m delta_terminal rpc --blocks 2 --output NEW_OUTPUT
python -m unittest delta_terminal.tests.test_terminal -v
```

RPC URL 由隱藏輸入或 `DELTA_RPC_URL` 環境變數提供；留空或只有空白字元直接取消，不連線、不產生資料，也不自動改用 Pocket。不把完整 URL 放在命令列參數、設定檔或結果中。使用者可自行輸入 Alchemy、Pocket 或其他支援相同唯讀方法的 Ethereum HTTPS RPC。既有測試只驗證 Alchemy 成功，不代表其他 provider 當前可用。

## 兩種模式的界線

目前建議把 RPC 當成可溯源的圖資料來源，再用離線重播驗證 DELTA。未來若要真正持續更新，可以獨立加入區塊輪詢或 newHeads／Sync 訂閱；這是唯讀資料接收器，不需要先有交易 bot。mempool pending transaction 不是已完成的池儲備，還需要狀態模擬等額外工作，不是本版 RPC 模式的必要前提。參考 [Geth 訂閱文件](https://geth.ethereum.org/docs/interacting-with-geth/rpc/pubsub)。

- **offline**：讀既有代幣有向圖與更新，在相同回答邊界依序增量維護。不重新取 log、不改權重單位。
- **rpc**：當次連線擷取最近 N 個 finalized 區塊末儲備，驗證池代幣順序、decimals、區塊 hash 與相鄰 parent hash，形成新圖，再交給相同引擎增量回放；同時另存 `<output>_case`，可直接給 offline。也可用 `--start-block` 指定已 finalized 歷史起點，前提是 provider 支援該歷史狀態。

RPC 本版是**有限區塊擷取＋測試**，不是持續訂閱 mempool 或永久追蹤新區塊的交易 bot。每次預設 2 區塊、最多 64 請求，單一連線、請求間至少 2 秒、逾時 15 秒，錯誤立即停止，不自動重試。401／403／429 或不支援 finalized／歷史狀態時暫緩 RPC；離線功能仍可用。

預設使用已有研究 pilot 的 USDC、USDT、WETH 三個 Uniswap V2 池。可用 `--pools` 載入相同 schema 的其他 V2 池設定。限定 Ethereum mainnet、每個代幣 pair 一個池、固定 997/1000 費率；拒絕重複／平行池，不默默折疊。不支援 V3 或其他費率 AMM。零儲備明示為池停用，轉成刪邊；缺失／無法解碼回應則失敗，不補值。

代幣以地址排序給 ID；RPC 模式顏色為 `id % k`，只有一組固定著色。三代幣 k=3 涵蓋兩個方向的三跳環；更大的圖不保證覆蓋所有無著色環。這不是正式主比較的 80 組著色服務。

同區塊費後邊際匯率為 `(997/1000) × reserve_out/reserve_in × 10^(decimals_in-decimals_out)`，邊權取負自然對數。負環只是邊際價格訊號；交易量、滑價、gas 與實際執行未納入，程式不持有錢包、不簽名或送交易。

API／合約依據：[Ethereum JSON-RPC 區塊參數](https://ethereum.org/en/developers/docs/apis/json-rpc/)、[Uniswap V2 Pair 合約](https://github.com/Uniswap/v2-core/blob/master/contracts/UniswapV2Pair.sol)。

## 離線資料契約

每個 case 目錄包含：

| 檔案 | 格式 |
|---|---|
| `colors.txt` | 每個節點一個整數顏色，0 到 k−1；行序即節點 ID |
| `graph.txt` | `u v weight`；有限權重，絕對值不超過 1e100；不接受重複有向邊 |
| `updates.txt` | `u v weight` 設定／插入；`u v D` 刪除；`u v N` 無作用事件 |
| `schedule.txt` | 可選，嚴格遞增的累積更新列號；末值必須等於更新數 |
| `metadata.json` | 可選，`k` 與節點標籤／來源；RPC 匯出另存原始整數儲備與區塊 hash |

沒有 schedule 時逐筆回答；`--batch` 明確覆寫 schedule。同批內同邊採最後一個非 N 操作，整批最終權重安裝後才修復狀態。N 不會取消前面的 S／D。固定節點目錄、k=2–10、固定著色；沒有候選回 `null`，非負最佳值仍會回傳。

終端顯示前 10 筆、每 1,000 筆與最後一筆；**全部答案**均在 `results.json`。輸出目錄必須是新目錄；中途失敗標示為「失敗／中止」，不冒充成功結果。

## 跨平台啟動

跨平台 demo 集中在 repository 的 [scripts/](../scripts/README.md)。macOS／Linux 以 Python 3.12+ 與 C++17 Clang／GCC 重新編譯；不要複製 Windows `.exe` 或 DLL。Windows 保留 `start.ps1`，其他平台使用 `sh scripts/demo.sh`。

## 是否需要 SOLID／Design Pattern／Clean Architecture 重構？

需要有限分層，不需要全案重寫或新增框架：

| 層 | 責任 |
|---|---|
| `native/delta_engine.hpp` | 原已驗證演算法，不依賴 UI、檔案與 RPC |
| `native/main.cpp`、`engine.py` | 常駐程序與批次協定 adapter |
| `model.py`、`rpc.py` | 共用輸入模型、檔案及 RPC 轉接 |
| `app.py` | 執行協調、SessionViewModel 與結果狀態 |
| `cli.py` | 終端輸入與畫面，不計算套利答案 |

採單一職責（Single Responsibility）、核心與外部 I/O 分離，以及輕量 Model–View–ViewModel（MVVM）；兩個資料來源收斂為同一 Case 契約。Adapter 僅用在實際程序／RPC 邊界，沒有為每個類別增加抽象介面、Repository、事件匯流排或 DI 容器。

原本實驗程式與 baseline 保留不動。`Lookup` 到 `DeltaEngine` 本體直接取自原 `delta_state_benchmark.cpp`，分離出必要型別，排除以 `#define main` 引入整份 benchmark 的耦合。編譯後須先通過小圖、原版 binary 與 RPC／離線回放測試；若不一致，停用新版本並修正新分支，原版仍可立即使用，不以破壞性 Git reset 回滾其他工作。

## 驗證

11 項測試涵蓋既有教學 fixture、12 個 seed × 3 批次模式的獨立窮舉核對、RPC fixture 匯出／回放、空白 URL 取消且不連線／寫檔、零儲備刪邊、hash 改變、輸入錯誤、請求上限、祕密遮罩及失敗狀態。原版 binary 比較可選：

```powershell
$env:DELTA_REFERENCE_EXE = 'PATH_TO_ORIGINAL_DELTA_EXE'
python -m unittest delta_terminal.tests.test_terminal -v
```

可用 `DELTA_REFERENCE_CASE` 指定已匯出的 RPC 小圖，再執行 `test_original_binary`；該測試含獨立 DFS，只應用於小圖，避免誤拿大圖做窮舉。

2026-09-11 Windows 本機驗收：11 項通過；新舊教學例的 9 個回答點完全一致；`sh scripts/demo.sh offline` 編譯並完成教學案例。Alchemy 區塊 25,952,744–25,952,745、3 池、21 請求成功；RPC 與離線兩個回答點之列號、權重及路徑完全相同，亦與原 binary／獨立 DFS 相符。最優權重均為 +0.007312742606632838，沒有負環訊號。這是功能測試，不是新的速度 benchmark。
