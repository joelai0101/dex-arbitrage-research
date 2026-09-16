import java.io.*;
import java.util.Optional;

/** Complete in-process window. Caller owns both boundary timestamps. */
public final class GraphSWindow {
    public record Response(String line,Optional<GraphSServiceContinuation.Candidate> candidate,
        long read,long accepted,long maintained,long validated,long acceptedVersion,
        long completedVersion,int backlog,long stepsBefore,long stepsAfter) {}
    public static Response serve(GraphSServiceContinuation service,BufferedReader input,long start)throws IOException {
        return serve(service,input,start,10_000_000,1_000_000);
    }
    public static Response serve(GraphSServiceContinuation service,BufferedReader input,long start,
                                 long budgetNs,long reserveNs)throws IOException {
        if(budgetNs<0||reserveNs<0||reserveNs>budgetNs)throw new IllegalArgumentException("invalid window policy");
        long before=service.steps();String line=input.readLine();
        if(line==null)throw new EOFException("missing update");
        long read=System.nanoTime();service.accept(line);long accepted=System.nanoTime();
        service.advanceUntil(start+budgetNs-reserveNs,Long.MAX_VALUE);long maintained=System.nanoTime();
        var candidate=service.currentCandidate();long validated=System.nanoTime();
        return new Response(line,candidate,read,accepted,maintained,validated,service.accepted(),
                            service.completed(),service.backlog(),before,service.steps());
    }
}
