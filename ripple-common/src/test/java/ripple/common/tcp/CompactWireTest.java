package ripple.common.tcp;

import io.netty.buffer.ByteBuf;
import io.netty.buffer.ByteBufUtil;
import io.netty.buffer.Unpooled;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import ripple.common.entity.Constants;
import ripple.common.helper.TypeHelper;
import ripple.common.tcp.decoder.SyncRequestDecoder;
import ripple.common.tcp.encoder.SyncRequestEncoder;
import ripple.common.tcp.message.SyncRequest;

import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.UUID;

import static org.junit.Assert.*;

public class CompactWireTest {
    private static final String PROPERTY = "ripple.wire.compact";
    private static final UUID UUID_VALUE = UUID.fromString("01234567-89ab-cdef-fedc-ba9876543210");
    private String previous;

    @Before
    public void saveProperty() {
        previous = System.getProperty(PROPERTY);
        System.clearProperty(PROPERTY);
    }

    @After
    public void restoreProperty() {
        if (previous == null) {
            System.clearProperty(PROPERTY);
        } else {
            System.setProperty(PROPERTY, previous);
        }
    }

    @Test
    public void legacyUuidKeepsExactBytes() {
        ByteBuf buffer = Unpooled.buffer();
        ByteBuf expected = Unpooled.buffer();
        try {
            TypeHelper.writeUuid(UUID_VALUE, buffer);
            expected.writeInt(36).writeBytes(UUID_VALUE.toString().getBytes(StandardCharsets.UTF_8));
            assertEquals(40, buffer.readableBytes());
            assertArrayEquals(ByteBufUtil.getBytes(expected), ByteBufUtil.getBytes(buffer));
            assertEquals(UUID_VALUE, TypeHelper.readUuid(buffer));
            assertEquals(0, buffer.readableBytes());
        } finally {
            buffer.release();
            expected.release();
        }
    }

    @Test
    public void disabledPropertyKeepsLegacyUuidBytes() {
        System.setProperty(PROPERTY, "false");
        legacyUuidKeepsExactBytes();
    }

    @Test
    public void compactUuidUsesTwoLongsAndRoundTrips() {
        System.setProperty(PROPERTY, "true");
        for (UUID value : new UUID[]{UUID_VALUE, new UUID(0, 0), new UUID(-1, -1)}) {
            ByteBuf buffer = Unpooled.buffer();
            try {
                TypeHelper.writeUuid(value, buffer);
                assertEquals(16, buffer.readableBytes());
                assertEquals(value.getMostSignificantBits(), buffer.getLong(0));
                assertEquals(value.getLeastSignificantBits(), buffer.getLong(8));
                assertEquals(value, TypeHelper.readUuid(buffer));
                assertEquals(0, buffer.readableBytes());
            } finally {
                buffer.release();
            }
        }
    }

    @Test
    public void syncRequestPreservesLegacyBytesAndCompactRoundTripsAllOperations() {
        String[] operations = {Constants.MESSAGE_TYPE_UPDATE, Constants.MESSAGE_TYPE_DELETE,
                Constants.MESSAGE_TYPE_INCREMENTAL_UPDATE};
        for (int i = 0; i < operations.length; i++) {
            SyncRequest request = request(operations[i]);
            System.clearProperty(PROPERTY);
            ByteBuf legacy = encode(request);
            ByteBuf expected = legacyBytes(request);
            ByteBuf compact = null;
            try {
                assertArrayEquals(ByteBufUtil.getBytes(expected), ByteBufUtil.getBytes(legacy));
                assertRequestEquals(request, decode(legacy.copy()));
                System.setProperty(PROPERTY, "true");
                compact = encode(request);
                assertEquals(i + 1, compact.getUnsignedByte(33));
                assertEquals(i == 2 ? 93 : 57, legacy.readableBytes() - compact.readableBytes());
                assertRequestEquals(request, decode(compact.copy()));
            } finally {
                legacy.release();
                expected.release();
                if (compact != null) compact.release();
            }
        }
    }

    @Test
    public void compactEncoderRejectsUnknownOperation() {
        System.setProperty(PROPERTY, "true");
        ByteBuf buffer = Unpooled.buffer();
        try {
            IllegalArgumentException error = assertThrows(IllegalArgumentException.class,
                    () -> new SyncRequestEncoder().encode(request("invalid"), buffer));
            assertTrue(error.getMessage().contains("invalid"));
        } finally {
            buffer.release();
        }
    }

