import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.Deflater;
import ripple.common.tcp.Message;
import ripple.common.tcp.message.Result;
import ripple.common.tcp.message.SyncResponse;
import ripple.common.tcp.message.PutResponse;

/** 独立运行载荷校验，避免启动真实集群。 */
public class DriverPayloadCheck {
    public static void main(String[] args) throws Exception {
        Method accepted = Driver.class.getDeclaredMethod("acceptedSync", Message.class);
        accepted.setAccessible(true);
        SyncResponse response = new SyncResponse();
        if ((Boolean) accepted.invoke(null, response))
            throw new AssertionError("未设置结果的同步响应不得计收件");
        for (Result result : Result.values()) {
            response.setResult(result);
            if (!(Boolean) accepted.invoke(null, response))
                throw new AssertionError("成功或重复结果应计收件");
        }
        if ((Boolean) accepted.invoke(null, new PutResponse())
                || (Boolean) accepted.invoke(null, (Object) null))
            throw new AssertionError("非同步响应不得计收件");
        try {
            Result.get((byte) 127);
            throw new AssertionError("未知同步结果字节必须拒绝");
        } catch (RuntimeException expected) {
            // 当前枚举只有成功与重复，未知字节在协议解码边界拒绝。
        }
        Method payload = Driver.class.getDeclaredMethod("makePayload", long.class, int.class,
                long.class, String.class);
        payload.setAccessible(true);
        for (String mode : new String[]{"random", "structured"}) {
            for (int size : new int[]{32, 256, 1024, 1000000}) {
                String value = (String) payload.invoke(null, 12L, size, 42L, mode);
                if (value.length() != size || !value.startsWith("RB1:000000000012:"))
                    throw new AssertionError("长度或序号不正确");
                if (!value.equals(payload.invoke(null, 12L, size, 42L, mode)))
                    throw new AssertionError("载荷不确定");
                for (char ch : value.toCharArray())
                    if (ch > 127) throw new AssertionError("非 ASCII 载荷");
            }
        }
        for (long seq : new long[]{0, 1, 59}) {
            String digits = (String) payload.invoke(null, seq, 2048, 42L, "digits");
            if (!digits.matches("[0-9]{2048}") || !digits.startsWith(String.format("%012d", seq)))
                throw new AssertionError("数字载荷必须恰好2048字节且包含可解析序号");
            if (!digits.equals(payload.invoke(null, seq, 2048, 42L, "digits")))
                throw new AssertionError("相同种子与序号必须生成相同载荷");
        }
        String structured = (String) payload.invoke(null, 0L, 8192, 42L, "structured");
        String random = (String) payload.invoke(null, 0L, 8192, 42L, "random");
        if (compressed(structured) >= compressed(random) / 4)
            throw new AssertionError("结构化正文应明显更易压缩");
        Constructor<?> constructor = Driver.class.getDeclaredConstructor(Path.class, int.class, String.class);
        constructor.setAccessible(true);
        Path root = Paths.get(args[0]);
        Object driver = constructor.newInstance(root, 1, "subscriber");
        Method check = Driver.class.getDeclaredMethod("observeContent", String.class, String.class,
                boolean.class, int.class, long.class, String.class);
        check.setAccessible(true);
        String valid = (String) payload.invoke(null, 0L, 128, 42L, "structured");
        check.invoke(driver, valid, "uuid", true, 128, 42L, "structured");
        check.invoke(driver, valid.substring(0, valid.length()-1) + "!", "uuid", true, 128, 42L, "structured");
        check.invoke(driver, "broken", "uuid", true, 128, 42L, "structured");
        response.setResult(null);
        check.invoke(driver, valid, "uuid", accepted.invoke(null, response), 128, 42L, "structured");
        List<String> events = Files.readAllLines(root.resolve("subscriber-1.jsonl"));
        if (events.stream().filter(line -> line.contains("\"receive\"")).count() != 2
                || events.stream().filter(line -> line.contains("\"content_mismatch\"")).count() != 2)
            throw new AssertionError("内容错误不得改变业务接收计数");
        Path digitsRoot = root.resolve("digits");
        Files.createDirectories(digitsRoot);
        Object digitsDriver = constructor.newInstance(digitsRoot, 1, "subscriber");
        String digitsValue = (String) payload.invoke(null, 0L, 2048, 42L, "digits");
        check.invoke(digitsDriver, digitsValue, "uuid", true, 2048, 42L, "digits");
        String changed = digitsValue.substring(0, 2047) + (digitsValue.endsWith("0") ? "1" : "0");
        check.invoke(digitsDriver, changed, "uuid", true, 2048, 42L, "digits");
        List<String> digitEvents = Files.readAllLines(digitsRoot.resolve("subscriber-1.jsonl"));
        if (digitEvents.stream().filter(line -> line.contains("\"payload_received\"")
                && line.contains("\"value_bytes\":2048") && line.contains("\"sha256\":")).count() != 2
                || digitEvents.stream().filter(line -> line.contains("\"content_mismatch\"")).count() != 1)
            throw new AssertionError("数字载荷必须记录实际SHA-256并识别单字符篡改");
        System.out.println("载荷及全文校验通过");
    }

    private static int compressed(String value) throws Exception {
        byte[] bytes = value.getBytes("US-ASCII");
        Deflater deflater = new Deflater();
        deflater.setInput(bytes);
        deflater.finish();
        int result = deflater.deflate(new byte[bytes.length * 2]);
        deflater.end();
        return result;
    }
}
