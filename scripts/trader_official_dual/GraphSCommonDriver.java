import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Shared timing/answer boundary; HP-index backend is unchanged. */
public class GraphSCommonDriver {
    static void emit(BufferedWriter out,String phase,int row,double weight,List<Integer> path)throws IOException {
        out.write(phase+"\t"+row+"\t"+weight+"\t");
        for(int i=0;i<path.size();i++) {if(i>0)out.write(' ');out.write(Integer.toString(path.get(i)));}
        out.write("\tglobal\n");
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=4)throw new IllegalArgumentException("case k trace hp_threshold");
        Path folder=Path.of(args[0]);int k=Integer.parseInt(args[1]),threshold=Integer.parseInt(args[3]);
        List<String> updates=Files.readAllLines(folder.resolve("updates.txt"));
        long start=System.nanoTime();
        var engine=new GraphSWeightedBenchmark(folder,k,threshold,false);
        double init=(System.nanoTime()-start)/1e6;
        int initialVertices=engine.simulator.getGraph().vertexSet().size();
        System.err.println("INITIALIZED instances=1 vertices="+initialVertices+" init_ms="+init);
        double weight=Double.POSITIVE_INFINITY;List<Integer> path=new ArrayList<>();
        if(!engine.ranking.isEmpty()) {var answer=engine.ranking.first();weight=answer.weight;path=new ArrayList<>(answer.path);}
        double detection=0;
        try(BufferedWriter output=Files.newBufferedWriter(Path.of(args[2]))) {
            output.write("phase\trow\tweight\tpath\tcoloring\n");emit(output,"initial",0,weight,path);
            for(int row=0;row<updates.size();row++) {
                long begin=System.nanoTime();
                var update=new GraphSWeightedBenchmark.Update(updates.get(row));
                if(update.op=='D'||(update.op=='S'&&(!Double.isFinite(update.weight)||update.weight>1000)))
                    throw new IllegalArgumentException("input is not normalized");
                engine.apply(Collections.singletonList(update));
                if(engine.ranking.isEmpty()) {weight=Double.POSITIVE_INFINITY;path=new ArrayList<>();}
                else {var answer=engine.ranking.first();weight=answer.weight;path=new ArrayList<>(answer.path);}
                detection+=(System.nanoTime()-begin)/1e6;
                emit(output,"arrival",row+1,weight,path);
            }
            long begin=System.nanoTime();
            if(!engine.ranking.isEmpty()) {var answer=engine.ranking.first();weight=answer.weight;path=new ArrayList<>(answer.path);}
            detection+=(System.nanoTime()-begin)/1e6;
            emit(output,"eof",updates.size(),weight,path);output.flush();
            System.out.println("{\"method\":\"GraphS third-party locally adapted\",\"search_scope\":\"all_exact_k\",\"instances\":1,\"k\":"+k+
                ",\"batch\":1,\"updates\":"+updates.size()+",\"queries\":"+updates.size()+",\"init_ms\":"+init+
                ",\"detection_ms\":"+detection+",\"initial_vertices\":"+initialVertices+
                ",\"final_vertices\":"+engine.simulator.getGraph().vertexSet().size()+",\"hp_threshold\":"+threshold+
                ",\"candidates\":"+engine.candidates.size()+",\"graph_edge_visits\":"+engine.simulator.graphEdgeVisits+
                ",\"index_edge_visits\":"+engine.simulator.indexEdgeVisits+",\"cycles_enumerated\":"+engine.cyclesEnumerated+"}");
            System.out.flush();
            // Keep the entire live service resident until OS-peak sampling is acknowledged.
            System.in.read();
        }
    }
}
