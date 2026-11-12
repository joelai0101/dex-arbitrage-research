import experiment.GraphSContinuation;
import backend.*;
import java.nio.file.*;
import java.util.*;

/** Correctness gate only. Draining jobs here is never a timed service protocol. */
public class TestGraphSContinuation {
    static long checks, pauses, steps;
    static void require(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    static Set<String> paths(GraphSWeightedBenchmark e, int u, int v) {
        Set<String> result = new TreeSet<>();
        for (var p : e.simulator.findPaths(e.vertices.get(u), e.vertices.get(v))) {
            List<String> ids = new ArrayList<>(); for (var x:p) ids.add(x.getId());
            result.add(ids.toString());
        }
        return result;
    }
    static List<String> index(GraphSWeightedBenchmark e) {
        List<String> result = new ArrayList<>();
        for (var p:e.simulator.getGraphHotpoint().edgeSet()) {
            List<String> ids=new ArrayList<>();for(var x:p.path)ids.add(x.getId());
            result.add(ids.toString());
        }
        Collections.sort(result);return result;
    }
    static void compare(GraphSWeightedBenchmark a, GraphSWeightedBenchmark b) {
        require(a.weights.equals(b.weights), "weights");
        require(a.candidates.keySet().equals(b.candidates.keySet()), "candidate keys");
        for(var p:a.candidates.keySet())require(a.candidates.get(p).weight==b.candidates.get(p).weight,"candidate score");
        var ar=new ArrayList<>(a.ranking);var br=new ArrayList<>(b.ranking);
        require(ar.size()==br.size(),"ranking size");
        for(int i=0;i<ar.size();i++)require(ar.get(i).path.equals(br.get(i).path)&&ar.get(i).weight==br.get(i).weight,"ranking");
        require(index(a).equals(index(b)),"index paths with multiplicity");
        for(int u=0;u<a.vertices.size();u++) {
            boolean present=a.simulator.getGraph().containsVertex(a.vertices.get(u));
            require(present==b.simulator.getGraph().containsVertex(b.vertices.get(u)),"vertices");
            if(!present)continue;
            require(a.vertices.get(u).getHotPoint()==b.vertices.get(u).getHotPoint(),"HP membership");
            for(int v=0;v<a.vertices.size();v++)if(a.simulator.getGraph().containsVertex(a.vertices.get(v)))
                require(paths(a,u,v).equals(paths(b,u,v)),"all-pair bounded paths");
        }
        checks++;
    }
    static void primitive() {
        Thread caller=Thread.currentThread();int[] sum={0},cleanup={0};
        try(var c=new GraphSContinuation()) {
            c.start(()->{try{for(int i=0;i<17;i++){GraphSContinuation.checkpoint();require(Thread.currentThread()==caller,"worker thread");sum[0]+=i;}}finally{cleanup[0]++;}});
            require(!c.advanceUntil(Long.MAX_VALUE,0)&&c.steps()==0&&sum[0]==0,"zero budget");
            require(!c.advanceUntil(System.nanoTime()-1,99)&&c.steps()==0,"expired budget");
            while(!c.advanceUntil(Long.MAX_VALUE,1))pauses++;
            require(sum[0]==136&&cleanup[0]==1,"locals survive yields");steps+=c.steps();
            c.start(()->{throw new IllegalArgumentException("test error");});
            boolean caught=false;try{c.advanceUntil(Long.MAX_VALUE,10);}catch(IllegalArgumentException expected){caught=true;}
            require(caught&&c.done(),"exception propagation");
            c.start(()->{try{while(true)GraphSContinuation.checkpoint();}finally{cleanup[0]++;}});
            c.advanceUntil(Long.MAX_VALUE,3);
        }
        require(cleanup[0]==2,"cancel unwinds finally");
    }
    public static void main(String[] args)throws Exception {
        primitive();Path root=Path.of(args[0]);Files.createDirectories(root);
        for(int k:new int[]{3,5})for(int threshold:new int[]{2,6,40}) {
            Path folder=root.resolve("k"+k+"h"+threshold);Files.createDirectory(folder);
            StringBuilder graph=new StringBuilder();
            for(int u=0;u<6;u++)for(int v=0;v<6;v++)if(u!=v&&(u+v)%3!=0)graph.append(u+" "+v+" -0.2\n");
            Files.writeString(folder.resolve("graph.txt"),graph);
            Files.writeString(folder.resolve("colors.txt"),"0\n1\n2\n3\n4\n0\n1\n2\n");
            var reference=new GraphSWeightedBenchmark(folder,k,threshold,false);
            var actual=new GraphSWeightedBenchmark(folder,k,threshold,false);
            compare(actual,reference);
            List<String> updates=new ArrayList<>(List.of("0 1 0.7","0 1 -0.8","0 1 N","0 1 D","0 1 -0.3",
                "6 0 -0.4","1 6 -0.5","6 7 -0.1","7 2 -0.2","6 7 D","6 7 -0.6"));
            Random rng=new Random(520+k);
            for(int i=0;i<45;i++){int u=rng.nextInt(8),v=rng.nextInt(7);if(v>=u)v++;
                updates.add(u+" "+v+" "+(i%7==0?"D":i%9==0?"N":Double.toString((rng.nextInt(17)-12)/10.0)));}
            try(var c=new GraphSContinuation();var other=new GraphSContinuation()) {
                int[] otherCount={0};other.start(()->{for(int j=0;j<10000;j++){GraphSContinuation.checkpoint();otherCount[0]++;}});
                for(String line:updates) {
                    var row=List.of(new GraphSWeightedBenchmark.Update(line));
                    reference.apply(row);c.start(()->actual.apply(row));
                    while(!c.advanceUntil(Long.MAX_VALUE,1+(checks%5))) {
                        pauses++;long before=c.steps();other.advanceUntil(Long.MAX_VALUE,1);
                        require(c.steps()==before,"other continuation advanced this engine");
                        // Never inspect partially-mutated GraphS state here.
                    }
                    compare(actual,reference);
                }
                steps+=c.steps();require(otherCount[0]>0,"interleaved job unused");
            }
        }
        System.out.println("PASS GraphS continuation completed-state checks="+checks+" pauses="+pauses+" steps="+steps+"; not a deadline service or UNI benchmark");
    }
}
