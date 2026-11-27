package ripple.common.tcp;

import io.netty.buffer.ByteBuf;
import io.netty.buffer.ByteBufUtil;
import io.netty.buffer.Unpooled;
import io.netty.channel.embedded.EmbeddedChannel;
import io.netty.handler.codec.CorruptedFrameException;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import ripple.common.entity.Constants;
import ripple.common.helper.TypeHelper;
import ripple.common.tcp.decoder.SyncRequestDecoder;
import ripple.common.tcp.encoder.SyncRequestEncoder;
import ripple.common.tcp.message.SyncRequest;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

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

    @Test
    public void packedFrameSavesOneByteAndDecodesSplitAndCoalescedFrames() {
        System.setProperty(PROPERTY, "true");
        SyncRequest request = request(Constants.MESSAGE_TYPE_UPDATE);
        MessageEncoder encoder = new MessageEncoder(true);
        encoder.registerEncoder(MessageType.SYNC_REQUEST, new SyncRequestEncoder());
        MessageDecoder decoder = new MessageDecoder(true);
        decoder.registerDecoder(MessageType.SYNC_REQUEST, new SyncRequestDecoder());
        EmbeddedChannel outbound = new EmbeddedChannel(encoder);
        EmbeddedChannel inbound = new EmbeddedChannel(new PackedFrameDecoder(), decoder);
        ByteBuf v1Body = encode(request); // Includes the 1 B type, excludes the 4 B length.
        ByteBuf frame = null;
        try {
            assertTrue(outbound.writeOutbound(request));
            frame = outbound.readOutbound();
            int length = v1Body.readableBytes() - 1;
            assertEquals(4 + length, frame.readableBytes());
            assertEquals((MessageType.SYNC_REQUEST.getValue() << 20) | length, frame.getInt(0));
            assertTrue(ByteBufUtil.equals(v1Body.slice(1, length), frame.slice(4, length)));

            assertFalse(inbound.writeInbound(frame.retainedSlice(0, 2)));
            assertFalse(inbound.writeInbound(frame.retainedSlice(2, 3)));
            ByteBuf combined = Unpooled.buffer();
            combined.writeBytes(frame, 5, frame.readableBytes() - 5);
            combined.writeBytes(frame, 0, frame.readableBytes());
            assertTrue(inbound.writeInbound(combined));
            assertRequestEquals(request, inbound.readInbound());
            assertRequestEquals(request, inbound.readInbound());
            assertNull(inbound.readInbound());
        } finally {
            if (frame != null) frame.release();
            v1Body.release();
            outbound.finishAndReleaseAll();
            inbound.finishAndReleaseAll();
        }
    }

    @Test
    public void packedFrameRejectsOversizeLengthAndReservedBits() {
        for (int header : new int[] { PackedFrame.LENGTH_MASK, 0x04000001 }) {
            EmbeddedChannel inbound = new EmbeddedChannel(new PackedFrameDecoder());
            try {
                assertThrows(CorruptedFrameException.class,
                        () -> inbound.writeInbound(Unpooled.buffer(4).writeInt(header)));
                assertFalse(inbound.isActive());
            } finally {
                inbound.finishAndReleaseAll();
            }
        }
    }

    @Test
    public void measureFrameCompressionAcrossPayloadLengths() throws Exception {
        byte[] corpus = readLittlePrince();
        System.setProperty(PROPERTY, "true");
        String property = "ripple.wire.frameCompression";
        String previousCompression = System.getProperty(property);
        System.clearProperty(property);
        EmbeddedChannel baseline = syncChannel();
        System.setProperty(property, "true");
        EmbeddedChannel optimized = syncChannel();
        try {
            for (int size : new int[] {1024, 10 * 1024, 100 * 1024}) {
                List<SyncRequest> requests = new ArrayList<>();
                for (int start = 0; start < corpus.length;) {
                    int end = Math.min(start + size, corpus.length);
                    while (end < corpus.length && (corpus[end] & 0xc0) == 0x80) end--;
                    SyncRequest request = request(Constants.MESSAGE_TYPE_UPDATE);
                    request.setValue(StandardCharsets.UTF_8.newDecoder()
                            .decode(ByteBuffer.wrap(corpus, start, end - start)).toString());
                    requests.add(request);
                    start = end;
                }
                int before = roundTrip(baseline, requests, corpus);
                int after = roundTrip(optimized, requests, corpus);
                assertTrue(after < before);
                byte[] plainFrames = encodeFrames(baseline, requests, before);
                byte[] optimizedFrames = encodeFrames(optimized, requests, after);
                long[] median = measureTcpTransfer(plainFrames, optimizedFrames);
                System.out.printf("WIRE_RESULT,little_prince,%d,%d,%d,%d,%d,%d,%d,%d%n",
                        corpus.length, size, requests.size(), before, after, before - after,
                        median[0], median[1]);
            }
        } finally {
            baseline.finishAndReleaseAll();
            optimized.finishAndReleaseAll();
            if (previousCompression == null) System.clearProperty(property);
            else System.setProperty(property, previousCompression);
        }
    }

    private static final int WARMUP_ROUNDS = 20;
    private static final int MEASURED_ROUNDS = 31;

    private static byte[] encodeFrames(EmbeddedChannel channel, List<SyncRequest> requests, int size) {
        byte[] frames = new byte[size];
        int offset = 0;
        for (SyncRequest request : requests) {
            assertTrue(channel.writeOutbound(request));
            ByteBuf frame = channel.readOutbound();
            try {
                int length = frame.readableBytes();
                frame.readBytes(frames, offset, length);
                offset += length;
            } finally {
                frame.release();
            }
        }
        assertEquals(size, offset);
        return frames;
    }

    private static long[] measureTcpTransfer(byte[] plain, byte[] optimized) throws Exception {
        InetAddress loopback = InetAddress.getLoopbackAddress();
        try (ServerSocket listener = new ServerSocket(0, 1, loopback);
             Socket sender = new Socket(loopback, listener.getLocalPort());
             Socket receiver = listener.accept()) {
            sender.setSoTimeout(5000);
            receiver.setSoTimeout(5000);
            sender.setTcpNoDelay(true);
            receiver.setTcpNoDelay(true);
            InputStream incoming = receiver.getInputStream();
            OutputStream confirm = receiver.getOutputStream();
            FutureTask<Void> receive = new FutureTask<>(() -> {
                byte[] buffer = new byte[8192];
                for (int round = -WARMUP_ROUNDS; round < MEASURED_ROUNDS; round++) {
                    boolean plainFirst = round % 2 == 0;
                    receiveTransfer(incoming, confirm, buffer, (plainFirst ? plain : optimized).length);
                    receiveTransfer(incoming, confirm, buffer, (plainFirst ? optimized : plain).length);
                }
                return null;
            });
            Thread reader = new Thread(receive, "ripple-tcp-transfer-test");
            reader.setDaemon(true);
            reader.start();
            OutputStream outgoing = sender.getOutputStream();
            InputStream confirmation = sender.getInputStream();
            long[] plainNanos = new long[MEASURED_ROUNDS];
            long[] optimizedNanos = new long[MEASURED_ROUNDS];
            for (int round = -WARMUP_ROUNDS; round < MEASURED_ROUNDS; round++) {
                boolean plainFirst = round % 2 == 0;
                long first = sendTransfer(outgoing, confirmation, plainFirst ? plain : optimized);
                long second = sendTransfer(outgoing, confirmation, plainFirst ? optimized : plain);
                if (round >= 0) {
                    plainNanos[round] = plainFirst ? first : second;
                    optimizedNanos[round] = plainFirst ? second : first;
                }
            }
            receive.get(5, TimeUnit.SECONDS);
            Arrays.sort(plainNanos);
            Arrays.sort(optimizedNanos);
            return new long[] {plainNanos[MEASURED_ROUNDS / 2], optimizedNanos[MEASURED_ROUNDS / 2]};
        }
    }

    private static void receiveTransfer(InputStream in, OutputStream confirm, byte[] buffer, int remaining)
            throws IOException {
        while (remaining > 0) {
            int count = in.read(buffer, 0, Math.min(buffer.length, remaining));
            if (count < 0) throw new IOException("TCP stream closed before all frame bytes arrived");
            remaining -= count;
        }
        confirm.write(1);
    }

    private static long sendTransfer(OutputStream out, InputStream confirm, byte[] frames) throws IOException {
        long start = System.nanoTime();
        out.write(frames);
        int ack = confirm.read();
        long elapsed = System.nanoTime() - start;
        assertEquals(1, ack);
        return elapsed;
    }

    private static int roundTrip(EmbeddedChannel channel, List<SyncRequest> requests, byte[] expected) {
        ByteArrayOutputStream reconstructed = expected == null ? null : new ByteArrayOutputStream();
        int totalBytes = 0;
        for (SyncRequest request : requests) {
            channel.writeOutbound(request);
            ByteBuf frame = channel.readOutbound();
            totalBytes += frame.readableBytes();
            channel.writeInbound(frame);
            SyncRequest decoded = channel.readInbound();
            if (reconstructed != null) {
                assertRequestEquals(request, decoded);
                byte[] bytes = decoded.getValue().getBytes(StandardCharsets.UTF_8);
                reconstructed.write(bytes, 0, bytes.length);
            }
        }
        if (reconstructed != null) assertArrayEquals(expected, reconstructed.toByteArray());
        return totalBytes;
    }

    private static byte[] readLittlePrince() throws IOException {
        try (InputStream input = CompactWireTest.class.getResourceAsStream("/little-prince-en.txt")) {
            assertNotNull("Missing Little Prince test fixture", input);
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            for (int count; (count = input.read(chunk)) != -1;) {
                bytes.write(chunk, 0, count);
            }
            return bytes.toByteArray();
        }
    }

    @Test
    public void compressedUtf8RoundTripsAndRejectsLengthMismatchOrTrailingInput() {
        String text = String.join("", java.util.Collections.nCopies(256, "\u6e29\u5ea6=23;"));
        ByteBuf encoded = Unpooled.buffer();
        try {
            assertTrue(PayloadCodec.write(text, encoded, true));
            int compressedLength = encoded.getInt(0);
            int plainLength = encoded.getInt(4);
            assertEquals(text.getBytes(StandardCharsets.UTF_8).length, plainLength);
            assertEquals(text, PayloadCodec.readCompressed(encoded.duplicate()));
            encoded.setInt(4, plainLength + 1);
            assertThrows(IllegalArgumentException.class, () -> PayloadCodec.readCompressed(encoded.duplicate()));
            encoded.setInt(4, plainLength);
            encoded.setInt(0, compressedLength + 1);
            encoded.writeByte(0);
            assertThrows(IllegalArgumentException.class, () -> PayloadCodec.readCompressed(encoded.duplicate()));
        } finally {
            encoded.release();
        }
    }

    @Test
    public void deleteAndIncrementalUpdateCannotBeDecodedAsCompressed() {
        for (String operation : new String[] {Constants.MESSAGE_TYPE_DELETE, Constants.MESSAGE_TYPE_INCREMENTAL_UPDATE}) {
            SyncRequest request = request(operation);
            ByteBuf body = Unpooled.buffer();
            try {
                assertFalse(new SyncRequestEncoder().encodePacked(request, body, true));
                body.readByte();
                assertThrows(IllegalArgumentException.class, () ->
                        new SyncRequestDecoder().decodePacked(body, MessageType.SYNC_REQUEST, true));
            } finally {
                body.release();
            }
        }
    }

    private static EmbeddedChannel syncChannel() {
        MessageEncoder encoder = new MessageEncoder(true);
        encoder.registerEncoder(MessageType.SYNC_REQUEST, new SyncRequestEncoder());
        MessageDecoder decoder = new MessageDecoder(true);
        decoder.registerDecoder(MessageType.SYNC_REQUEST, new SyncRequestDecoder());
        return new EmbeddedChannel(new PackedFrameDecoder(), encoder, decoder);
    }

    @Test
    public void compressedValueRejectsTruncationAndInvalidLengths() {
        ByteBuf buffer = Unpooled.buffer();
        try {
            buffer.writeInt(2).writeInt(512).writeByte(0);
            assertThrows(IllegalArgumentException.class, () -> PayloadCodec.readCompressed(buffer));
            buffer.clear().writeInt(1).writeInt(PackedFrame.MAX_FRAME_BYTES + 1).writeByte(0);
            assertThrows(IllegalArgumentException.class, () -> PayloadCodec.readCompressed(buffer));
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
