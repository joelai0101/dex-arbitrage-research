# DEX 套利研究

[English](README.md) | [繁體中文](README.zh-TW.md)

本專案提供可重現的代幣圖實驗與去中心化交易所（Decentralized Exchange, DEX）循環增量維護工具；此版本包含 DELTA 終端機應用，以及 RICH／TRADER 資料稽核基礎。

## 目前可以執行什麼？

| 模組 | 已具備功能 | 說明 |
|---|---|---|
| DELTA 終端機 | 互動選單、離線圖重播、有限區塊唯讀 Ethereum RPC 擷取、答案一致性測試 | [終端機使用指南](delta_terminal/README.md) |
| RICH／TRADER benchmark | UNI1–UNI6 來源與資料稽核、實驗規範、結果格式 | [Benchmark 指南](rich_trader_benchmark/README.md) |
| 輔助實驗 | 範圍明確、可重現的研究實驗 | [實驗規則](experiments/README.md) |

其他尚未合併分支中的 benchmark 執行器、CCSS 評估、相依狀態剖析與歷史資料可行性工作，不自動包含於此版本。作者原始資料、外部 baseline 原始碼、編譯後執行檔及產生的結果均不隨 repository 提供。

## 快速開始：DELTA

需要 Python 3.12 以上，以及既有 C++17 編譯器。DELTA 僅使用 Python 標準函式庫，無須安裝終端 UI 或 Web3 套件。請使用專案虛擬環境；以下命令在 Git repository 根目錄執行。

~~~powershell
# 先啟用專案環境，或把 python 換成該環境的完整執行檔路徑。
python -m delta_terminal build
python -m delta_terminal
~~~

選單提供離線資料、RPC 擷取／測試、重新編譯與結束。既有 Windows 研究工作區可直接執行 [start.ps1](delta_terminal/start.ps1)，它會向上尋找專案 `.venv/Scripts/python.exe` 並啟動選單。

若編譯器未被自動找到，可明確指定：

~~~powershell
python -m delta_terminal build --compiler "C:\path\to\clang++.exe"
~~~

### 離線模式

~~~powershell
python -m delta_terminal offline
python -m delta_terminal offline --case "C:\data\token_case" --k 5 --batch 100 --output "C:\results\new_run"
~~~

每個案例目錄包含 `colors.txt`、`graph.txt`、`updates.txt`，以及可選的 `schedule.txt`、`metadata.json`。更新可設定權重、刪除邊（`D`），或記錄無作用事件（`N`）。未指定 `--batch` 時保留既有 schedule；沒有 schedule 時逐筆回答。詳見[輸入契約](delta_terminal/README.md#離線資料契約)。

終端畫面只顯示部分答案；`results.json` 保存全部答案、對應路徑與引擎計數。每次請使用新的輸出目錄，既有結果不會被覆蓋。

### RPC 模式

~~~powershell
python -m delta_terminal rpc --blocks 2 --output "C:\results\new_rpc_run"
~~~

在隱藏輸入提示中貼上 HTTPS RPC URL，或透過程序環境變數 `DELTA_RPC_URL` 提供。輸入空白則使用設定的 Pocket 公開入口。不要把供應商金鑰提交到 Git，或放入命令列 URL 參數。

此模式擷取有限個已 finalized 的 Ethereum 區塊末快照，再對產生的圖進行增量重播，不是持續訂閱 mempool。預設三個 Uniswap V2 池（USDC／USDT／WETH）、兩個區塊、一組固定著色與 `k=3`。每次最多 64 次唯讀請求，間隔至少兩秒，不自動重試。RPC 不可用時暫緩該模式，離線功能仍可使用。

擷取結果另存為 `<output>_case`，保留區塊 hash 與原始整數儲備量；可用相同輸入離線重播：

~~~powershell
python -m delta_terminal offline --case "C:\results\new_rpc_run_case" --output "C:\results\rpc_replay"
~~~

可用 `--pools` 指定相容池設定；若供應商提供對應歷史狀態，可用 `--start-block` 指定已 finalized 的歷史起點。轉接層假設 Uniswap V2 的 997/1000 費率乘數，每個代幣 pair 僅一個池；遇到平行池會拒絕，不會默默合併。

## 正確性與架構

DELTA 維護所選固定著色範圍內、恰好 `k` 條邊的最低權重簡單有向環。最佳環為非負時仍會回傳；沒有候選以 `null` 表示。這不保證取得所有不受著色限制之循環的全域最優值。

RPC 圖的邊權為含池費邊際匯率的負自然對數。負環是價格訊號，不等於可成交淨利：尚未納入有限交易量、滑價、gas、競爭與交易執行。此應用不簽名、不送出交易。

終端應用保留已驗證的 DELTA 遞推。原生核心、程序轉接、資料來源、應用狀態與終端畫面各自負責不同工作；使用輕量 Model–View–ViewModel（MVVM）與邊界轉接，不進行框架式全面重寫。

## 測試

~~~powershell
python -m unittest delta_terminal.tests.test_terminal -v
~~~

測試涵蓋教學案例、獨立窮舉小圖、批次更新、RPC／離線重播、停用池、區塊 hash 改變、錯誤輸入、憑證遮罩、請求上限與失敗狀態。可選的原版執行檔比較需設定：

~~~powershell
$env:DELTA_REFERENCE_EXE = "C:\path\to\original_delta.exe"
python -m unittest delta_terminal.tests.test_terminal -v
~~~

`DELTA_REFERENCE_CASE` 可指定其他小圖；此比較也會進行完整窮舉，因此不要用於大圖。具日期的本機驗收結果見終端機指南；這些是功能測試，不是效能 benchmark。

## RICH／TRADER 資料稽核

請另行取得 TRADER 作者資料，保存在 Git 之外，再執行：

~~~powershell
python rich_trader_benchmark/scripts/audit_datasets.py --data-dir "C:\data\processed_graph_data_new" --output-dir "C:\results\data_audit"
~~~

也可設定 `TRADER_UNI_DATA_DIR`。稽核會檢查來源、檔案清單身分、格式、數量與事件順序，輸出 JSON／CSV／Markdown 報告。資料稽核通過不代表已證明套利結果。解讀量測前，請先閱讀[資料來源](rich_trader_benchmark/docs/data_provenance.md)、[稽核細節](rich_trader_benchmark/docs/data_audit.md)與[實驗規範](rich_trader_benchmark/docs/experiment_protocol.md)。

## 目錄結構

~~~text
.
├── README.md                  # 英文入口
├── README.zh-TW.md             # 繁體中文入口
├── delta_terminal/             # DELTA 核心、終端、RPC 轉接與測試
├── rich_trader_benchmark/      # 資料稽核與 benchmark 規範
└── experiments/               # 輔助實驗規則
~~~

外層研究工作區的 `6D/doc`、`6D/pdf` 等資料夾不屬於此 Git repository。

## 開發與資料規則

- 從更新後的 `main` 建立功能分支；保留無關修改，必要時使用獨立工作樹。
- 保留原始資料與外部 baseline 實作。不要提交 `.env`、RPC 憑證、錢包機密、本機執行環境或大型產生資料。
- 解讀速度前先檢查答案品質，明列初始化、計時邊界與資源成本。
- 執行相關檢查、提交限定範圍的修改並建立 PR；只有檢查通過且使用者或指定 reviewer 同意後才能合併。
- 移除分支前核對 PR／提交涵蓋狀態與工作樹內容；遠端分支不存在，不代表可以丟棄本機工作。
