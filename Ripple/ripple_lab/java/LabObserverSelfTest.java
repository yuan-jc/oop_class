import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.netty.channel.embedded.EmbeddedChannel;
import ripple.common.tcp.*;
import ripple.common.tcp.message.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

/** 实际运行包装后的处理链，验证完整内容损坏事件且不改变原处理结果。 */
public final class LabObserverSelfTest {
    public static void run() throws Exception {
        Path directory = Files.createTempDirectory("ripple-content-self-test-");
        Path path = directory.resolve("events.jsonl");
        AtomicInteger calls = new AtomicInteger();
        LabEvents events = new LabEvents(path,"c1");
        MessageHandler original = new MessageHandler();
        original.registerHandler(MessageType.SYNC_REQUEST,(context,message) -> {
            calls.incrementAndGet();
            SyncResponse response = new SyncResponse();
            response.setUuid(message.getUuid()); response.setResult(Result.SUCCESS); return response;
        });
        EmbeddedChannel channel = new EmbeddedChannel(original);
        try {
            Map<String,LabContent> specifications = Collections.singletonMap("p1",new LabContent(1024,42));
            new LabObserver(events,true,Collections.emptyMap(),specifications).attach(channel);
            channel.runPendingTasks();
            String valid = LabPayload.create("p1",0,1024,42);
            String corrupt = valid.substring(0,1023) + (valid.charAt(1023) == 'a' ? 'b' : 'a');
            for (String value : new String[]{valid,corrupt}) {
                SyncRequest request = new SyncRequest(); request.setUuid(UUID.randomUUID());
                request.setKey("load-p1"); request.setValue(value);
                channel.writeInbound(request); channel.runPendingTasks();
                SyncResponse response = channel.readOutbound();
                require(response != null && response.getResult() == Result.SUCCESS,"保留原处理器成功返回");
            }
            require(calls.get() == 2,"原处理器调用次数不变");
        } finally { channel.close(); events.close(); }
        int good = 0, corrupt = 0, errors = 0;
        ObjectMapper mapper = new ObjectMapper();
        for (String line : Files.readAllLines(path,StandardCharsets.UTF_8)) {
            JsonNode event = mapper.readTree(line);
            if (event.path("event").asText().equals("delivery")) {
                require(event.path("bytes").asInt() == 1024,"记录完整实际字节数");
                require(event.path("payload_sha256").asText().length() == 64,"记录完整摘要");
                if (event.path("content_ok").asBoolean()) good++; else corrupt++;
            }
            if (event.path("event").asText().equals("error") && !event.path("content_ok").asBoolean(true)) errors++;
        }
        require(good == 1 && corrupt == 1 && errors == 1,"正文单字节损坏产生失败送达与错误事件");
        Files.delete(path); Files.delete(directory);
    }
    private static void require(boolean condition,String note) { if (!condition) throw new AssertionError(note); }
}
