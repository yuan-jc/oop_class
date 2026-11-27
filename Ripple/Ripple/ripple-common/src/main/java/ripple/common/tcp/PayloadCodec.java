package ripple.common.tcp;

import io.netty.buffer.ByteBuf;
import ripple.common.helper.TypeHelper;

import java.nio.charset.StandardCharsets;
import java.util.zip.DataFormatException;
import java.util.zip.Deflater;
import java.util.zip.Inflater;

/** Raw Deflate for a value marked by the packed frame header. */
public final class PayloadCodec {
    private static final int MIN_COMPRESSION_BYTES = 512;
    private static final int MAX_PAYLOAD_BYTES = 1024 * 1024;

    private PayloadCodec() {
    }

    /** Write a value and report whether this frame needs its compressed bit set. */
    public static boolean write(String value, ByteBuf buffer, boolean allowCompression) {
        if (!allowCompression) {
            TypeHelper.writeString(value, buffer);
            return false;
        }
        byte[] plain = value.getBytes(StandardCharsets.UTF_8);
        if (plain.length >= MIN_COMPRESSION_BYTES && plain.length <= MAX_PAYLOAD_BYTES
                && writeCompressed(plain, buffer)) {
            return true;
        }
        buffer.writeInt(plain.length).writeBytes(plain);
        return false;
    }

    public static String readCompressed(ByteBuf buffer) {
        requireBytes(buffer, 8);
        int compressedLength = buffer.readInt();
        int plainLength = buffer.readInt();
        checkLength(compressedLength);
        checkLength(plainLength);
        requireBytes(buffer, compressedLength);
        byte[] compressed = new byte[compressedLength];
        buffer.readBytes(compressed);
        return inflate(compressed, plainLength);
    }

    private static boolean writeCompressed(byte[] plain, ByteBuf buffer) {
        Deflater deflater = new Deflater(Deflater.BEST_SPEED, true);
        try {
            deflater.setInput(plain);
            deflater.finish();
            // 额外的原文长度占4B；只有完整压缩编码严格更小时才使用压缩。
            byte[] compressed = new byte[plain.length - 5];
            int length = 0;
            while (!deflater.finished() && length < compressed.length) {
                int count = deflater.deflate(compressed, length, compressed.length - length);
                if (count == 0) break;
                length += count;
            }
            if (!deflater.finished()) return false;
            buffer.writeInt(length).writeInt(plain.length).writeBytes(compressed, 0, length);
            return true;
        } finally {
            deflater.end();
        }
    }

    private static String inflate(byte[] compressed, int plainLength) {
        Inflater inflater = new Inflater(true);
        try {
            inflater.setInput(compressed);
            // 多留1B检测超出声明长度的输出，分配上限仍由1MiB限制约束。
            byte[] plain = new byte[plainLength + 1];
            int length = 0;
            while (!inflater.finished() && length <= plainLength) {
                int count = inflater.inflate(plain, length, plain.length - length);
                length += count;
                if (count == 0 && !inflater.finished()) {
                    throw new IllegalArgumentException("压缩value不完整或无法继续解压");
                }
            }
            if (!inflater.finished() || length != plainLength || inflater.getRemaining() != 0) {
                throw new IllegalArgumentException("压缩value长度不匹配或存在剩余输入");
            }
            return new String(plain, 0, length, StandardCharsets.UTF_8);
        } catch (DataFormatException error) {
            throw new IllegalArgumentException("压缩value格式错误", error);
        } finally {
            inflater.end();
        }
    }

    private static void checkLength(int length) {
        if (length <= 0 || length > MAX_PAYLOAD_BYTES) {
            throw new IllegalArgumentException("Invalid compressed value length: " + length);
        }
    }

    private static void requireBytes(ByteBuf buffer, int length) {
        if (buffer.readableBytes() < length) {
            throw new IllegalArgumentException("value数据被截断");
        }
    }
}
