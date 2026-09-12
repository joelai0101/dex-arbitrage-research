import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Single uncolored exact-k HP-Index adapter for TRADER Table III comparison. */
public class GraphSPaperDriver {
    static void emit(BufferedWriter out, int row, GraphSWeightedBenchmark engine) throws IOException {
        out.write(Integer.toString(row)); out.write('\t');
        if (engine.ranking.isEmpty()) out.write("none\t");
        else {
            var answer = engine.ranking.first();
            out.write(Double.toString(answer.weight)); out.write('\t');
            for (int i=0;i<answer.path.size();i++) {
                if (i>0) out.write(' ');
                out.write(Integer.toString(answer.path.get(i)));
            }
        }
        out.newLine();
    }
    public static void main(String[] args) throws Exception {
        if (args.length!=4) throw new IllegalArgumentException("case k trace hp_threshold");
        Path folder=Path.of(args[0]); int k=Integer.parseInt(args[1]);
        int threshold=Integer.parseInt(args[3]);
        long start=System.nanoTime();
        // false disables every color filter, including HP-Index path filtering.
        // colors.txt supplies the declared vertex count only, not a search restriction.
        var engine=new GraphSWeightedBenchmark(folder,k,threshold,false);
        double init=(System.nanoTime()-start)/1e6;
        System.err.println("INITIALIZED instances=1 search_scope=all_exact_k init_ms="+init);
        try (BufferedWriter output=Files.newBufferedWriter(Path.of(args[2]))) {
            output.write("row\tweight\tpath\n"); emit(output,0,engine);
            int rows=0; double core=0; start=System.nanoTime();
            try (BufferedReader input=Files.newBufferedReader(folder.resolve("updates.txt"))) {
                String line;
                while ((line=input.readLine())!=null) {
                    var update=new GraphSWeightedBenchmark.Update(line);
                    if(update.op=='D') throw new IllegalArgumentException("deletion outside formal common domain");
                    long begin=System.nanoTime(); engine.apply(Collections.singletonList(update));
                    core+=(System.nanoTime()-begin)/1e6;
                    emit(output,++rows,engine);
                }
            }
            output.flush(); double online=(System.nanoTime()-start)/1e6;
            System.out.println("{\"method\":\"GraphS-paper-aligned\",\"search_scope\":\"all_exact_k\",\"instances\":1,\"k\":"+k+
                ",\"batch\":1,\"rows\":"+rows+",\"queries\":"+rows+",\"init_ms\":"+init+",\"online_ms\":"+online+
                ",\"core_ms\":"+core+",\"hp_threshold\":"+threshold+",\"candidates\":"+engine.candidates.size()+
                ",\"graph_edge_visits\":"+engine.simulator.graphEdgeVisits+",\"index_edge_visits\":"+engine.simulator.indexEdgeVisits+
                ",\"cycles_enumerated\":"+engine.cyclesEnumerated+"}");
            System.out.flush();
            // Same post-timing OS peak-memory handshake as the existing driver.
            System.in.read();
        }
    }
}
