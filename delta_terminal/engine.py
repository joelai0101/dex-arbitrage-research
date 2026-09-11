"""Adapter for a persistent native DELTA process; each source uses this boundary."""
import json
import subprocess
from .build import EXECUTABLE


def solve(case, on_result=None, executable=EXECUTABLE):
    case.validate()
    if not executable.is_file():
        raise RuntimeError("尚未編譯核心，請先執行 python -m delta_terminal build。")
    process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8")
    answers = []

    def exchange(header, rows, colors=None):
        process.stdin.write(header + "\n")
        if colors is not None:
            process.stdin.write(" ".join(map(str, colors)) + "\n")
        for u, v, w in rows:
            value = w if isinstance(w, str) else format(w, ".17g")
            process.stdin.write(f"{u} {v} {value}\n")
        process.stdin.flush()
        response = process.stdout.readline()
        if not response:
            raise RuntimeError("DELTA 核心失敗：" + process.stderr.read().strip())
        answer = json.loads(response)
        answers.append(answer)
        if on_result:
            on_result(answer)

    try:
        exchange(f"INIT {len(case.colors)} {case.k} {len(case.graph)}", case.graph, case.colors)
        previous = 0
        for boundary in case.boundaries:
            exchange(f"B {boundary-previous}", case.updates[previous:boundary])
            previous = boundary
        process.stdin.close()
        if process.wait(timeout=10):
            raise RuntimeError("DELTA 核心非正常結束。")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
    return answers
