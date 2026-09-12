import backend.*;
import org.jgrapht.Graph;
import org.jgrapht.graph.DefaultDirectedGraph;
import java.nio.file.*;
import java.io.*;
import java.util.*;

/** Weighted-cycle adapter around the repaired paper HP-Index; not a DELTA/CPE kernel. */
public class GraphSWeightedBenchmark {
    static long edge(int u,int v){return ((long)u<<32)|(v&0xffffffffL);}
    static int from(long e){return (int)(e>>32);}
    static int to(long e){return (int)e;}
    static class Candidate implements Comparable<Candidate> {
        List<Integer> path;double weight;
        Candidate(List<Integer> p,double w){path=p;weight=w;}
        public int compareTo(Candidate b){
            int c=Double.compare(weight,b.weight);if(c!=0)return c;
            for(int i=0;i<path.size();i++){c=Integer.compare(path.get(i),b.path.get(i));if(c!=0)return c;}
            return 0;
        }
    }
    static class Update {int u,v;double weight;char op;
        Update(String line){String[] p=line.trim().split("\\s+");u=Integer.parseInt(p[0]);v=Integer.parseInt(p[1]);
            op=p[2].equals("N")?'N':p[2].equals("D")?'D':'S';weight=op=='S'?Double.parseDouble(p[2]):0;}}
    final List<CustomVertex> vertices=new ArrayList<>();
    final Map<Long,Double> weights=new HashMap<>();
    final Map<List<Integer>,Candidate> candidates=new HashMap<>();
    final TreeSet<Candidate> ranking=new TreeSet<>();
    final int[] colors;final int k;final boolean colorful;Simulator simulator;
    long cyclesEnumerated;

