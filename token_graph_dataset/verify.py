"""Independent exhaustive cycle oracle and witness checks for bounded small graphs."""
from fractions import Fraction
from itertools import permutations
import math

from delta_terminal.engine import solve


def minimum_cycle(graph, nodes, k, colors=None):
    best, witness = None, []
    for vertices in permutations(range(nodes), k):
        if vertices[0] != min(vertices):
            continue  # Remove rotations, retaining both directed orientations.
        if colors is not None and len({colors[v] for v in vertices}) != k:
            continue
        path = [*vertices, vertices[0]]
        edges = list(zip(path, path[1:]))
        if all(edge in graph for edge in edges):
            weight = math.fsum(graph[edge] for edge in edges)
            if best is None or weight < best:
                best, witness = weight, path
    return {"weight": best, "path": witness}


def equal_weight(left, right):
    return left is right if left is None or right is None else math.isclose(left, right, abs_tol=1e-10, rel_tol=1e-10)


def verify(case):
    if len(case.colors) > 10 or case.k > 5 or len(case.boundaries) > 1000:
        raise ValueError("Exhaustive validation limited to <=10 nodes, k<=5, <=1000 transaction batches")
    answers = solve(case)
    if [answer["row"] for answer in answers] != [0] + case.boundaries:
        raise ValueError("DELTA returned wrong answer boundaries")
    graph = {(u, v): w for u, v, w in case.graph}
    state = {event["pool"]: event["reserves"] for event in case.metadata["initial_events"]}
    ids = {node["address"]: node["id"] for node in case.metadata["nodes"]}
    pool_pairs = {pool["pair_address"].lower(): tuple(ids[pool[f"token{i}_address"].lower()] for i in (0, 1)) for pool in case.metadata["pools"]}
    transactions = {row["row"]: row for row in case.metadata["transactions"]}
    results, previous = [], 0
    for answer in answers:
        for u, v, weight in case.updates[previous:answer["row"]]:
            if weight == "D":
                graph.pop((u, v), None)
            elif weight != "N":
                graph[u, v] = weight
        previous = answer["row"]
        for event in transactions.get(previous, {}).get("events", []):
            state[event["pool"]] = event["reserves"]
        restricted = minimum_cycle(graph, len(case.colors), case.k, case.colors)
        global_best = minimum_cycle(graph, len(case.colors), case.k)
        if not equal_weight(answer["weight"], restricted["weight"]):
            raise ValueError(f"DELTA/oracle mismatch at row {previous}")
        path = answer["path"]
        if answer["weight"] is not None:
            if len(path) != case.k+1 or path[0] != path[-1] or len(set(path[:-1])) != case.k or len({case.colors[v] for v in path[:-1]}) != case.k:
                raise ValueError("Invalid DELTA cycle witness")
            if not equal_weight(math.fsum(graph[u, v] for u, v in zip(path, path[1:])), answer["weight"]):
                raise ValueError("DELTA witness weight mismatch")
        elif path:
            raise ValueError("Null answer has a nonempty path")
        # Along a closed cycle decimal units cancel. Exact rational reserve products
        # independently determine the price-signal sign, including near-zero cases.
        rates = {}
        for pool, (u, v) in pool_pairs.items():
            a, b = state[pool]
            if a and b:
                rates[u, v], rates[v, u] = Fraction(997*b, 1000*a), Fraction(997*a, 1000*b)
        def product(witness):
            if not witness:
                return None
            return math.prod(rates[u, v] for u, v in zip(witness, witness[1:]))
        gp, dp = product(global_best["path"]), product(path)
        results.append({"row": previous, "delta": answer, "restricted_oracle": restricted,
                        "global_oracle": global_best,
                        "global_weight_matched": equal_weight(answer["weight"], global_best["weight"]),
                        "global_negative_exact": gp is not None and gp > 1,
                        "delta_negative_exact": dp is not None and dp > 1,
                        "global_rate_product": str(gp) if gp is not None else None})
    return {"status": "passed", "k": case.k, "nodes": len(case.colors),
            "answers_checked": len(results), "restricted_matches": len(results),
            "global_matches": sum(row["global_weight_matched"] for row in results),
            "global_negative_states": sum(row["global_negative_exact"] for row in results),
            "delta_negative_states": sum(row["delta_negative_exact"] for row in results),
            "results": results}
