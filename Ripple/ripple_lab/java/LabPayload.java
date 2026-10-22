import java.util.Locale;
import java.util.Random;

/** 只用 ASCII，字符串长度与 UTF-8 字节数相等。 */
public final class LabPayload {
    public final String publisher;
    public final long seq;
    private LabPayload(String publisher, long seq) { this.publisher = publisher; this.seq = seq; }
    public static String create(String publisher, long seq, int size, long seed) {
        String head = "RL1:" + publisher + ":" + String.format(Locale.ROOT, "%012d", seq) + ":";
        if (size < head.length()) throw new IllegalArgumentException("载荷小于标识头");
        StringBuilder out = new StringBuilder(size).append(head);
        Random random = new Random(seed ^ (seq * 0x9E3779B97F4A7C15L) ^ publisher.hashCode());
        while (out.length() < size) out.append((char) ('!' + random.nextInt(94)));
        return out.toString();
    }
    public static LabPayload parse(String value) {
        if (value == null || !value.startsWith("RL1:")) return null;
        try {
            String[] parts = value.split(":", 4);
            return new LabPayload(parts[1], Long.parseLong(parts[2]));
        } catch (RuntimeException ignored) { return null; }
    }
}
