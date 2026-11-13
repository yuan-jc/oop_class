package ripple.common.tcp;

import io.netty.buffer.ByteBuf;
import ripple.common.helper.TypeHelper;

import java.nio.charset.StandardCharsets;
import java.util.zip.DataFormatException;
import java.util.zip.Deflater;
import java.util.zip.Inflater;

/** 仅用于同步、分发请求的value；通信双方必须显式使用相同压缩配置。 */
public final class PayloadCodec {
    private static final int MIN_COMPRESSION_BYTES = 512;
    private static final int MAX_PAYLOAD_BYTES = 1024 * 1024;

    private PayloadCodec() {
    }

    public static void write(String value, ByteBuf buffer) {
        if (!enabled()) {
            TypeHelper.writeString(value, buffer);
            return;
        }
        byte[] plain = value.getBytes(StandardCharsets.UTF_8);
        checkLength(plain.length, true);
        if (plain.length >= MIN_COMPRESSION_BYTES && writeCompressed(plain, buffer)) return;
        buffer.writeInt(plain.length).writeBytes(plain);
    }

    public static String read(ByteBuf buffer) {
        requireBytes(buffer, 4);
        if (!enabled()) {
            if (buffer.getInt(buffer.readerIndex()) < 0) {
                throw new IllegalArgumentException("未启用value压缩，拒绝压缩标记");
            }
            return TypeHelper.readString(buffer);
        }
        int marker = buffer.readInt();
        if (marker >= 0) {
            checkLength(marker, true);
            requireBytes(buffer, marker);
            byte[] plain = new byte[marker];
            buffer.readBytes(plain);
            return new String(plain, StandardCharsets.UTF_8);
        }
        long compressedLength = -(long) marker - 1;
        if (compressedLength <= 0 || compressedLength > MAX_PAYLOAD_BYTES) {
            throw new IllegalArgumentException("非法压缩value长度: " + compressedLength);
        }
        requireBytes(buffer, 4);
        int plainLength = buffer.readInt();
        checkLength(plainLength, false);
        requireBytes(buffer, (int) compressedLength);
        byte[] compressed = new byte[(int) compressedLength];
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
            buffer.writeInt(-(length + 1)).writeInt(plain.length).writeBytes(compressed, 0, length);
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

    private static boolean enabled() {
        return Boolean.getBoolean("ripple.wire.compression");
    }

    private static void checkLength(int length, boolean allowEmpty) {
        if (length < (allowEmpty ? 0 : 1) || length > MAX_PAYLOAD_BYTES) {
            throw new IllegalArgumentException("非法value长度: " + length);
        }
    }

    private static void requireBytes(ByteBuf buffer, int length) {
        if (buffer.readableBytes() < length) {
            throw new IllegalArgumentException("value数据被截断");
        }
    }
}