    GraphSWeightedBenchmark(Path folder,int hops,int threshold)throws Exception {
        this(folder,hops,threshold,true);
    }
    GraphSWeightedBenchmark(Path folder,int hops,int threshold,boolean filter)throws Exception {
        colorful=filter;
        k=hops;colors=Files.readAllLines(folder.resolve("colors.txt")).stream().mapToInt(Integer::parseInt).toArray();
        Graph<CustomVertex,CustomEdge> graph=new DefaultDirectedGraph<>(CustomEdge.class);
        for(int i=0;i<colors.length;i++){CustomVertex v=new CustomVertex(""+i);vertices.add(v);graph.addVertex(v);}
        try(BufferedReader input=Files.newBufferedReader(folder.resolve("graph.txt"))){String line;
            while((line=input.readLine())!=null){Update u=new Update(line);weights.put(edge(u.u,u.v),u.weight);
                // Shared fixed-color query constraint: same-color edges cannot belong to a colorful cycle.
                if(!colorful||colors[u.u]!=colors[u.v])graph.addEdge(vertices.get(u.u),vertices.get(u.v),new CustomEdge(true,0));}}
        simulator=new Simulator(graph,k,threshold,path->allowed(path,0));
        System.err.println("STAGE hp_index_ready; building weighted global candidate cache");
        for(int root=0;root<colors.length;root++) {
            final int minimum=root;
            for(CustomEdge closing:graph.incomingEdgesOf(vertices.get(root))) {
                int end=Integer.parseInt(closing.getSource().getId());if(end<=root)continue;
                for(List<CustomVertex> p:simulator.findPaths(vertices.get(root),closing.getSource(),path->allowed(path,minimum))) {
                    List<CustomVertex> closed=new ArrayList<>(p);closed.add(vertices.get(root));
                    List<Integer> key=canonical(closed);if(key!=null)refresh(key);
                }
            }
        }
        simulator.graphEdgeVisits=simulator.indexEdgeVisits=0;cyclesEnumerated=0;
    }
    boolean allowed(List<CustomVertex> path,int minimum) {
        int mask=0;
        for(CustomVertex v:path){int id=Integer.parseInt(v.getId());if(id<minimum)return false;
            if(colorful){int bit=1<<colors[id];if((mask&bit)!=0)return false;mask|=bit;}}
        return true;
    }
    List<Integer> canonical(List<CustomVertex> cycle) {
        ++cyclesEnumerated;if(cycle.size()!=k+1)return null;
        List<CustomVertex> body=cycle.subList(0,k);if(!allowed(body,0))return null;
        int start=0;int[] ids=new int[k];
        for(int i=0;i<k;i++){ids[i]=Integer.parseInt(cycle.get(i).getId());if(ids[i]<ids[start])start=i;}
        List<Integer> key=new ArrayList<>();for(int i=0;i<k;i++)key.add(ids[(start+i)%k]);key.add(key.get(0));return key;
    }
    List<List<Integer>> affected(int u,int v) {
        List<List<Integer>> result=new ArrayList<>();if(colorful&&colors[u]==colors[v])return result;
        for(List<CustomVertex> p:simulator.findPaths(vertices.get(v),vertices.get(u),path->allowed(path,0))) {
            List<CustomVertex> closed=new ArrayList<>();closed.add(vertices.get(u));closed.addAll(p);
            List<Integer> key=canonical(closed);if(key!=null)result.add(key);
        }
        return result;
    }
    void remove(List<Integer> path){Candidate old=candidates.remove(path);if(old!=null)ranking.remove(old);}
    void refresh(List<Integer> path){
        double sum=0;for(int i=1;i<path.size();i++) {Double w=weights.get(edge(path.get(i-1),path.get(i)));
            if(w==null){remove(path);return;}sum+=w;}
        remove(path);Candidate c=new Candidate(path,sum);candidates.put(path,c);ranking.add(c);
    }
    void apply(List<Update> rows) {
        Map<Long,Update> last=new LinkedHashMap<>();for(Update u:rows)if(u.op!='N')last.put(edge(u.u,u.v),u);
        Set<List<Integer>> dirty=new HashSet<>();List<Update> weightChanges=new ArrayList<>();
        for(Update u:last.values()) {
            long e=edge(u.u,u.v);Double old=weights.get(e);
            if(u.op=='D') {
                if(old==null)continue;
                for(List<Integer> path:affected(u.u,u.v))remove(path);
                if(!colorful||colors[u.u]!=colors[u.v])simulator.removeEdge(vertices.get(u.u),vertices.get(u.v));
                weights.remove(e);
            } else if(old==null) {
                weights.put(e,u.weight);
                if(!colorful||colors[u.u]!=colors[u.v])
                    for(List<CustomVertex> cycle:simulator.insertEdge(vertices.get(u.u),vertices.get(u.v),new CustomEdge(true,0))) {
                        List<Integer> path=canonical(cycle);if(path!=null)dirty.add(path);
                    }
            } else if(old.doubleValue()!=u.weight) {weights.put(e,u.weight);weightChanges.add(u);}
        }
        // Newly inserted cycles were captured by their last inserted edge; changed old edges are queried on the final graph.
        for(Update u:weightChanges)dirty.addAll(affected(u.u,u.v));
        for(List<Integer> path:dirty)refresh(path);
    }
    void emit(StringBuilder out,int row) {
        out.append(row).append('\t');
        if(ranking.isEmpty()){out.append("none\t\n");return;}
        Candidate c=ranking.first();out.append(c.weight).append('\t');
        for(int i=0;i<c.path.size();i++){if(i>0)out.append(' ');out.append(c.path.get(i));}out.append('\n');
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=5 && !(args.length==6 && args[5].equals("--all-cycles")))throw new IllegalArgumentException("case k batch trace hp_threshold [--all-cycles]");
        Path folder=Paths.get(args[0]);int k=Integer.parseInt(args[1]),batch=Integer.parseInt(args[2]),threshold=Integer.parseInt(args[4]);
        boolean colorful=args.length==5;
        long begin=System.nanoTime();GraphSWeightedBenchmark engine=new GraphSWeightedBenchmark(folder,k,threshold,colorful);
        double initMs=(System.nanoTime()-begin)/1e6;
        System.err.println("STAGE initialized; init_ms="+initMs+"; starting online updates");
        StringBuilder initial=new StringBuilder();engine.emit(initial,0);
        begin=System.nanoTime();StringBuilder out=new StringBuilder();List<Update> pending=new ArrayList<>();int rows=0,queries=0;
        try(BufferedReader input=Files.newBufferedReader(folder.resolve("updates.txt"))) {String line;
            while((line=input.readLine())!=null){pending.add(new Update(line));rows++;
                if(pending.size()==batch){engine.apply(pending);engine.emit(out,rows);pending.clear();queries++;}}
            if(!pending.isEmpty()){engine.apply(pending);engine.emit(out,rows);queries++;}
        }
        double onlineMs=(System.nanoTime()-begin)/1e6;
        Files.writeString(Paths.get(args[3]),"row\tweight\tpath\n"+initial+out);
        System.out.println("{\"method\":\"GraphS-W\",\"search_scope\":\""+(colorful?"common_coloring":"all_exact_k")+"\",\"init_ms\":"+initMs+",\"online_ms\":"+onlineMs+",\"rows\":"+rows+",\"queries\":"+queries+
            ",\"hp_threshold\":"+threshold+",\"hotpoints\":"+engine.simulator.getGraphHotpoint().vertexSet().size()+
            ",\"index_paths\":"+engine.simulator.getGraphHotpoint().edgeSet().size()+",\"candidates\":"+engine.candidates.size()+
            ",\"graph_edge_visits\":"+engine.simulator.graphEdgeVisits+",\"index_edge_visits\":"+engine.simulator.indexEdgeVisits+
            ",\"cycles_enumerated\":"+engine.cyclesEnumerated+"}");
    }
}
