package ripple.common.tcp;

import io.netty.buffer.ByteBuf;
import io.netty.buffer.ByteBufUtil;
import io.netty.buffer.Unpooled;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import ripple.common.entity.Constants;
import ripple.common.helper.TypeHelper;
import ripple.common.tcp.decoder.DispatchRequestDecoder;
import ripple.common.tcp.decoder.SyncRequestDecoder;
import ripple.common.tcp.encoder.DispatchRequestEncoder;
import ripple.common.tcp.encoder.SyncRequestEncoder;
import ripple.common.tcp.message.DispatchRequest;
import ripple.common.tcp.message.SyncRequest;

import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.Random;
import java.util.UUID;

import static org.junit.Assert.*;

public class CompressionWireTest {
    private static final String COMPRESSION = "ripple.wire.compression";
    private static final String COMPACT = "ripple.wire.compact";
    private String previousCompression;
    private String previousCompact;

    @Before
    public void saveProperties() {
        previousCompression = System.getProperty(COMPRESSION);
        previousCompact = System.getProperty(COMPACT);
        System.clearProperty(COMPRESSION);
        System.clearProperty(COMPACT);
    }

    @After
    public void restoreProperties() {
        restore(COMPRESSION, previousCompression);
        restore(COMPACT, previousCompact);
    }

    @Test
    public void compressedSyncAndDispatchRoundTripAllValueOperationsAndBothUuidModes() {
        String value = repeat("压缩内容😀", 128);
        for (boolean compact : new boolean[]{false, true}) {
            System.setProperty(COMPACT, Boolean.toString(compact));
            for (boolean dispatch : new boolean[]{false, true}) {
                for (boolean incremental : new boolean[]{false, true}) {
                    Message request = request(dispatch, incremental, value);
                    ByteBuf legacy = encode(request);
                    System.setProperty(COMPRESSION, "true");
                    ByteBuf encoded = encode(request);
                    try {
                        assertTrue(encoded.readableBytes() < legacy.readableBytes());
                        int offset = valueOffset(encoded, dispatch, incremental);
                        assertTrue(encoded.getInt(offset) < 0);
                        // value之前的应用名、key等所有字段保持原编码。
                        assertArrayEquals(ByteBufUtil.getBytes(legacy, 0, offset),
                                ByteBufUtil.getBytes(encoded, 0, offset));
                        assertMessageEquals(request, decode(encoded, dispatch));
                    } finally {
                        legacy.release();
                        encoded.release();
                        System.clearProperty(COMPRESSION);
                    }
                }
            }
        }
    }

    @Test
    public void smallAndHighEntropyValuesKeepExactLegacyBytes() {
        String[] values = {repeat("x", 32), highEntropyValue()};
        for (String value : values) {
            for (boolean dispatch : new boolean[]{false, true}) {
                Message request = request(dispatch, false, value);
                ByteBuf legacy = encode(request);
                System.setProperty(COMPRESSION, "true");
                ByteBuf encoded = encode(request);
                try {
                    assertArrayEquals(ByteBufUtil.getBytes(legacy), ByteBufUtil.getBytes(encoded));
                    assertMessageEquals(request, decode(encoded, dispatch));
                } finally {
                    legacy.release();
                    encoded.release();
                    System.clearProperty(COMPRESSION);
                }
            }
        }
    }

    @Test
    public void disabledCompressionRejectsCompressedValueWithoutGuessing() {
        System.setProperty(COMPRESSION, "true");
        for (boolean dispatch : new boolean[]{false, true}) {
            ByteBuf encoded = encode(request(dispatch, false, repeat("x", 1024)));
            try {
                assertTrue(encoded.getInt(valueOffset(encoded, dispatch, false)) < 0);
                System.setProperty(COMPRESSION, "false");
                assertThrows(IllegalArgumentException.class, () -> decode(encoded, dispatch));
            } finally {
                encoded.release();
                System.setProperty(COMPRESSION, "true");
            }
        }
    }

    private static Message request(boolean dispatch, boolean incremental, String value) {
        SyncRequest sync = new SyncRequest();
        sync.setUuid(new UUID(1, 2));
        sync.setMessageUuid(new UUID(3, 4));
        sync.setOperationType(incremental ? Constants.MESSAGE_TYPE_INCREMENTAL_UPDATE : Constants.MESSAGE_TYPE_UPDATE);
        sync.setApplicationName(repeat("应用", 160));
        sync.setKey(repeat("key", 180));
        sync.setBaseMessageUuid(new UUID(5, 6));
        sync.setAtomicOperation(Constants.ATOMIC_OPERATION_ADD_ENTRY);
        sync.setValue(value);
        sync.setLastUpdate(new Date(12345678));
        sync.setLastUpdateServerId(7);
        sync.setFromId(8);
        if (!dispatch) return sync;
        DispatchRequest result = new DispatchRequest();
        result.setUuid(sync.getUuid());
        result.setClientListSignature("signature");
        result.setMessageUuid(sync.getMessageUuid());
        result.setOperationType(sync.getOperationType());
        result.setApplicationName(sync.getApplicationName());
        result.setKey(sync.getKey());
        result.setBaseMessageUuid(sync.getBaseMessageUuid());
        result.setAtomicOperation(sync.getAtomicOperation());
        result.setValue(sync.getValue());
        result.setLastUpdate(sync.getLastUpdate());
        result.setLastUpdateServerId(sync.getLastUpdateServerId());
        return result;
    }

