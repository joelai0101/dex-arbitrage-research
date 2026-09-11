"""Data contract shared by file and RPC sources; no UI or network dependencies."""
from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass
class Case:
    k: int
    colors: list[int]
    graph: list[tuple[int, int, float]]
    updates: list[tuple[int, int, float | str]]
    boundaries: list[int]
    metadata: dict

    def validate(self):
        if not 2 <= self.k <= 10 or not self.colors or any(type(c) is not int or not 0 <= c < self.k for c in self.colors):
            raise ValueError("k 必須為 2–10，且每個節點顏色必須介於 0 與 k-1。")
        seen = set()
        for initial, rows in ((True, self.graph), (False, self.updates)):
            for u, v, w in rows:
                if not 0 <= u < len(self.colors) or not 0 <= v < len(self.colors):
                    raise ValueError("邊端點超出 colors.txt 節點範圍。")
                if w != "N" and u == v:
                    raise ValueError("不接受自迴圈；明示 N 事件除外。")
                if w in ("N", "D"):
                    if initial:
                        raise ValueError("初始圖只接受有限權重。")
                elif not isinstance(w, (int, float)) or not math.isfinite(w) or abs(w) > 1e100:
                    raise ValueError("權重須為有限數值且絕對值不超過 1e100。")
                if initial:
                    if (u, v) in seen:
                        raise ValueError("初始圖包含重複有向邊／平行池；請先明訂轉接規則。")
                    seen.add((u, v))
        if self.boundaries != sorted(set(self.boundaries)) or any(x <= 0 for x in self.boundaries):
            raise ValueError("回答邊界須為嚴格遞增的正整數。")
        if (self.updates and (not self.boundaries or self.boundaries[-1] != len(self.updates))) or (not self.updates and self.boundaries):
            raise ValueError("回答邊界未完整涵蓋更新。")


def read_rows(path):
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"{Path(path).name}:{number} 須為 u v weight|D|N。")
        u, v = map(int, parts[:2])
        rows.append((u, v, parts[2] if parts[2] in ("D", "N") else float(parts[2])))
    return rows


def load_case(folder, k=None, batch=None):
    folder = Path(folder)
    metadata_path = folder / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig")) if metadata_path.exists() else {}
    k = k if k is not None else metadata.get("k")
    if not isinstance(k, int):
        raise ValueError("請提供 --k，或在 metadata.json 設定 k。")
    colors = list(map(int, (folder / "colors.txt").read_text(encoding="utf-8-sig").split()))
    graph, updates = read_rows(folder / "graph.txt"), read_rows(folder / "updates.txt")
    schedule = folder / "schedule.txt"
    if batch is not None:
        if batch < 1:
            raise ValueError("batch 必須大於 0。")
        boundaries = list(range(batch, len(updates), batch)) + ([len(updates)] if updates else [])
    elif schedule.exists():
        boundaries = list(map(int, schedule.read_text(encoding="utf-8-sig").split()))
    else:
        boundaries = list(range(1, len(updates) + 1))
    case = Case(k, colors, graph, updates, boundaries, metadata)
    case.validate()
    return case


def write_case(case, folder):
    case.validate()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "colors.txt").write_text("\n".join(map(str, case.colors)) + "\n", encoding="utf-8")
    for name, rows in (("graph.txt", case.graph), ("updates.txt", case.updates)):
        (folder / name).write_text("".join(f"{u} {v} {w if isinstance(w,str) else format(w,'.17g')}\n" for u,v,w in rows), encoding="utf-8")
    (folder / "schedule.txt").write_text("".join(f"{x}\n" for x in case.boundaries), encoding="utf-8")
    (folder / "metadata.json").write_text(json.dumps({**case.metadata, "k": case.k}, ensure_ascii=False, indent=2), encoding="utf-8")
