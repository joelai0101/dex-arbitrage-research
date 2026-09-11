"""Plain terminal view: works in PowerShell without third-party UI packages."""
import argparse
from datetime import datetime
import getpass
import os
from pathlib import Path
import sys
from .app import run_case
from .build import PACKAGE, EXECUTABLE, build
from .model import load_case, write_case
from .rpc import DEFAULT_POOLS, POCKET, RpcClient, RpcUnavailable, capture

EXAMPLE = PACKAGE / "examples/toy"


def output_folder():
    return PACKAGE / "output" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def display(state, answer):
    print(state.row(answer), flush=True)


def execute(args):
    if args.command == "build":
        print("核心已編譯：", build(args.compiler))
        return
    if not EXECUTABLE.exists():
        raise RuntimeError("尚未編譯；請先執行 python -m delta_terminal build。")
    output = args.output or output_folder()
    if Path(output).exists():
        raise ValueError("輸出目錄已存在，請另選新目錄，避免覆蓋結果。")
    if args.command == "rpc":
        # No URL command-line option: avoid leaking provider keys into process lists.
        url = os.environ.get("DELTA_RPC_URL") or getpass.getpass("RPC URL（隱藏輸入；空白使用 Pocket）：").strip() or POCKET
        client = RpcClient(url)
        print(f"RPC：{client.host}；最多 64 請求、間隔 2 秒、無自動重試。", flush=True)
        case = capture(client, blocks=args.blocks, k=args.k, pool_path=args.pools,
                       start_block=args.start_block, progress=lambda s: print(s, flush=True))
        # Capture is complete and validated before any exported case is labelled usable.
        exported = Path(output).with_name(Path(output).name + "_case")
        write_case(case, exported)
        print("可離線重播的圖：", exported)
    else:
        case = load_case(args.case, args.k, args.batch)
    print(f"\nDELTA | {args.command} | 節點 {len(case.colors)} | k={case.k} | 固定 1 組著色")
    print("更新列號  狀態                       權重  路徑")
    count = 0

    def show(state, answer):
        nonlocal count
        count += 1
        if count <= 10 or count % 1000 == 0 or answer["row"] == len(case.updates):
            display(state, answer)

    state = run_case(case, output, args.command, show)
    print(f"{state.status}：{len(state.answers)} 個回答點；完整結果：{Path(output) / 'results.json'}")
    print("負環僅為含池費的邊際匯率訊號，不是扣除滑價與 gas 後的可成交淨利。")


def parser():
    p = argparse.ArgumentParser(description="DELTA 終端機：離線圖與唯讀 RPC 小測試")
    commands = p.add_subparsers(dest="command")
    b = commands.add_parser("build", help="使用既有 C++17 編譯器建置")
    b.add_argument("--compiler")
    off = commands.add_parser("offline", help="讀取 colors／graph／updates／schedule")
    off.add_argument("--case", type=Path, default=EXAMPLE)
    off.add_argument("--k", type=int)
    off.add_argument("--batch", type=int, help="覆寫回答邊界；不指定則沿用 schedule.txt")
    off.add_argument("--output", type=Path)
    rpc = commands.add_parser("rpc", help="擷取 finalized 區塊，增量測試並另存離線圖")
    rpc.add_argument("--blocks", type=int, default=2)
    rpc.add_argument("--start-block", type=int)
    rpc.add_argument("--k", type=int, default=3)
    rpc.add_argument("--pools", type=Path, default=DEFAULT_POOLS)
    rpc.add_argument("--output", type=Path)
    return p


def menu():
    while True:
        print("\n┌──────────── DELTA 研究終端機 ────────────┐")
        print("│ 1  離線範例／代幣圖                    │")
        print("│ 2  RPC 擷取與測試（有限 finalized 區塊）│")
        print("│ 3  編譯核心                            │")
        print("│ 0  結束                                │")
        print("└────────────────────────────────────────┘")
        choice = input("選擇：").strip()
        if choice == "0":
            return
        try:
            if choice == "1":
                folder = input("圖目錄（空白使用內建範例）：").strip().strip('"')
                args = parser().parse_args(["offline"] + (["--case", folder] if folder else []))
                if folder:
                    value = input("k（空白使用 metadata.json）：").strip()
                    args.k = int(value) if value else None
            elif choice == "2":
                value = input("最近 finalized 區塊數（預設 2）：").strip()
                args = parser().parse_args(["rpc"])
                args.blocks = int(value or "2")
            elif choice == "3":
                args = parser().parse_args(["build"])
            else:
                print("請選擇 0–3。")
                continue
            execute(args)
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"未完成：{exc}")


def main():
    try:
        args = parser().parse_args()
        if args.command is None:
            menu()
        else:
            execute(args)
        return 0
    except RpcUnavailable as exc:
        print(f"RPC 暫緩：{exc} 離線模式仍可使用。", file=sys.stderr)
        return 2
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"未完成：{exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n已結束。")
        return 130