    private static ByteBuf encode(Message message) {
        ByteBuf result = Unpooled.buffer();
        if (message instanceof DispatchRequest) new DispatchRequestEncoder().encode(message, result);
        else new SyncRequestEncoder().encode(message, result);
        return result;
    }

    private static Message decode(ByteBuf source, boolean dispatch) {
        ByteBuf buffer = source.duplicate();
        MessageType type = MessageType.get(buffer.readByte());
        Message result = dispatch ? new DispatchRequestDecoder().decode(buffer, type)
                : new SyncRequestDecoder().decode(buffer, type);
        assertEquals(0, buffer.readableBytes());
        return result;
    }

    private static int valueOffset(ByteBuf source, boolean dispatch, boolean incremental) {
        ByteBuf buffer = source.duplicate();
        buffer.readByte();
        TypeHelper.readUuid(buffer);
        if (dispatch) TypeHelper.readString(buffer);
        TypeHelper.readUuid(buffer);
        if (!dispatch && TypeHelper.isCompactWire()) buffer.readByte();
        else TypeHelper.readString(buffer);
        TypeHelper.readString(buffer);
        TypeHelper.readString(buffer);
        if (incremental) {
            TypeHelper.readUuid(buffer);
            TypeHelper.readString(buffer);
        }
        return buffer.readerIndex();
    }

    private static void assertMessageEquals(Message expected, Message actual) {
        assertEquals(expected.getUuid(), actual.getUuid());
        if (expected instanceof SyncRequest) {
            SyncRequest a = (SyncRequest) expected;
            SyncRequest b = (SyncRequest) actual;
            assertEquals(a.getMessageUuid(), b.getMessageUuid());
            assertEquals(a.getOperationType(), b.getOperationType());
            assertEquals(a.getApplicationName(), b.getApplicationName());
            assertEquals(a.getKey(), b.getKey());
            assertEquals(a.getValue(), b.getValue());
            assertEquals(a.getLastUpdate(), b.getLastUpdate());
            assertEquals(a.getLastUpdateServerId(), b.getLastUpdateServerId());
            assertEquals(a.getFromId(), b.getFromId());
            if (Constants.MESSAGE_TYPE_INCREMENTAL_UPDATE.equals(a.getOperationType())) {
                assertEquals(a.getBaseMessageUuid(), b.getBaseMessageUuid());
                assertEquals(a.getAtomicOperation(), b.getAtomicOperation());
            }
        } else {
            DispatchRequest a = (DispatchRequest) expected;
            DispatchRequest b = (DispatchRequest) actual;
            assertEquals(a.getClientListSignature(), b.getClientListSignature());
            assertEquals(a.getMessageUuid(), b.getMessageUuid());
            assertEquals(a.getOperationType(), b.getOperationType());
            assertEquals(a.getApplicationName(), b.getApplicationName());
            assertEquals(a.getKey(), b.getKey());
            assertEquals(a.getValue(), b.getValue());
            assertEquals(a.getLastUpdate(), b.getLastUpdate());
            assertEquals(a.getLastUpdateServerId(), b.getLastUpdateServerId());
            if (Constants.MESSAGE_TYPE_INCREMENTAL_UPDATE.equals(a.getOperationType())) {
                assertEquals(a.getBaseMessageUuid(), b.getBaseMessageUuid());
                assertEquals(a.getAtomicOperation(), b.getAtomicOperation());
            }
        }
    }

    private static String repeat(String value, int count) {
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < count; i++) result.append(value);
        return result.toString();
    }

    private static String highEntropyValue() {
        Random random = new Random(2345);
        StringBuilder result = new StringBuilder();
        int length = 0;
        while (length < 512) {
            int choice = random.nextInt(1000);
            int codePoint = choice < 885 ? random.nextInt(128)
                    : choice < 977 ? 128 + random.nextInt(1920)
                    : choice < 997 ? 2048 + random.nextInt(53248)
                    : 65536 + random.nextInt(1048576);
            String next = new String(Character.toChars(codePoint));
            int bytes = next.getBytes(StandardCharsets.UTF_8).length;
            if (length + bytes <= 512) {
                result.append(next);
                length += bytes;
            }
        }
        return result.toString();
    }

    private static void restore(String property, String value) {
        if (value == null) System.clearProperty(property);
        else System.setProperty(property, value);
    }
}