    @Test
    public void compactDecoderRejectsUnknownOperationCode() {
        System.setProperty(PROPERTY, "true");
        ByteBuf buffer = encode(request(Constants.MESSAGE_TYPE_UPDATE));
        try {
            buffer.setByte(33, 255);
            assertEquals(MessageType.SYNC_REQUEST.getValue(), buffer.readByte());
            IllegalArgumentException error = assertThrows(IllegalArgumentException.class,
                    () -> new SyncRequestDecoder().decode(buffer, MessageType.SYNC_REQUEST));
            assertTrue(error.getMessage().contains("255"));
        } finally {
            buffer.release();
        }
    }

    private static SyncRequest request(String operation) {
        SyncRequest request = new SyncRequest();
        request.setUuid(UUID_VALUE);
        request.setMessageUuid(new UUID(-123, 456));
        request.setOperationType(operation);
        request.setApplicationName("应用");
        request.setKey("key");
        request.setBaseMessageUuid(new UUID(789, -123));
        request.setAtomicOperation(Constants.ATOMIC_OPERATION_ADD_ENTRY);
        request.setValue("内容");
        request.setLastUpdate(new Date(1720000000123L));
        request.setLastUpdateServerId(2);
        request.setFromId(3);
        return request;
    }

    private static ByteBuf encode(SyncRequest request) {
        ByteBuf buffer = Unpooled.buffer();
        new SyncRequestEncoder().encode(request, buffer);
        return buffer;
    }

    private static SyncRequest decode(ByteBuf buffer) {
        try {
            assertEquals(MessageType.SYNC_REQUEST.getValue(), buffer.readByte());
            SyncRequest result = (SyncRequest) new SyncRequestDecoder().decode(buffer, MessageType.SYNC_REQUEST);
            assertEquals(0, buffer.readableBytes());
            return result;
        } finally {
            buffer.release();
        }
    }

    private static void assertRequestEquals(SyncRequest expected, SyncRequest actual) {
        assertEquals(expected.getUuid(), actual.getUuid());
        assertEquals(expected.getMessageUuid(), actual.getMessageUuid());
        assertEquals(expected.getOperationType(), actual.getOperationType());
        assertEquals(expected.getApplicationName(), actual.getApplicationName());
        assertEquals(expected.getKey(), actual.getKey());
        if (!Constants.MESSAGE_TYPE_DELETE.equals(expected.getOperationType())) {
            assertEquals(expected.getValue(), actual.getValue());
        }
        if (Constants.MESSAGE_TYPE_INCREMENTAL_UPDATE.equals(expected.getOperationType())) {
            assertEquals(expected.getBaseMessageUuid(), actual.getBaseMessageUuid());
            assertEquals(expected.getAtomicOperation(), actual.getAtomicOperation());
        }
        assertEquals(expected.getLastUpdate(), actual.getLastUpdate());
        assertEquals(expected.getLastUpdateServerId(), actual.getLastUpdateServerId());
        assertEquals(expected.getFromId(), actual.getFromId());
    }

    private static ByteBuf legacyBytes(SyncRequest request) {
        ByteBuf buffer = Unpooled.buffer();
        buffer.writeByte(request.getType().getValue());
        legacyString(request.getUuid().toString(), buffer);
        legacyString(request.getMessageUuid().toString(), buffer);
        legacyString(request.getOperationType(), buffer);
        legacyString(request.getApplicationName(), buffer);
        legacyString(request.getKey(), buffer);
        if (Constants.MESSAGE_TYPE_UPDATE.equals(request.getOperationType())) {
            legacyString(request.getValue(), buffer);
        } else if (Constants.MESSAGE_TYPE_INCREMENTAL_UPDATE.equals(request.getOperationType())) {
            legacyString(request.getBaseMessageUuid().toString(), buffer);
            legacyString(request.getAtomicOperation(), buffer);
            legacyString(request.getValue(), buffer);
        }
        return buffer.writeLong(request.getLastUpdate().getTime())
                .writeInt(request.getLastUpdateServerId()).writeInt(request.getFromId());
    }

    private static void legacyString(String value, ByteBuf buffer) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        buffer.writeInt(bytes.length).writeBytes(bytes);
    }
}
