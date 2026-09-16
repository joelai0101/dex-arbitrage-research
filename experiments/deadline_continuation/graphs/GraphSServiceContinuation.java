import experiment.GraphSContinuation;
import java.nio.file.Path;
import java.util.*;

/** Private GraphS engine plus current input graph. No query reads partial indexes. */
public final class GraphSServiceContinuation implements AutoCloseable {
    public record Candidate(List<Integer> path, double weight, long sourceVersion, long graphVersion) {}
    private record Cached(List<Integer> path, long version) {}
    private final GraphSWeightedBenchmark engine;
    private final Map<Long,Double> live;
    private final ArrayDeque<GraphSWeightedBenchmark.Update> pending=new ArrayDeque<>();
    private final GraphSContinuation continuation=new GraphSContinuation();
    private final Thread owner=Thread.currentThread();
    private Cached cached;
    private long accepted, completed;
    private boolean closed;

    public GraphSServiceContinuation(Path folder,int k,int threshold)throws Exception {
        engine=new GraphSWeightedBenchmark(folder,k,threshold,false);
        live=new HashMap<>(engine.weights);capture(0);
    }
    private void checkOpen() {
        if(closed||Thread.currentThread()!=owner)throw new IllegalStateException("open caller-thread service required");
    }
    // Called only after complete apply; no injected checkpoint in publication.
    private void capture(long version) {
        cached=new Cached(engine.ranking.isEmpty()?List.of():List.copyOf(engine.ranking.first().path),version);
    }
    public void accept(String line) {
        checkOpen();String[] parts=line.trim().split("\\s+");
        if(parts.length!=3)throw new IllegalArgumentException("three update fields required");
        var u=new GraphSWeightedBenchmark.Update(line);
        if(u.u<0||u.v<0||u.u>=engine.vertices.size()||u.v>=engine.vertices.size()||
           (u.op=='S'&&(!Double.isFinite(u.weight)||u.weight>1000)))
            throw new IllegalArgumentException("update outside normalized input contract");
        long key=GraphSWeightedBenchmark.edge(u.u,u.v);
        if(u.op=='D')live.remove(key);else if(u.op=='S')live.put(key,u.weight);
        pending.addLast(u);accepted++;
    }
    public long advanceUntil(long deadlineNs,long maxSteps) {
        checkOpen();if(maxSteps<0)throw new IllegalArgumentException("negative step budget");
        long before=continuation.steps();
        while(!pending.isEmpty()&&continuation.steps()-before<maxSteps&&System.nanoTime()<deadlineNs) {
            if(continuation.done()) {
                var next=pending.getFirst();long version=completed+1;
                continuation.start(()->{
                    engine.apply(List.of(next));
                    capture(version);completed=version;pending.removeFirst();
                });
            }
            if(!continuation.advanceUntil(deadlineNs,maxSteps-(continuation.steps()-before)))break;
        }
        return continuation.steps()-before;
    }
    public Optional<Candidate> currentCandidate() {
        checkOpen();List<Integer> path=cached.path();int k=engine.k;
        if(path.size()!=k+1||!path.getFirst().equals(path.getLast()))return Optional.empty();
        double weight=0;
        for(int i=0;i<k;i++) {
            for(int j=0;j<i;j++)if(path.get(i).equals(path.get(j)))return Optional.empty();
            Double w=live.get(GraphSWeightedBenchmark.edge(path.get(i),path.get(i+1)));
            if(w==null||!Double.isFinite(w))return Optional.empty();weight+=w;
        }
        if(!Double.isFinite(weight)||weight>=0)return Optional.empty();
        return Optional.of(new Candidate(List.copyOf(path),weight,cached.version(),accepted));
    }
    public long accepted(){return accepted;}
    public long completed(){return completed;}
    public int backlog(){return pending.size();}
    public long steps(){return continuation.steps();}
    // Test inspection is permitted only when the complete FIFO is drained.
    GraphSWeightedBenchmark inspectCompleted() {
        checkOpen();if(!pending.isEmpty()||!continuation.done())throw new IllegalStateException("partial engine hidden");
        return engine;
    }
    @Override public void close(){checkOpen();continuation.close();closed=true;}
}
