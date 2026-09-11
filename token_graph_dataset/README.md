# Small on-chain token-graph datasets

從 Ethereum Uniswap V2 `Sync` 紀錄重建小型 DELTA 資料集，並提供五代幣唯讀 RPC 蒐集器。使用真實鏈上觀測的準備金，不隨機生成市場權重，也不修改資料來植入負環。`build`／`verify`／`verify-cover` 離線執行，只有明確選擇 `capture` 才連網，所有模式都不送交易。

只依賴 Python 標準函式庫與 repository 內的 DELTA；不匯入封存研究模組。原始市場資料與產出不隨 Git repository 提供。可先擷取新的 RPC 紀錄，或準備符合下列 CSV 契約的保存資料夾，不能把作者 UNI 檔案直接當成這裡的來源。

## 五代幣 RPC 與 k=4／5 驗證

```sh
python -m delta_terminal build
python -m token_graph_dataset capture --blocks 100 --output NEW_CAPTURE
python -m token_graph_dataset verify-cover --source-json NEW_CAPTURE/source.json --k 4 5 --output NEW_COVER
```

在隱藏提示中輸入 HTTPS RPC URL，或由程序環境變數 `DELTA_RPC_URL` 提供。空白即取消，不連線、不建立輸出。沒有預設或自動切換的 provider；不要把含金鑰的 URL 放在命令列或 Git。需要 Ethereum mainnet 的 `eth_chainId`、`eth_getBlockByNumber`、歷史 `eth_call` 及 `eth_getLogs`。每次 2–100 區塊、最多 256 次請求、間隔至少 2 秒、單次逾時 15 秒；錯誤立即停止，不自動重試。

