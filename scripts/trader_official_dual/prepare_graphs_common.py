"""Generate only input-layer changes; reuse hash-pinned HP-index class files."""
import difflib
from pathlib import Path

from prepare_source import replace_once
from run_uni1_official import sha

SOURCE_SHA='cb62c52a92df56e867a7527ebc5ff833aa7db6fb7d999d85a5718b91519e5fe2'


def prepare(source:Path,output:Path):
    assert sha(source)==SOURCE_SHA
    original=source.read_text(encoding='utf-8')
    text=replace_once(original,
        '        for(int i=0;i<colors.length;i++){CustomVertex v=new CustomVertex(""+i);vertices.add(v);graph.addVertex(v);}',
        '''        for(int i=0;i<colors.length;i++)vertices.add(new CustomVertex(""+i));
        // Reserve IDs, but materialize only initially observed graph vertices.
        Set<Integer> initiallyPresent=new TreeSet<>();
        try(BufferedReader input=Files.newBufferedReader(folder.resolve("graph.txt"))){String line;
            while((line=input.readLine())!=null){Update u=new Update(line);initiallyPresent.add(u.u);initiallyPresent.add(u.v);}}
        for(int id:initiallyPresent)graph.addVertex(vertices.get(id));''')
    text=replace_once(text,'        for(int root=0;root<colors.length;root++) {',
        '        for(int root=0;root<colors.length;root++) {\n            if(!graph.containsVertex(vertices.get(root)))continue;')
    text=replace_once(text,'            } else if(old==null) {\n                weights.put(e,u.weight);',
        '''            } else if(old==null) {
                // Input-only vertex insertion through the backend's public graphs.
                for(int id:new int[]{u.u,u.v}) {
                    var vertex=vertices.get(id);
                    if(!simulator.getGraph().containsVertex(vertex)) {
                        simulator.getGraph().addVertex(vertex);
                        simulator.getGraphRev().addVertex(vertex);
                    }
                }
                weights.put(e,u.weight);''')
    output.write_text(text,encoding='utf-8')
    output.with_suffix('.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),
        fromfile='frozen/GraphSWeightedBenchmark.java',tofile='common/GraphSWeightedBenchmark.java')),encoding='utf-8')
