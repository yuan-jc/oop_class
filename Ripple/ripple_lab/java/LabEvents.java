import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/** 有界队列让网络线程只入队；写盘失败让运行明确失败。 */
public final class LabEvents implements AutoCloseable {
    private final ArrayBlockingQueue<Map<String,Object>> queue = new ArrayBlockingQueue<>(16384);
    private final AtomicLong dropped = new AtomicLong();
    private final String node;
    private final Thread writer;
    private volatile boolean closing;
    private volatile Throwable failure;
    public LabEvents(Path path, String node) throws Exception {
        this.node = node;
        Files.createDirectories(path.getParent());
        BufferedWriter output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        writer = new Thread(() -> {
            ObjectMapper mapper = new ObjectMapper();
            try (BufferedWriter out = output) {
                long lastFlush = System.nanoTime();
                while (!closing || !queue.isEmpty()) {
                    Map<String,Object> event = queue.poll(100, TimeUnit.MILLISECONDS);
                    long count = dropped.getAndSet(0);
                    if (count > 0) {
                        Map<String,Object> gap = base("observation_gap");
                        gap.put("dropped",count);
                        gap.put("note", "事件队列溢出，丢弃 " + count + " 条");
                        out.write(mapper.writeValueAsString(gap)); out.newLine();
                    }
                    if (event != null) { out.write(mapper.writeValueAsString(event)); out.newLine(); }
                    if (event == null || queue.isEmpty() || System.nanoTime()-lastFlush >= 100000000L) {
                        out.flush(); lastFlush = System.nanoTime();
                    }
                }
            } catch (Throwable e) { failure = e; e.printStackTrace(); }
        }, "实验事件写盘");
        writer.start();
    }
    public Map<String,Object> base(String event) {
        Map<String,Object> data = new LinkedHashMap<>();
        data.put("time", System.currentTimeMillis() / 1000.0);
        data.put("node", node); data.put("event", event);
        for (String key : new String[]{"type","publisher","seq","request_uuid","message_uuid","peer","bytes","ok","preview","note"}) data.put(key, null);
        return data;
    }
    public void emit(Map<String,Object> event) { if (!queue.offer(event)) dropped.incrementAndGet(); }
    public void simple(String event, String note) {
        Map<String,Object> data = base(event); data.put("note",note); emit(data);
    }
    public void check() { if (failure != null) throw new IllegalStateException("事件写盘失败", failure); }
    public void close() throws Exception { closing = true; writer.join(); check(); }
}
