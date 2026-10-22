import io.netty.buffer.ByteBuf;
import io.netty.buffer.Unpooled;
import ripple.common.entity.Constants;
import ripple.common.tcp.MessageType;
import ripple.common.tcp.encoder.SyncRequestEncoder;
import ripple.common.tcp.decoder.SyncRequestDecoder;
import ripple.common.tcp.message.SyncRequest;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.UUID;

/** 同一DTO真实编码账本，不把限时未送出的数据当成压缩收益。 */
public final class CodecLedger {
    public static void main(String[] args) throws Exception {
        Method generator = Driver.class.getDeclaredMethod("makePayload", long.class, int.class, long.class, String.class);
        generator.setAccessible(true);
        for (String payload : new String[]{"random", "structured"}) {
            for (int size : new int[]{32, 1024}) {
                long bytes = 0;
                int iterations = 1000;
                long begin = System.nanoTime();
                for (int seq = 0; seq < iterations; seq++) {
                    String original = (String)generator.invoke(null, (long)seq, size, 43L, payload);
                    SyncRequest request = new SyncRequest();
                    request.setUuid(new UUID(1, seq));
                    request.setMessageUuid(new UUID(2, seq));
                    request.setOperationType(Constants.MESSAGE_TYPE_UPDATE);
                    request.setApplicationName("bench_12345678");
                    request.setKey("load");
                    request.setValue(original);
                    request.setLastUpdate(new Date(1000));
                    request.setLastUpdateServerId(1);
                    request.setFromId(1);
                    ByteBuf buffer = Unpooled.buffer();
                    try {
                        new SyncRequestEncoder().encode(request, buffer);
                        bytes += 4+buffer.readableBytes();
                        if (buffer.readByte() != MessageType.SYNC_REQUEST.getValue()) throw new AssertionError("消息类型改变");
                        SyncRequest decoded = (SyncRequest)new SyncRequestDecoder().decode(buffer, MessageType.SYNC_REQUEST);
                        if (!original.equals(decoded.getValue()) || !request.getUuid().equals(decoded.getUuid())
                                || !request.getMessageUuid().equals(decoded.getMessageUuid()) || buffer.isReadable())
                            throw new AssertionError("编解码全文或字段不一致");
                    } finally { buffer.release(); }
                }
                double elapsed = (System.nanoTime()-begin)/1e6;
                System.out.printf(java.util.Locale.ROOT,
                    "{\"payload\":\"%s\",\"size\":%d,\"samples\":%d,\"sync_frame_bytes_mean\":%.6f,\"loop_ms\":%.6f,\"roundtrip_ok\":true}%n",
                    payload,size,iterations,bytes/(double)iterations,elapsed);
            }
        }
    }
}
