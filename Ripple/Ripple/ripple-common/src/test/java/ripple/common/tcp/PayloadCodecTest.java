package ripple.common.tcp;

import io.netty.buffer.ByteBuf;
import io.netty.buffer.ByteBufUtil;
import io.netty.buffer.Unpooled;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import ripple.common.helper.TypeHelper;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.zip.Deflater;

import static org.junit.Assert.*;

public class PayloadCodecTest {
    private static final String PROPERTY = "ripple.wire.compression";
    private static final int LIMIT = 1024 * 1024;
    private String previous;

    @Before
    public void enableCompression() {
        previous = System.getProperty(PROPERTY);
        System.setProperty(PROPERTY, "true");
    }

    @After
    public void restoreProperty() {
        if (previous == null) System.clearProperty(PROPERTY);
        else System.setProperty(PROPERTY, previous);
    }

    @Test
    public void payloadBelowThresholdAndDisabledCompressionKeepLegacyBytes() {
        for (String value : new String[]{"", repeated(32), repeated(511), "中文😀"}) {
            assertLegacy(value);
        }
        System.clearProperty(PROPERTY);
        assertLegacy(repeated(1024));
        System.setProperty(PROPERTY, "false");
        assertLegacy(repeated(1024));
    }

    @Test
    public void thresholdAndOneMiBLimitRoundTrip() {
        for (int length : new int[]{512, 1024, LIMIT}) {
            ByteBuf buffer = Unpooled.buffer();
            try {
                String value = repeated(length);
                PayloadCodec.write(value, buffer);
                assertTrue(buffer.getInt(0) < 0);
                assertTrue(buffer.readableBytes() < length + 4);
                assertEquals(value, PayloadCodec.read(buffer));
                assertEquals(0, buffer.readableBytes());
            } finally {
                buffer.release();
            }
        }
    }

    @Test
    public void oversizedEncoderValueIsRejectedBeforeWriting() {
        ByteBuf buffer = Unpooled.buffer();
        try {
            assertThrows(IllegalArgumentException.class, () -> PayloadCodec.write(repeated(LIMIT + 1), buffer));
            assertEquals(0, buffer.readableBytes());
        } finally {
            buffer.release();
        }
    }

    @Test
    public void malformedHeadersAndTruncatedBodiesAreRejected() {
        reject(Unpooled.buffer().writeByte(0));
        reject(Unpooled.buffer().writeInt(-1));
        reject(Unpooled.buffer().writeInt(Integer.MIN_VALUE));
        reject(Unpooled.buffer().writeInt(-(LIMIT + 2)));
        reject(Unpooled.buffer().writeInt(-5));
        reject(Unpooled.buffer().writeInt(-5).writeShort(2));
        for (int length : new int[]{-1, 0, LIMIT + 1, Integer.MAX_VALUE}) {
            reject(Unpooled.buffer().writeInt(-5).writeInt(length).writeInt(0));
        }
        reject(Unpooled.buffer().writeInt(-5).writeInt(512).writeByte(0));
        reject(Unpooled.buffer().writeInt(LIMIT + 1));
        reject(Unpooled.buffer().writeInt(32).writeByte(1));
        reject(Unpooled.buffer().writeInt(-5).writeInt(512).writeInt(-1));
    }

    @Test
    public void incompleteStreamsTrailingInputAndLengthMismatchAreRejected() {
        byte[] compressed = deflate(repeated(1024));
        reject(frame(Arrays.copyOf(compressed, compressed.length - 1), 1024));
        reject(frame(Arrays.copyOf(compressed, compressed.length + 1), 1024));
        reject(frame(compressed, 1023));
        reject(frame(compressed, 1025));
        // 压缩正文很小，但真实输出超出允许值，不能只相信头部声明。
        reject(frame(deflate(repeated(LIMIT + 1)), LIMIT));
    }

    @Test
    public void disabledCompressionExplicitlyRejectsNegativeHeaders() {
        System.clearProperty(PROPERTY);
        reject(Unpooled.buffer().writeInt(-1));
        reject(frame(deflate(repeated(1024)), 1024));
    }

    private static void assertLegacy(String value) {
        ByteBuf expected = Unpooled.buffer();
        ByteBuf actual = Unpooled.buffer();
        try {
            TypeHelper.writeString(value, expected);
            PayloadCodec.write(value, actual);
            assertArrayEquals(ByteBufUtil.getBytes(expected), ByteBufUtil.getBytes(actual));
            assertEquals(value, PayloadCodec.read(actual));
            assertEquals(0, actual.readableBytes());
        } finally {
            expected.release();
            actual.release();
        }
    }

    private static void reject(ByteBuf buffer) {
        try {
            assertThrows(IllegalArgumentException.class, () -> PayloadCodec.read(buffer));
        } finally {
            buffer.release();
        }
    }

    private static ByteBuf frame(byte[] compressed, int plainLength) {
        return Unpooled.buffer().writeInt(-(compressed.length + 1)).writeInt(plainLength).writeBytes(compressed);
    }

    private static byte[] deflate(String value) {
        byte[] input = value.getBytes(StandardCharsets.UTF_8);
        byte[] output = new byte[input.length + 1024];
        Deflater deflater = new Deflater(Deflater.BEST_SPEED, true);
        try {
            deflater.setInput(input);
            deflater.finish();
            int length = deflater.deflate(output);
            assertTrue(deflater.finished());
            return Arrays.copyOf(output, length);
        } finally {
            deflater.end();
        }
    }

    private static String repeated(int length) {
        char[] chars = new char[length];
        Arrays.fill(chars, 'x');
        return new String(chars);
    }
}
