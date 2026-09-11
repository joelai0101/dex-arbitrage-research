"""Build the local engine without installing tools or changing PATH."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

PACKAGE = Path(__file__).resolve().parent
EXECUTABLE = PACKAGE / "build" / ("delta.exe" if os.name == "nt" else "delta")


def build(compiler=None):
    if compiler is None:
        for parent in PACKAGE.parents:
            candidate = parent / ".venv/toolchains/llvm-mingw-20260616-ucrt-x86_64/bin/clang++.exe"
            if candidate.is_file():
                compiler = str(candidate)
                break
        else:
            compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        raise RuntimeError("找不到 C++17 編譯器，請使用 build --compiler 指定既有編譯器。")
    EXECUTABLE.parent.mkdir(exist_ok=True)
    temporary = EXECUTABLE.with_name("delta.pending" + EXECUTABLE.suffix)
    result = subprocess.run([str(compiler), "-std=c++17", "-O3", str(PACKAGE / "native/main.cpp"),
                             "-o", str(temporary)], capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError("編譯失敗：\n" + result.stderr.decode(errors="replace"))
    if os.name == "nt":
        for name in ("libc++.dll", "libunwind.dll", "libwinpthread-1.dll"):
            source = Path(compiler).resolve().parent / name
            if source.is_file():
                shutil.copy2(source, EXECUTABLE.parent / name)
    temporary.replace(EXECUTABLE)
    return EXECUTABLE


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler")
    print(build(parser.parse_args().compiler))
