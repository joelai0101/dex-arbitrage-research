package experiment;

import jdk.internal.vm.Continuation;
import jdk.internal.vm.ContinuationScope;

/** Isolated JDK-25 experiment, not a supported/public Java API or hard deadline. */
public final class GraphSContinuation implements AutoCloseable {
    private static final ThreadLocal<GraphSContinuation> ACTIVE = new ThreadLocal<>();
    private static final class Cancelled extends RuntimeException {}
    private final Thread owner = Thread.currentThread();
    private final ContinuationScope scope = new ContinuationScope("GraphS-private-job");
    private Continuation task;
    private long deadline, remaining, steps;
    private boolean cancel, closed;

    private void ownerCheck() {
        if (Thread.currentThread() != owner || ACTIVE.get() != null || closed)
            throw new IllegalStateException("same caller thread, no nesting, open instance required");
    }
    public void start(Runnable work) {
        ownerCheck();
        if (!done()) throw new IllegalStateException("unfinished job");
        cancel = false;
        task = new Continuation(scope, () -> {
            try { check(); work.run(); }
            catch (Cancelled discarded) { /* Only for discarding the private engine. */ }
        });
    }
    public boolean done() { return task == null || task.isDone(); }
    public long steps() { return steps; }
    private void run() {
        ACTIVE.set(this);
        try { task.run(); } finally { ACTIVE.remove(); }
    }
    public boolean advanceUntil(long deadlineNs, long maxSteps) {
        ownerCheck();
        if (maxSteps < 0) throw new IllegalArgumentException("negative step budget");
        if (done()) return true;
        if (maxSteps == 0 || System.nanoTime() >= deadlineNs) return false;
        deadline = deadlineNs; remaining = maxSteps;
        run();
        return done();
    }
    private void check() {
        if (cancel) throw new Cancelled();
        if (remaining == 0 || System.nanoTime() >= deadline) {
            if (!Continuation.yield(scope)) throw new IllegalStateException("continuation could not yield");
            if (cancel) throw new Cancelled();
        }
        remaining--; steps++;
    }
    public static void checkpoint() {
        GraphSContinuation current = ACTIVE.get();
        if (current != null) current.check();
    }
    @Override public void close() {
        ownerCheck();
        if (!done()) { cancel = true; run(); }
        closed = true;
        // Cancellation unwinds finally blocks, not a rollback. Discard that engine.
    }
}
