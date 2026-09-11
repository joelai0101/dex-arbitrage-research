# DEX 套利研究

[English](README.md) | [繁體中文](README.zh-TW.md)

本專案提供可重現的代幣圖實驗與去中心化交易所（Decentralized Exchange, DEX）循環增量維護工具；此版本聚焦 DELTA 終端機、原生核心、資料轉接、範例與正確性測試。

[終端機使用指南](delta_terminal/README.md) 說明互動選單、離線圖重播、有限區塊唯讀 Ethereum RPC 擷取與答案一致性測試。作者原始資料、外部 baseline 原始碼與編譯後執行檔不隨 repository 提供。

## 快速開始：DELTA

需要 Python 3.12 以上，以及既有 C++17 編譯器。DELTA 僅使用 Python 標準函式庫，無須安裝終端 UI 或 Web3 套件。請使用專案虛擬環境；以下命令在 Git repository 根目錄執行。

[requirements.txt](requirements.txt) 刻意不列套件：DELTA 與測試都只使用標準函式庫。可執行 `python -m pip install -r requirements.txt`，目前不會安裝任何套件。Python 與 C++ 編譯器須另行準備；本機文獻／文件工具不屬於這份 DELTA 依賴清單。

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

在隱藏輸入提示中貼上 HTTPS RPC URL，或透過程序環境變數 `DELTA_RPC_URL` 提供。URL 留空或只有空白字元時直接取消，不連線、不產生資料，也不切換到備用端點。不要把供應商金鑰提交到 Git，或放入命令列 URL 參數。

此模式擷取有限個已 finalized 的 Ethereum 區塊末快照，再對產生的圖進行增量重播，不是持續訂閱 mempool。預設三個 Uniswap V2 池（USDC／USDT／WETH）、兩個區塊、一組固定著色與 `k=3`。每次最多 64 次唯讀請求，間隔至少兩秒，不自動重試。RPC 不可用時暫緩該模式，離線功能仍可使用。

擷取結果另存為 `<output>_case`，保留區塊 hash 與原始整數儲備量；可用相同輸入離線重播：

~~~powershell
python -m delta_terminal offline --case "C:\results\new_rpc_run_case" --output "C:\results\rpc_replay"
~~~

可用 `--pools` 指定相容池設定；若供應商提供對應歷史狀態，可用 `--start-block` 指定已 finalized 的歷史起點。轉接層假設 Uniswap V2 的 997/1000 費率乘數，每個代幣 pair 僅一個池；遇到平行池會拒絕，不會默默合併。

## 在 macOS／Linux clone 與執行

先準備既有 Python 3.12+、C++17 Clang／GCC，再建立本機虛擬環境；不需要 Windows 執行檔，也不依賴外層研究工作區：

~~~sh
git clone https://github.com/joelai0101/dex-arbitrage-research.git
cd dex-arbitrage-research
python3 -m venv .venv
. .venv/bin/activate
sh scripts/demo.sh offline
sh scripts/demo.sh test
~~~

[demo 腳本](scripts/README.md) 也支援 `menu` 與 `rpc`。shell 檔固定使用 LF 換行；C++ 核心沒有 Windows API 相依，各平台各自編譯執行檔。只有 `.ps1` 啟動器是 Windows 專用，不是整個應用都只能在 Windows 跑。跨平台 workflow 會在 Ubuntu 與 macOS 編譯、測試；實際通過狀態以當前 PR checks 為準，不把語法可攜性直接當成已驗證執行。

原始 UNI 資料與 Windows baseline 執行檔不隨 repository 提供。新環境可先用內建教學例或 RPC 產生新圖；其他外部 baseline 必須在目標平台另行建置。

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

## 歷史研究模組

DELTA 不依賴 `rich_trader_benchmark`、`dex_arbitrage_feasibility` 或原 `experiments` 目錄。這些獨立研究模組保留在[整理前的 Git 快照](https://github.com/joelai0101/dex-arbitrage-research/tree/fe82afbdc05fcfadebf705f95db9b32dd26661a4)，不放在目前聚焦 DELTA 的程式樹；`dex_data_probe` 已於更早版本退役。移出目前程式樹不會刪除其 Git 歷史或外部研究資料。

## 目錄結構

~~~text
.
├── README.md                  # 英文入口
├── README.zh-TW.md             # 繁體中文入口
├── requirements.txt           # 目前沒有第三方 Python 依賴
├── delta_terminal/             # DELTA 核心、終端、RPC 轉接與測試
├── scripts/                    # 跨平台 shell demo
└── .github/workflows/          # Ubuntu／macOS 原生編譯與測試
~~~

外層研究工作區的 `6D/doc`、`6D/pdf` 等資料夾不屬於此 Git repository。

## 開發與資料規則

- 從更新後的 `main` 建立功能分支；保留無關修改，必要時使用獨立工作樹。
- 保留原始資料與外部 baseline 實作。不要提交 `.env`、RPC 憑證、錢包機密、本機執行環境或大型產生資料。
- 解讀速度前先檢查答案品質，明列初始化、計時邊界與資源成本。
- 執行相關檢查、提交限定範圍的修改並建立 PR；只有檢查通過且使用者或指定 reviewer 同意後才能合併。
- 移除分支前核對 PR／提交涵蓋狀態與工作樹內容；遠端分支不存在，不代表可以丟棄本機工作。