預設事前固定 USDC、USDT、DAI、WETH、WBTC，依 [Uniswap token list](https://github.com/Uniswap/default-token-list/blob/main/src/tokens/mainnet.json) 設定地址與 decimals，再於起始區塊向合約核對。查詢官方 V2 Factory 的全部 10 組兩兩配對，保留所有存在的池，不依價格或是否有負環篩選。`--tokens` 可指定同 schema 的五個不同代幣；第一輪驗收不在看到結果後改選代幣。

未提供 `--start-block` 時，區間為擷取開始所見 finalized 高度往前共 N 個區塊。保存並核對區塊鏈結、finalized 錨點及起訖 hash。以起始區塊末 `getReserves` 初始化，每 10 區塊擷取一次後續 Sync，最後將事件重建的期末準備金與期末 `getReserves` 比較。10 區塊分批符合 [Alchemy 免費方案的目前單次範圍限制](https://www.alchemy.com/docs/chains/ethereum/ethereum-api-endpoints/eth-get-logs)。**不將 eth_call 初始化值偽裝成 Sync 事件，也不捏造 PairCreated 紀錄**；池身分由該起始區塊的 Factory `getPair` 及池 `token0/token1` 核對。

`NEW_CAPTURE/rpc_responses.jsonl` 保存成功 RPC 回應的 JSON envelope 與對應公開查詢參數（不是逐位元網路封包，不含 URL）。`status.json` 記錄範圍、請求數、耗時與完成／失敗狀態；只有全部擷取與重建核對成功才產生 `source.json`。原始回應提供可稽核性，但單一 provider 的 logs／eth_call 一致不是獨立多來源或密碼學完整性證明。

完整著色覆蓋只供這個五節點小圖：對每個 k 節點子集建立一組子集內顏色互異的固定著色，再移除重複設定，因此 k=4 有 4 組、k=5 有 1 組。每個 exact-k 環必被某組涵蓋；這個保證來自子集覆蓋，不是依 oracle 答案挑著色，也不是一般大圖的高效率策略。

每組執行獨立 DELTA 增量重播，核對限制 oracle；再合併各組見證並逐狀態核對全圖 oracle。Oracle 以精確準備金分數乘積排序，另外報告浮點權重與精確乘積是否相同、真正的費後負環狀態數。所有 `color_XX` 資料夾皆可用 `delta_terminal offline` 重播；`k4/summary.json`、`k5/summary.json` 保存每個狀態的全圖最佳見證，最上層 `summary.json` 為摘要。

也可只產生單一固定著色 case：

```sh
python -m token_graph_dataset build --source-json NEW_CAPTURE/source.json --k 5 --output NEW_CASE
```

`source.json` 已固定區間，不與 `--blocks`／`--start-block` 混用。真實市場找到負環、驗證最優性、以及比 baseline 更有效率是不同證據；本工具不把合成 fixture 的陽性結果當成市場發現。

## 執行

以下命令在 Git repository 根目錄執行，`SOURCE` 指向已保存的來源資料夾，輸出必須使用新路徑：

```sh
python -m token_graph_dataset build --source SOURCE --blocks 100 --output NEW_CASE
python -m delta_terminal build
python -m token_graph_dataset verify --case NEW_CASE --output NEW_VERIFICATION.json
python -m delta_terminal offline --case NEW_CASE --output NEW_TERMINAL_OUTPUT
```

預設起點為來源第一個觀測區塊，`--start-block` 可以明確指定起點，但該區塊必須有每個池的歷史 `getReserves` 核對值。初始圖是起點的**區塊末狀態**，更新從下一區塊開始，避免把第一個區塊的事件重播兩次。`--blocks 100` 因此包含 1 個初始區塊與其後 99 個區塊。

保存紀錄重建範圍：Ethereum mainnet、Uniswap V2、固定 997/1000 費率、1–10 個池、最多 10 個代幣、1–1,000 區塊、最多 10,000 筆更新 Sync。小圖枚舉驗證另限最多 1,000 個交易批次、`k=2–5` 且代幣數至少 k。預設 `k=3`。這是功能與正確性檢查，不是大規模效能測試。

## 保存 CSV 的來源契約

來源是已解碼的鏈上紀錄 CSV，不是完整 RPC JSON 原始封包。保留地址、hash、事件位置與整數準備金；空白準備金不視為零。所有 CSV 使用 UTF-8，可有 BOM。必要欄位如下，額外欄位保留於 `source.json`：

| 檔案 | 必要內容 |
| --- | --- |
| `block_metadata.csv` | `block_number, block_hash, parent_hash`，完整涵蓋所選區間 |
| `pool_metadata.csv` | `pair_address, chain_id, dex_name, token0_address, token1_address, token0_symbol, token1_symbol, token0_decimals, token1_decimals, fee_numerator, fee_denominator, factory_get_pair_verified, creation_event_verified, creation_event_pair_address, creation_block, creation_transaction_hash` |
| `pool_events.csv` | `block_number, block_hash, transaction_hash, transaction_index, log_index, pair_address, event_type, removed, reserve0_raw, reserve1_raw`；包含每個池起點以前或起點內的初始化 Sync，以及所選後續區間的全部 Sync |
| `pool_state_snapshots.csv` | `chain_id, block_number, pair_address, token0_address, token1_address, reserve0_raw, reserve1_raw`，每個區塊每個池一筆，用於重建一致性核對 |
| `archive_state_checks.csv` | `block_number, pair_address, historical_call_reserve0_raw, historical_call_reserve1_raw, archive_call_status`；起始區塊每個池皆須為 `available` |
| `run_metadata.json` | `chain_id: 1, dex_name: "Uniswap v2", finality_tag: "finalized", finalized_block_at_start, start_block, end_block, run_completed_at_utc` |

來源布林欄位使用 `True`／`False` 字串；`event_type` 為 `Sync` 的列才改變準備金。池識別核對依據是來源記錄的 Factory／PairCreated 驗證，這個離線工具不重新向鏈上查詢。準備金為 `uint112`，代幣 decimals 為 0–36。拒絕重複／平行池、重複 log、removed log、衝突交易位置、區塊 hash 不符、不連續區塊與缺少初始化狀態。

## 圖與更新語意

- 節點依代幣地址排序給 ID；每個池建立兩條有向邊。
- 費後邊際匯率為 `(997/1000) × reserve_out/reserve_in × 10^(decimals_in-decimals_out)`，權重為負自然對數。這不是有限交易量報價。
- 依 `block_number, transaction_index, log_index` 排序。同一交易內，全部選定池的最後 Sync 值及兩個方向一次安裝，再回答；不對交易中途的暫態回答。
- 零準備金刪除池的兩條邊，之後有有效準備金可以重新插入。無 Sync 的區塊沿用已知狀態，不建立假的更新；這是合約狀態持續，不是插值。
- 每個區塊末與保存的池快照比較，另比較範圍內可用的歷史 `getReserves` 整數值。池快照可能與事件來自相同上游，不能把所有快照比較都稱為獨立鏈上查證。區塊末一致也無法排除同一區塊內漏掉、但不改變最後狀態的事件；完整性仍依賴來源蒐集紀錄。

官方語意依據：[Uniswap V2 Pair 合約的 Sync／_update](https://github.com/Uniswap/v2-core/blob/master/contracts/UniswapV2Pair.sol)、[Ethereum JSON-RPC 區塊與事件介面](https://ethereum.org/developers/docs/apis/json-rpc/)。

## 輸出與驗證

`NEW_CASE` 包含標準 `colors.txt, graph.txt, updates.txt, schedule.txt, metadata.json`，可直接離線重播。額外的 `source.json` 保存來源切片，包含初始化紀錄、所選區塊、事件、快照及歷史核對值。來源五份 CSV 的 SHA-256 用來辨識此次輸入版本；不是鏈上真實性證明。

驗證先從 `source.json` 重新建圖，與磁碟 case 精確比較，再執行 DELTA。獨立 oracle 以完整排列枚舉恰好 k 條邊的簡單有向環，分別求固定著色限制與全圖最小值；以原始整數準備金的精確分數乘積排序，再重算各環的浮點權重，避免僅憑浮點近零負號或相等值解讀訊號。DELTA 權重及見證比較採 `abs=1e-10, rel=1e-10` 容差，精確乘積相等另列一欄，不把容差內相符冒充精確相等。

一般 `build` 顏色固定為 `node_id % k`；三個代幣、k=3 時涵蓋全圖三跳環，較大圖不保證全圖覆蓋。`verify-cover` 使用上方的五節點完整子集覆蓋。驗證分開回報 `restricted_matches`、`global_matches` 與負環狀態數，沒有負環是有效結果。時間欄位僅作執行紀錄，重播一致性比較應排除 `update_ms`／`query_ms`。

負環不等於可成交淨利；未納入滑價、交易量、gas、MEV 競爭與執行。舊三池 pilot 不支持 k=4／5；新五代幣功能仍須以當次真實擷取結果驗收，不能僅憑測試通過推論市場全面泛化或 UNI 等級規模的效能。

## 測試

```sh
python -m delta_terminal build
python -m unittest token_graph_dataset.tests.test_dataset token_graph_dataset.tests.test_collect delta_terminal.tests.test_terminal -v
```

測試 fixture 是明示的合成資料，只用來測試錯誤情境、負環、停用與重新啟用；不混入真實市場輸出。`sh scripts/demo.sh test` 也會執行這些離線測試。
