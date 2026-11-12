import java.io.*;
import java.nio.file.*;
import java.util.*;

public class RunGraphSWindow {
    record Record(GraphSWindow.Response response,long start,long end) {}
    static void require(boolean ok,String what){if(!ok)throw new AssertionError(what);}
    static void unit(Path folder)throws Exception {
        try(var service=new GraphSServiceContinuation(folder,3,6)) {
            var input=new BufferedReader(new StringReader("0 1 -0.7\n0 1 N\n0 1 bad\n"));
            long start=System.nanoTime();var r=GraphSWindow.serve(service,input,start,0,0);long end=System.nanoTime();
            require(r.acceptedVersion()==1&&r.completedVersion()==0&&r.backlog()==1,"zero acceptance");
            require(r.stepsBefore()==r.stepsAfter()&&r.candidate().isPresent(),"zero maintenance");
            require(start<=r.read()&&r.read()<=r.accepted()&&r.accepted()<=r.maintained()&&r.maintained()<=r.validated()&&r.validated()<=end,"timestamps");
            r=GraphSWindow.serve(service,input,System.nanoTime()-1_000_000_000);
            require(r.acceptedVersion()==2&&r.completedVersion()==0&&r.stepsBefore()==r.stepsAfter(),"expired maintenance");
            boolean rejected=false;try{GraphSWindow.serve(service,input,System.nanoTime());}catch(IllegalArgumentException expected){rejected=true;}
            require(rejected&&service.accepted()==2,"parse rejection");
        }
        System.out.println("PASS GraphS window zero/expired, parse rejection, timestamps");
    }
    public static void main(String[] args)throws Exception {
        if(args.length==2&&args[0].equals("--unit")){unit(Path.of(args[1]));return;}
        boolean full=args.length==4&&args[3].equals("--full");
        if(args.length!=3&&!full)throw new IllegalArgumentException("case output-csv frozen-golden-trace [--full]");
        Path folder=Path.of(args[0]);final int count=full?7628:32,k=5;
        List<Record> records=new ArrayList<>(count);
        try(var service=new GraphSServiceContinuation(folder,k,40);var input=Files.newBufferedReader(folder.resolve("updates.txt"))) {
            System.err.println("STAGE initialized; "+count+" complete-window pilot starting");
            long previous=0;
            for(int i=0;i<count;i++) {
                require(service.steps()==previous,"maintenance between windows");
                long start=System.nanoTime();var response=GraphSWindow.serve(service,input,start);long end=System.nanoTime();
                previous=response.stepsAfter();records.add(new Record(response,start,end));
            }
            if(full)require(input.readLine()==null,"expected full UNI1 stream");
            // close discards any paused private engine. No maintenance or EOF flush.
        }
        Map<Long,Double> live=new HashMap<>();
        for(String line:Files.readAllLines(folder.resolve("graph.txt")))TestGraphSServiceContinuation.applyLive(live,line);
        Map<Integer,Double> golden=new HashMap<>();
        for(String line:Files.readAllLines(Path.of(args[2]))) {
            String[] p=line.split("\t",-1);if(p[0].equals("arrival"))golden.put(Integer.parseInt(p[1]),Double.parseDouble(p[2]));
        }
        int late=0,missing=0,older=0,completeChecks=0,maxDebt=0;long maxReturn=0;
        try(var out=Files.newBufferedWriter(Path.of(args[1]))) {
            out.write("row,accepted_version,completed_version,backlog,steps_before,steps_after,read_ns,accept_ns,maintenance_ns,validation_ns,return_ns,actual_return_ns,late,source_version,weight,path\n");
            for(int i=0;i<count;i++) {
                var record=records.get(i);var r=record.response();long total=record.end()-record.start();
                TestGraphSServiceContinuation.applyLive(live,r.line());
                require(r.acceptedVersion()==i+1&&r.backlog()==r.acceptedVersion()-r.completedVersion(),"versions");
                require(record.start()<=r.read()&&r.read()<=r.accepted()&&r.accepted()<=r.maintained()&&r.maintained()<=r.validated()&&r.validated()<=record.end(),"phase order");
                if(i>0)require(r.stepsBefore()==records.get(i-1).response().stepsAfter(),"work outside window");
                boolean isLate=total>10_000_000;if(isLate)late++;maxReturn=Math.max(maxReturn,total);maxDebt=Math.max(maxDebt,r.backlog());
                out.write((i+1)+","+r.acceptedVersion()+","+r.completedVersion()+","+r.backlog()+","+r.stepsBefore()+","+r.stepsAfter()+","+
                    (r.read()-record.start())+","+(r.accepted()-r.read())+","+(r.maintained()-r.accepted())+","+(r.validated()-r.maintained())+","+
                    (record.end()-r.validated())+","+total+","+(isLate?1:0)+",");
                if(r.candidate().isEmpty()){missing++;out.write(",,\n");continue;}
                var c=r.candidate().get();var p=c.path();
                require(p.size()==k+1&&p.getFirst().equals(p.getLast())&&new HashSet<>(p.subList(0,k)).size()==k,"cycle shape");
                double w=0;for(int j=0;j<k;j++){Double value=live.get(GraphSWeightedBenchmark.edge(p.get(j),p.get(j+1)));require(value!=null,"missing current edge");w+=value;}
                require(w==c.weight()&&w<0&&Double.isFinite(w)&&c.sourceVersion()<=r.completedVersion()&&c.graphVersion()==i+1,"current cycle/version");
                if(c.sourceVersion()<i+1)older++;
                if(r.completedVersion()==i+1){require(Math.abs(w-golden.get(i+1))<=1e-10,"completed answer differs from frozen baseline");completeChecks++;}
                out.write(c.sourceVersion()+","+Double.toString(w)+",\"");for(int vertex:p)out.write(vertex+" ");out.write("\"\n");
            }
        }
        System.out.println("PASS GraphS UNI1-"+count+" protocol audit late="+late+" missing="+missing+" older_source="+older+
            " completed_golden_checks="+completeChecks+" max_backlog="+maxDebt+" eof_backlog="+records.getLast().response().backlog()+
            " max_return_ns="+maxReturn+"; single-run local protocol, quality scored separately");
    }
}
