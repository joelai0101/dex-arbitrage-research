"""Application state and use case; independent of terminal input/rendering."""
from dataclasses import dataclass, field
import json
from pathlib import Path
from .engine import solve


@dataclass
class SessionViewModel:
    mode: str
    status: str = "準備中"
    answers: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)

    def accept(self, answer):
        self.answers.append(answer)
        self.status = "執行中"

    def row(self, answer):
        weight = answer["weight"]
        kind = "無候選" if weight is None else "負環訊號" if weight < -1e-10 else "非負／近零"
        path = " → ".join(self.labels.get(v, str(v)) for v in answer["path"]) or "—"
        return f"{answer['row']:>8}  {kind:<8}  {weight if weight is not None else 'none'!s:>22}  {path}"


def run_case(case, output, mode, notify=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    state = SessionViewModel(mode, labels={n["id"]: n.get("symbol", str(n["id"])) for n in case.metadata.get("nodes", [])})

    def receive(answer):
        state.accept(answer)
        if notify:
            notify(state, answer)

    try:
        solve(case, receive)
        state.status = "完成"
    except BaseException:
        state.status = "失敗／中止"
        raise
    finally:
        report = {"status": state.status, "mode": mode, "k": case.k,
                  "nodes": len(case.colors), "initial_edges": len(case.graph),
                  "update_rows": len(case.updates), "answers": state.answers}
        (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return state
