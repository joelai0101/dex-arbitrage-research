"""Verify the existing minimal TRADER EG old/new-weight repair in isolation.

Inputs are locally supplied, frozen service sources; no upstream code is vendored.
An optional single UNI1 quality replay is diagnostic, never a formal timing run.
"""
import argparse
import csv
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def score(case, reference, trace, colors):
    live = {(int(u), int(v)): float(w) for u, v, w in
            (line.split() for line in (case / "graph.txt").read_text().splitlines())}
    updates = (case / "updates.txt").read_text().splitlines()
    with reference.open() as f:
        refs = list(csv.DictReader(f, delimiter="\t"))
    with trace.open() as f:
        answers = list(csv.DictReader(f, delimiter="\t"))
    arrivals = [a for a in answers if a["phase"] == "arrival"]
    assert len(arrivals) == len(updates) == len(refs) - 1
    counts = dict(arrivals=len(updates), legal_path=0, weight_mismatch=0,
                  color_violation=0, valid_report=0, valid_colored_report=0,
                  below_oracle=0, optimal_path=0)
    failures = []
    for row, (line, answer, ref) in enumerate(zip(updates, arrivals, refs[1:]), 1):
        assert int(answer["row"]) == int(ref["row"]) == row
        u, v, w = line.split()
        if w != "N":
            live[int(u), int(v)] = float(w)
        path = list(map(int, answer["path"].split()))
        legal = (len(path) == 6 and path[0] == path[-1] and len(set(path[:-1])) == 5
                 and all(edge in live for edge in zip(path, path[1:])))
        actual = math.fsum(live[e] for e in zip(path, path[1:])) if legal else None
        reported = float(answer["weight"])
        matches = legal and math.isfinite(reported) and abs(actual - reported) <= 1e-10
        rainbow = legal and len({colors[answer["coloring"]][str(v)] for v in path[:-1]}) == 5
        target = float(ref["weight"])
        counts["legal_path"] += legal
        counts["weight_mismatch"] += legal and not matches
        counts["color_violation"] += legal and not rainbow
        counts["valid_report"] += matches
        counts["valid_colored_report"] += matches and rainbow
        counts["below_oracle"] += legal and actual < target - 1e-10
        counts["optimal_path"] += legal and abs(actual - target) <= 1e-10
        if not (matches and rainbow):
            failures.append(dict(row=row, legal=legal, matches=matches, rainbow=rainbow,
                                 actual=actual, reported=reported if math.isfinite(reported) else None,
                                 path=path, coloring=answer["coloring"]))
    return counts, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--replay-uni1", action="store_true")
    args = parser.parse_args()
    root, out = args.root.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    base = root / ".research_data/common_benchmark"
    service = base / "trader_official_dual_20260913/service_v1"
    frozen = service / "official"
    native = base / "trader_official_native_20260913/build"
    suite = base / "experiment_suite_20261002"
    protocol_path = suite / "external_protocols/20261002T132042_994973Z/protocol.json"
    assert sha(protocol_path) == "723f9c2ee6496ddeecfdd37d2b450a886128456d159eaf4af6e6eb8f20af442f"
    protocol = json.loads(protocol_path.read_text())
    driver = root / ".worktrees/trader-official-dual/scripts/trader_official_dual/service_driver.cpp"
    compiler = root / ".venv/toolchains/llvm-mingw-20260616-ucrt-x86_64/bin/clang++.exe"
    compat = native / "trader_native_uint_compat.h"
    manifest = json.loads((frozen / "manifest.json").read_text())
    sources = {name: frozen / name for name in manifest["generated_sha256"]}
    for name, path in sources.items():
        assert sha(path) == manifest["generated_sha256"][name], name
    for path in [*sources.values(), driver, compat]:
        assert sha(path) == protocol["files"][path.relative_to(root).as_posix()], path
    protected = {str(p): sha(p) for p in [*sources.values(), driver, compat]}
    env = dict(os.environ, PATH=str(native) + os.pathsep + os.environ["PATH"])
    scripts = Path(__file__).resolve().parent
    run_records = []

    def run(command, label, expected=(0,), timeout=120):
        print("START", label, flush=True)
        with (out / f"{label}.stdout.log").open("wb") as stdout, (out / f"{label}.stderr.log").open("wb") as stderr:
            process = subprocess.Popen(list(map(str, command)), cwd=root, env=env, stdout=stdout, stderr=stderr)
            save(out / "active.json", dict(phase=label, pid=process.pid, diagnostic_only=True))
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise
        record = dict(command=list(map(str, command)), returncode=code, expected=list(expected), diagnostic_only=True)
        save(out / f"{label}.process.json", record)
        run_records.append(record)
        assert code in expected, (label, code)
        print("DONE", label, flush=True)
        return (out / f"{label}.stdout.log").read_text(encoding="utf-8")

    original = sources["cycle_detector.cpp"].read_text(encoding="utf-8")
    anchor = "                if(!graph.get_edge_weight(src_node, dst_node, weight)) {"
    assert original.count(anchor) == 2  # Native loop and extracted persistent loop.
    replacement = ("                double lookup_old_weight = 0.0;\n"
                   "                if(!graph.get_edge_weight(src_node, dst_node, lookup_old_weight)) {")
    fixed = original.replace(anchor, replacement)
    assert fixed == (service / "oldnew/cycle_detector.cpp").read_text(encoding="utf-8")
    (out / "weight_fix.diff").write_text("".join(difflib.unified_diff(
        original.splitlines(True), fixed.splitlines(True), fromfile="official/cycle_detector.cpp",
        tofile="weight_fixed/cycle_detector.cpp")), encoding="utf-8")
    accessor = """
#ifdef EG_REGRESSION
    double regression_decrease() const { return cumulative_weight; }
    size_t regression_pending() const { return batch_lines.size(); }
    double regression_gap() const { return batch_weight_threshold_; }
    void regression_set_gap(double gap) { batch_weight_threshold_ = gap; }
#endif
"""
    graph = out / "two_cycles.txt"
    graph.write_text("".join(f"{start+i} {start+(i+1)%5} {weight}\n"
                             for start, weight in [(0, -2), (5, -1)] for i in range(5)))
    checks = {}
    for variant, text in [("original", original), ("weight_fixed", fixed)]:
        source = out / variant
        source.mkdir()
        for name, path in sources.items():
            shutil.copy2(path, source / name)
        (source / "cycle_detector.cpp").write_text(text, encoding="utf-8")
        header = (source / "cycle_detector.h").read_text(encoding="utf-8")
        assert header.count("    void common_start(unsigned int seed);") == 1
        (source / "cycle_detector.h").write_text(header.replace(
            "    void common_start(unsigned int seed);", accessor + "    void common_start(unsigned int seed);"), encoding="utf-8")
        command = [compiler, "-O3", "-std=c++17", "-include", compat, "-I", source,
                   source / "directed_graph.cpp", source / "cycle_detector.cpp"]
        binary = out / f"{variant}_regression.exe"
        run([*command, "-DEG_REGRESSION", scripts / "eg_regression.cpp", "-o", binary], f"compile_{variant}")
        raw = run([binary, graph], f"regression_{variant}", expected=(1,) if variant == "original" else (0,))
        records = [line.split("\t") for line in raw.splitlines()]
        checks[variant] = {
            "checks": {parts[1]: parts[2] for parts in records if parts[0] == "CHECK"},
            "native_gap_witness": next(dict(gap=parts[1], returned_weight=float(parts[2]),
                 pending=int(parts[3]), cumulative_decrease=float(parts[4]), expected_current_weight=-16)
                 for parts in records if parts[0] == "GAP_WITNESS"),
        }
    expected_failures = {"decrease_retained", "repeated_edge_accounting", "equal_gap_deferred", "above_gap_flushes"}
    assert {name for name, value in checks["original"]["checks"].items() if value == "FAIL"} == expected_failures
    assert all(value == "PASS" for value in checks["weight_fixed"]["checks"].values())
    result = dict(regression=checks, scope="EG old/new weight lookup only", formal_benchmark=False,
                  equivalent_to_existing_oldnew_source=True, baseline_accepted=False)
    save(out / "regression.json", result)
    if args.replay_uni1:
        # Build without test accessors enabled, using the exact existing driver.
        binary = out / "weight_fixed_normal.exe"
        run([*command, driver, "-lpsapi", "-o", binary], "compile_replay")
        spec = protocol["cases"]["UNI1"]
        case, reference = root / spec["path"], root / spec["reference"]
        seeds = root / "6D/code/.upstream/TRADER/seeds.txt"
        color_path = base / "trader_official_dual_20260913/interface_v2/UNI1_all_arrival_colors.json"
        old_trace = suite / "external_runs/Clean_UNI1_4_20261003/UNI1_TRADER_EG_official_r1/trace.tsv"
        for path in [case / "graph.txt", case / "updates.txt", reference, seeds]:
            assert sha(path) == protocol["files"][path.relative_to(root).as_posix()], path
        protected.update({str(p): sha(p) for p in [case / "graph.txt", case / "updates.txt", reference, seeds, color_path, old_trace]})
        raw = run([binary, case / "graph.txt", case / "updates.txt", seeds, 5, 80, 1, 1, out / "trace.tsv"], "UNI1_quality_replay", timeout=1200)
        runtime = json.loads(next(line for line in raw.splitlines() if line.startswith("{")))
        assert runtime["updates"] == spec["updates"] == 7628 and runtime["ell"] == 80
        save(out / "diagnostic_runtime.json", dict(runtime=runtime, formal_benchmark=False, not_for_speed_comparison=True))
        colors = json.loads(color_path.read_text())
        for variant, trace in [("original", old_trace), ("weight_fixed", out / "trace.tsv")]:
            counts, failures = score(case, reference, trace, colors)
            save(out / f"{variant}_failures.json", failures)
            result[variant + "_UNI1"] = counts
        result["replay_binary_sha256"] = sha(binary)
    for name, expected in protected.items():
        assert sha(Path(name)) == expected, name
    result["inputs_unchanged"] = True
    result["input_sha256"] = protected
    save(out / "summary.json", result)
    save(out / "active.json", dict(status="completed", diagnostic_only=True))
    print(json.dumps({k: v for k, v in result.items() if k not in ("input_sha256", "regression")}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
