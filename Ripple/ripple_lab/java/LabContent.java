import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** 对完整原字符串重新生成期望值并比较，摘要覆盖实际 UTF-8 内容。 */
public final class LabContent {
    public final int size;
    public final long seed;
    public LabContent(int size, long seed) { this.size = size; this.seed = seed; }
    public static boolean matches(String value, String publisher, long seq, int size, long seed) {
        return value != null && value.equals(LabPayload.create(publisher,seq,size,seed));
    }
    public static int bytes(String value) { return value.getBytes(StandardCharsets.UTF_8).length; }
    public static String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            char[] hex = "0123456789abcdef".toCharArray();
            StringBuilder output = new StringBuilder(64);
            for (byte b : digest) output.append(hex[(b & 255) >>> 4]).append(hex[b & 15]);
            return output.toString();
        } catch (NoSuchAlgorithmException e) { throw new IllegalStateException("运行环境缺少 SHA-256",e); }
    }
}
