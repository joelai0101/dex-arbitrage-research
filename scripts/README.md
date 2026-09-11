# Demo scripts / 展示腳本

Run from any directory using the script's path. The script changes to the repository root, finds an existing Python environment, compiles the native engine, and runs the selected mode. It installs nothing.

從任意目錄指定腳本路徑即可；腳本會切到 repository 根目錄、尋找既有 Python、編譯核心並執行選定模式，不安裝任何工具。

```sh
sh scripts/demo.sh offline           # Default teaching example / 預設教學例
sh scripts/demo.sh menu              # Interactive terminal / 互動選單
sh scripts/demo.sh test              # Small correctness tests / 小型正確性測試
sh scripts/demo.sh rpc --blocks 2    # Capture graphs and replay / 擷取圖並回放
```

`DELTA_PYTHON` may point to a Python executable; otherwise the script searches ancestor `.venv` environments, then `python3`/`python`. Python 3.12+ and a C++17 Clang/GCC compiler must already be available. All shell scripts live in this directory; use `sh` so an executable permission bit is not required.

可用 `DELTA_PYTHON` 指定 Python 執行檔；否則依序找上層 `.venv`、`python3`／`python`。需要事先有 Python 3.12+ 與 C++17 Clang／GCC 編譯器。shell 腳本集中在此目錄，使用 `sh` 呼叫，不依賴執行權限 bit。

RPC credentials are never included in this script. An empty URL cancels without connecting. The offline and test modes need no RPC. On Windows without a POSIX shell, use `delta_terminal/start.ps1` or `python -m delta_terminal`.

腳本不包含 RPC 憑證；RPC URL 留空直接取消、不連線。離線與測試模式不需要 RPC。Windows 沒有 POSIX shell 時，使用 `delta_terminal/start.ps1` 或 `python -m delta_terminal`。
