"""Apply the local bounded-index change to a hash-pinned backend build copy.

The original third-party/repaired Simulator.java is supplied by the research
workspace, not overwritten or redistributed here. See README for provenance.
"""
import hashlib
from pathlib import Path
import sys

SOURCE_SHA256 = 'e1debeb8db21e0868c9a44acc38d8cacbbf097768c7120a4c64993b927503cd2'

PATCHES = [
    ('    private Predicate<List<CustomVertex>> pathConstraint',
     '    private final Map<CustomVertex, Map<Integer, Map<CustomVertex, Set<HotpointEdge>>>> lengthIndex = new HashMap<>();\n'
     '    private Predicate<List<CustomVertex>> pathConstraint'),
    ('        edgePaths.clear();', '        edgePaths.clear();\n        lengthIndex.clear();'),
    ('''        for (HotpointEdge edge : graphHotpoint.outgoingEdgesOf(h)) {
            ++indexEdgeVisits;
            List<CustomVertex> next = join(prefix, edge.path);
            if (next != null && constraint.test(next)) searchIndex(next, destination, right, result, constraint);
        }''',
     '''        // A path of size L adds L-1 vertices to the prefix. At the exact
        // budget boundary there is no room for another HP edge or a nonempty
        // destination tail, so only paths ending at destination can succeed.
        int maximumSize = pathLength - prefix.size() + 1;
        Map<Integer, Map<CustomVertex, Set<HotpointEdge>>> lengths =
            lengthIndex.getOrDefault(h, Collections.emptyMap());
        for (int size = 2; size <= maximumSize; ++size) {
            Map<CustomVertex, Set<HotpointEdge>> endings = lengths.get(size);
            if (endings == null) continue;
            Collection<Set<HotpointEdge>> groups = size == maximumSize
                ? Collections.singleton(endings.getOrDefault(destination, Collections.emptySet()))
                : endings.values();
            for (Set<HotpointEdge> group : groups) for (HotpointEdge edge : group) {
                ++indexEdgeVisits;
                List<CustomVertex> next = join(prefix, edge.path);
                if (next != null && constraint.test(next)) searchIndex(next, destination, right, result, constraint);
            }
        }'''),
    ('        graphHotpoint.addEdge(first, last, indexed);',
     '''        graphHotpoint.addEdge(first, last, indexed);
        lengthIndex.computeIfAbsent(first, x -> new HashMap<>())
            .computeIfAbsent(path.size(), x -> new HashMap<>())
            .computeIfAbsent(last, x -> new LinkedHashSet<>()).add(indexed);'''),
    ('        graphHotpoint.removeEdge(indexed);',
     '''        graphHotpoint.removeEdge(indexed);
        CustomVertex first = indexed.path.get(0);
        CustomVertex last = indexed.path.get(indexed.path.size() - 1);
        Map<Integer, Map<CustomVertex, Set<HotpointEdge>>> lengths = lengthIndex.get(first);
        Map<CustomVertex, Set<HotpointEdge>> endings = lengths.get(indexed.path.size());
        Set<HotpointEdge> pathsOfLength = endings.get(last);
        pathsOfLength.remove(indexed);
        if (pathsOfLength.isEmpty()) endings.remove(last);
        if (endings.isEmpty()) lengths.remove(indexed.path.size());
        if (lengths.isEmpty()) lengthIndex.remove(first);'''),
]


def prepare(source, output):
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('Unexpected backend source; do not patch an unverified revision')
    code = raw.decode('utf-8').replace('\r\n', '\n')
    for old, new in PATCHES:
        if code.count(old) != 1:
            raise ValueError('Backend patch context must occur exactly once')
        code = code.replace(old, new)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    output.write_bytes(code.encode('utf-8'))


if __name__ == '__main__':
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
