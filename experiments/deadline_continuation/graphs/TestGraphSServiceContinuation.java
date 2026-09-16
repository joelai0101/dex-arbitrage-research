import java.nio.file.*;
import java.util.*;

public class TestGraphSServiceContinuation {
    static long arrivals,debtRows,oldCandidates,checks;
    static void require(boolean ok,String what){if(!ok)throw new AssertionError(what);}
    static void checkCandidate(GraphSServiceContinuation service,Map<Long,Double> live,int k) {
        long before=service.steps();var candidate=service.currentCandidate();
        require(before==service.steps(),"query performed maintenance");
        require(service.backlog()==service.accepted()-service.completed(),"FIFO versions");
        if(candidate.isEmpty())return;
        var c=candidate.get();var p=c.path();
        require(p.size()==k+1&&p.getFirst().equals(p.getLast())&&new HashSet<>(p.subList(0,k)).size()==k,"candidate shape");
        double w=0;for(int i=0;i<k;i++){Double value=live.get(GraphSWeightedBenchmark.edge(p.get(i),p.get(i+1)));require(value!=null,"absent current edge");w+=value;}
        require(w==c.weight()&&w<0&&Double.isFinite(w),"current candidate weight");
        require(c.graphVersion()==service.accepted()&&c.sourceVersion()<=service.completed(),"candidate version");
        if(c.sourceVersion()<c.graphVersion())oldCandidates++;
    }
    static void applyLive(Map<Long,Double> graph,String text) {
        var u=new GraphSWeightedBenchmark.Update(text);long key=GraphSWeightedBenchmark.edge(u.u,u.v);
        if(u.op=='D')graph.remove(key);else if(u.op=='S')graph.put(key,u.weight);
    }
    public static void main(String[] args)throws Exception {
        Path base=Path.of(args[0]);Files.createDirectories(base);
        for(int k:new int[]{3,5})for(int threshold:new int[]{2,6,40}) {
            Path folder=base.resolve("k"+k+"h"+threshold);Files.createDirectory(folder);
            StringBuilder graph=new StringBuilder();for(int u=0;u<6;u++)for(int v=0;v<6;v++)if(u!=v)graph.append(u+" "+v+" -0.2\n");
            Files.writeString(folder.resolve("graph.txt"),graph);Files.writeString(folder.resolve("colors.txt"),"0\n1\n2\n3\n4\n0\n1\n2\n");
            var reference=new GraphSWeightedBenchmark(folder,k,threshold,false);
            var live=new HashMap<>(reference.weights);
            try(var service=new GraphSServiceContinuation(folder,k,threshold)) {
                require(service.currentCandidate().isPresent(),"initial negative fixture");
                long start=service.steps();service.accept("0 1 -0.4");applyLive(live,"0 1 -0.4");
                reference.apply(List.of(new GraphSWeightedBenchmark.Update("0 1 -0.4")));
                require(service.advanceUntil(Long.MAX_VALUE,0)==0&&service.steps()==start,"zero budget");
                require(service.advanceUntil(System.nanoTime()-1,99)==0&&service.steps()==start,"expired budget");
                boolean hidden=false;try{service.inspectCompleted();}catch(IllegalStateException expected){hidden=true;}
                require(hidden,"partial inspection allowed");checkCandidate(service,live,k);arrivals++;debtRows++;
                for(String bad:List.of("0 1 NaN","0 1 Infinity","0 1 1001","-1 0 1","8 1 0","0 1 N extra","0 1 bad")) {
                    long version=service.accepted();boolean rejected=false;
                    try{service.accept(bad);}catch(IllegalArgumentException expected){rejected=true;}
                    require(rejected&&version==service.accepted(),"malformed acceptance");
                }
                List<String> updates=new ArrayList<>(List.of("0 1 N","1 2 D","6 0 -0.1","2 6 -0.3","6 7 -0.4","7 1 -0.2","1 2 -0.5"));
                Random rng=new Random(912+k);for(int i=0;i<95;i++){int u=rng.nextInt(8),v=rng.nextInt(7);if(v>=u)v++;
                    updates.add(u+" "+v+" "+(i%8==0?"N":i%7==0?"D":Double.toString((rng.nextInt(17)-12)/10.0)));}
                int i=0;for(String text:updates) {
                    long before=service.steps();service.accept(text);require(before==service.steps(),"accept maintained core");
                    applyLive(live,text);reference.apply(List.of(new GraphSWeightedBenchmark.Update(text)));arrivals++;
                    service.advanceUntil(Long.MAX_VALUE,1+i%4);checkCandidate(service,live,k);
                    if(service.backlog()>0)debtRows++;
                    if(++i%17==0) {
                        while(service.backlog()>0)service.advanceUntil(Long.MAX_VALUE,13);
                        TestGraphSContinuation.compare(service.inspectCompleted(),reference);checks++;checkCandidate(service,live,k);
                    }
                }
                while(service.backlog()>0)service.advanceUntil(Long.MAX_VALUE,13);
                TestGraphSContinuation.compare(service.inspectCompleted(),reference);checks++;
                var old=service.currentCandidate();
                if(old.isPresent()) {
                    var p=old.get().path();String deletion=p.get(0)+" "+p.get(1)+" D";
                    service.accept(deletion);applyLive(live,deletion);arrivals++;
                    require(service.currentCandidate().isEmpty(),"cached removed edge not rejected");
                }
                // No maintenance: make every currently known edge positive.
                for(long edge:new ArrayList<>(live.keySet())) {
                    String text=GraphSWeightedBenchmark.from(edge)+" "+GraphSWeightedBenchmark.to(edge)+" 0.5";
                    service.accept(text);applyLive(live,text);arrivals++;
                }
                require(service.currentCandidate().isEmpty(),"nonnegative cached cycle published");
                service.advanceUntil(Long.MAX_VALUE,2); // close while a private update is paused
            }
        }
        require(debtRows>0&&oldCandidates>0,"debt/source cases not exercised");
        System.out.println("PASS GraphS service arrivals="+arrivals+" debt_rows="+debtRows+" completed_state_checks="+checks+" older_source_query_observations="+oldCandidates+"; no timed UNI result");
    }
}
