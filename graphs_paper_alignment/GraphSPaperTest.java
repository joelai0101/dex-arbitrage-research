import java.nio.file.*;
import java.util.*;

/** Independent adjacency-matrix oracle; no HP-Index calls in expected answers. */
public class GraphSPaperTest {
    static double best;
    static Map<List<Integer>,Double> allCandidates;
    static void enumerateCandidates(double[][] g,int root,List<Integer> path,boolean[] used,int k) {
        int last=path.get(path.size()-1);
        if(path.size()==k) {
            if(!Double.isFinite(g[last][root]))return;
            var cycle=new ArrayList<>(path);cycle.add(root);double weight=0;
            for(int i=1;i<cycle.size();i++)weight+=g[cycle.get(i-1)][cycle.get(i)];
            allCandidates.put(cycle,weight);return;
        }
        for(int next=root+1;next<g.length;next++)if(!used[next]&&Double.isFinite(g[last][next])) {
            used[next]=true;path.add(next);enumerateCandidates(g,root,path,used,k);
            path.remove(path.size()-1);used[next]=false;
        }
    }
    static void dfs(double[][] g,int root,int v,int left,boolean[] used,double w) {
        if(left==0) { if(Double.isFinite(g[v][root]))best=Math.min(best,w+g[v][root]); return; }
        for(int next=0;next<g.length;next++)if(!used[next]&&Double.isFinite(g[v][next])) {
            used[next]=true; dfs(g,root,next,left-1,used,w+g[v][next]); used[next]=false;
        }
    }
    static double expected(double[][] g,int k) {
        best=Double.POSITIVE_INFINITY;
        allCandidates=new HashMap<>();
        for(int root=0;root<g.length;root++) {
            boolean[] used=new boolean[g.length]; used[root]=true; dfs(g,root,root,k-1,used,0);
            enumerateCandidates(g,root,new ArrayList<>(List.of(root)),used,k);
        }
        return best;
    }
    static void verify(GraphSWeightedBenchmark e,double[][] g,int k,double reference) {
        double actual=e.ranking.isEmpty()?Double.POSITIVE_INFINITY:e.ranking.first().weight;
        if(actual!=reference && Math.abs(actual-reference)>1e-10)throw new AssertionError(actual+" != "+reference);
        if(!e.candidates.keySet().equals(allCandidates.keySet())||e.ranking.size()!=allCandidates.size())
            throw new AssertionError("incomplete or duplicate global candidate cache");
        for(var entry:allCandidates.entrySet())
            if(Math.abs(e.candidates.get(entry.getKey()).weight-entry.getValue())>1e-10)
                throw new AssertionError("stale non-best candidate");
        if(!e.ranking.isEmpty()) {
            var p=e.ranking.first().path;
            if(p.size()!=k+1||!p.get(0).equals(p.get(k))||new HashSet<>(p.subList(0,k)).size()!=k)throw new AssertionError("invalid cycle");
            double weight=0;for(int i=1;i<p.size();i++)weight+=g[p.get(i-1)][p.get(i)];
            if(Math.abs(weight-actual)>1e-10)throw new AssertionError("stale weight");
        }
    }
    public static void main(String[] args)throws Exception {
        Path base=Path.of(args[0]);Files.createDirectories(base); int checks=0;
        for(int k=3;k<=5;k++)for(int seed=0;seed<20;seed++) {
            int n=7;Random rng=new Random(seed+1000*k);double[][] g=new double[n][n];
            StringBuilder edges=new StringBuilder(),zero=new StringBuilder(),random=new StringBuilder();
            for(int u=0;u<n;u++) {
                zero.append("0\n");random.append(rng.nextInt(k)).append('\n');
                for(int v=0;v<n;v++){g[u][v]=Double.POSITIVE_INFINITY;
                    if(u!=v&&rng.nextDouble()<.28){g[u][v]=(rng.nextInt(17)-8)/4.0;edges.append(u+" "+v+" "+g[u][v]+"\n");}}
            }
            Path a=base.resolve("k"+k+"_s"+seed+"_zero"),b=base.resolve("k"+k+"_s"+seed+"_random");
            Files.createDirectories(a);Files.createDirectories(b);
            for(Path dir:List.of(a,b))Files.writeString(dir.resolve("graph.txt"),edges);
            Files.writeString(a.resolve("colors.txt"),zero);Files.writeString(b.resolve("colors.txt"),random);
            var first=new GraphSWeightedBenchmark(a,k,3,false);
            var second=new GraphSWeightedBenchmark(b,k,3,false);
            for(int row=0;row<=40;row++) {
                double reference=expected(g,k);verify(first,g,k,reference);verify(second,g,k,reference);checks+=2;
                if(row==40)break;
                int u=rng.nextInt(n),v=rng.nextInt(n-1);if(v>=u)v++;
                String value=row%11==0?"N":row%7==0?"D":Double.toString((rng.nextInt(25)-12)/4.0);
                var update=new GraphSWeightedBenchmark.Update(u+" "+v+" "+value);
                if(value.equals("D"))g[u][v]=Double.POSITIVE_INFINITY;
                else if(!value.equals("N"))g[u][v]=Double.parseDouble(value);
                first.apply(Collections.singletonList(update));second.apply(Collections.singletonList(update));
            }
        }
        System.out.println("GraphS uncolored oracle/recoloring checks passed: "+checks);
    }
}
