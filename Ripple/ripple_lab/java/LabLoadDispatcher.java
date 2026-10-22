import java.util.concurrent.*;
import java.util.function.*;

/** 单个无队列业务线程隔离原库同步阻塞；结束调度不取消已经进入的原库调用。 */
public final class LabLoadDispatcher {
    private final ThreadPoolExecutor executor;
    private final LongSupplier clock;
    private final BooleanSupplier halted;
    private final LongConsumer operation;
    private final long deadline;
    private boolean accepting = true;
    private boolean inFlight;
    private long submitted;
    private long blockedSlots;
    public LabLoadDispatcher(long deadline, LongSupplier clock, BooleanSupplier halted, LongConsumer operation) {
        this.deadline = deadline; this.clock = clock; this.halted = halted; this.operation = operation;
        executor = new ThreadPoolExecutor(1,1,0,TimeUnit.MILLISECONDS,new SynchronousQueue<>(), task -> {
            Thread thread = new Thread(task,"实验业务提交"); thread.setDaemon(true); return thread;
        });
    }
    public void offer() {
        try {
            executor.execute(() -> {
                final long seq;
                synchronized (this) {
                    if (!accepting || halted.getAsBoolean() || clock.getAsLong()-deadline >= 0) return;
                    seq = submitted++; inFlight = true;
                }
                try { operation.accept(seq); }
                finally { synchronized (this) { inFlight = false; notifyAll(); } }
            });
        } catch (RejectedExecutionException busy) { synchronized (this) { blockedSlots++; } }
    }
    public synchronized void finish() { accepting = false; executor.shutdown(); }
    public synchronized long submitted() { return submitted; }
    public synchronized long blockedSlots() { return blockedSlots; }
    public synchronized boolean inFlight() { return inFlight; }
    public boolean await(long millis) throws InterruptedException { return executor.awaitTermination(millis,TimeUnit.MILLISECONDS); }
}
