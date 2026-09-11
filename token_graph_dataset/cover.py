"""Deterministic exhaustive color coverage, only for the five-token pilot."""
from fractions import Fraction
from itertools import combinations
import json
from pathlib import Path

from delta_terminal.model import write_case
from .reconstruct import reconstruct, require
from .verify import equal_weight, verify


def color_cover(nodes, k):
    require(nodes == 5 and k in (4,5), "Complete pilot cover requires five nodes and k=4 or 5")
    unique = set()
    for subset in combinations(range(nodes), k):
        colors = [0]*nodes
        for color, vertex in enumerate(subset):
            colors[vertex] = color
        unique.add(tuple(colors))
    return sorted(unique)


def verify_cover(source, output, ks=(4,5), progress=print):
    output = Path(output)
    require(len(set(ks)) == len(ks) and set(ks) <= {4,5} and ks, "Choose k=4 and/or 5 once each")
    output.mkdir(parents=True, exist_ok=False)
    status = {"status": "running", "results": []}
    try:
        for k in ks:
            base = reconstruct(source, k)
            cover = color_cover(len(base.colors), k)
            runs = []
            for index, colors in enumerate(cover):
                case = reconstruct(source, k, colors)
                folder = output / f"k{k}" / f"color_{index:02d}"
                write_case(case, folder)
                (folder/"source.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
                report = verify(case)
                (folder/"verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                runs.append(report)
                progress(f"k={k} coloring {index+1}/{len(cover)}: {report['answers_checked']} states checked")
            combined = []
            for index, row in enumerate(runs[0]["results"]):
                choices = [(color, run["results"][index]) for color, run in enumerate(runs)
                           if run["results"][index]["delta"]["weight"] is not None]
                winner = max(choices, key=lambda item: Fraction(item[1]["delta_rate_product"])) if choices else None
                best = winner[1]["delta"] if winner else {"weight": None, "path": []}
                require(equal_weight(best["weight"], row["global_oracle"]["weight"]), "Complete color cover missed the global oracle weight")
                exact_match = (winner[1]["delta_rate_product"] == row["global_rate_product"]) if winner else row["global_rate_product"] is None
                combined.append({"row": row["row"], "best_coloring": winner[0] if winner else None,
                    "delta_weight": best["weight"], "delta_path": best["path"],
                    "global_oracle": row["global_oracle"], "global_weight_matched": True,
                    "global_product_matched": exact_match,
                    "global_negative_exact": row["global_negative_exact"],
                    "delta_negative_exact": winner[1]["delta_negative_exact"] if winner else False,
                    "global_rate_product": row["global_rate_product"]})
            summary = {"k": k, "colorings": [list(colors) for colors in cover], "states": len(combined),
                "global_weight_matches": len(combined), "global_product_matches": sum(r["global_product_matched"] for r in combined),
                "global_candidate_states": sum(r["global_oracle"]["weight"] is not None for r in combined),
                "global_negative_states": sum(r["global_negative_exact"] for r in combined),
                "delta_negative_states": sum(r["delta_negative_exact"] for r in combined), "results": combined}
            (output/f"k{k}"/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            status["results"].append({key: value for key, value in summary.items() if key != "results"})
        status["status"] = "passed"
        return status
    except BaseException as exc:
        status.update(status="failed_or_interrupted", error_type=type(exc).__name__)
        raise
    finally:
        (output/"summary.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
