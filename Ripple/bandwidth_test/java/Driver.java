import io.netty.channel.Channel;
import ripple.client.RippleClient;
import ripple.client.core.HashingBasedSelector;
import ripple.common.entity.NodeMetadata;
import ripple.common.hashing.ModHashing;
import ripple.common.tcp.Handler;
import ripple.common.tcp.Message;
import ripple.common.tcp.MessageHandler;
import ripple.common.tcp.MessageType;
import ripple.common.tcp.message.*;

import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Instant;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** 外部测试驱动：加载原版 JAR，使用公开处理器接口观测，不修改引擎。 */
public class Driver {
    private final Path root;
    private final int id;
    private final PrintWriter events;
    private final Set<Channel> hooked = Collections.newSetFromMap(new ConcurrentHashMap<Channel, Boolean>());
    private final Map<UUID, Long> pending = new ConcurrentHashMap<>();
    private final AtomicBoolean subscribed = new AtomicBoolean();
    private RippleClient client;
    private int payloadSize;
    private long payloadSeed;
    private String payloadMode = "random";

    private Driver(Path root, int id, String role) throws Exception {
        this.root = root;
        this.id = id;
        events = new PrintWriter(new OutputStreamWriter(
                new FileOutputStream(root.resolve(role + "-" + id + ".jsonl").toFile()), StandardCharsets.UTF_8), true);
    }

    private static double now() {
        Instant value = Instant.now();
        return value.getEpochSecond() + value.getNano() / 1e9;
    }

    private synchronized void event(String type, long seq, String uuid, boolean ok, double lag) {
        events.printf(Locale.ROOT,
                "{\"event\":\"%s\",\"seq\":%d,\"id\":%d,\"time\":%.9f,\"uuid\":\"%s\",\"ok\":%s,\"lag_ms\":%.4f}%n",
                type, seq, id, now(), uuid, ok, lag);
    }

    private synchronized void contentEvent(String type, long seq, String uuid, String value, boolean ok) {
        try {
            byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
            StringBuilder hex = new StringBuilder(64);
            for (byte part : digest) hex.append(String.format(Locale.ROOT, "%02x", part & 255));
            events.printf(Locale.ROOT,
                "{\"event\":\"%s\",\"seq\":%d,\"id\":%d,\"time\":%.9f,\"uuid\":\"%s\",\"ok\":%s,\"value_bytes\":%d,\"sha256\":\"%s\"}%n",
                type, seq, id, now(), uuid, ok, bytes.length, hex);
        } catch (java.security.NoSuchAlgorithmException failure) {
            throw new IllegalStateException("缺少SHA-256算法", failure);
        }
    }

    private void hook(Channel channel) throws Exception {
        if (!channel.isActive() || !hooked.add(channel)) return;
        channel.eventLoop().submit(() -> {
            MessageHandler handler = channel.pipeline().get(MessageHandler.class);
            if (handler == null) throw new IllegalStateException("原版消息处理器尚未就绪");
            for (MessageType type : new MessageType[]{MessageType.SYNC_REQUEST, MessageType.DISPATCH_REQUEST,
                    MessageType.SUBSCRIBE_RESPONSE, MessageType.PUT_RESPONSE}) {
                Handler original = handler.getHandlers().get(type);
                if (original == null) continue;
                handler.registerHandler(type, (ctx, message) -> {
                    // 先执行原版业务逻辑，之后的时间才代表处理完成。
                    Message result = original.handle(ctx, message);
                    if (message instanceof SubscribeResponse) {
                        boolean ok = ((SubscribeResponse) message).isSuccess();
                        subscribed.set(ok);
                        event("subscribe_response", -1, message.getUuid().toString(), ok, 0);
                    } else if (message instanceof PutResponse) {
                        Long seq = pending.remove(message.getUuid());
                        if (seq != null) event("put_response", seq, message.getUuid().toString(),
                                ((PutResponse) message).isSuccess(), 0);
                    } else {
                        String value, uuid;
                        boolean ok;
                        if (message instanceof SyncRequest) {
                            SyncRequest request = (SyncRequest) message;
                            value = request.getValue();
                            uuid = request.getMessageUuid().toString();
                            ok = acceptedSync(result);
                        } else {
                            DispatchRequest request = (DispatchRequest) message;
                            value = request.getValue();
                            uuid = request.getMessageUuid().toString();
                            ok = result instanceof DispatchResponse && ((DispatchResponse) result).isSuccess();
                        }
                        observeContent(value, uuid, ok, payloadSize, payloadSeed, payloadMode);
                    }
                    return result;
                });
            }
        }).sync();
    }

    private void hookConnections() throws Exception {
        for (Channel channel : client.getServerConnections().values()) hook(channel);
        for (Channel channel : client.getClientConnections().values()) hook(channel);
    }

    private static boolean acceptedSync(Message response) {
        if (!(response instanceof SyncResponse)) return false;
        Result result = ((SyncResponse) response).getResult();
        return result == Result.SUCCESS || result == Result.DUPLICATED;
    }

    private void observeContent(String value, String uuid, boolean ok, int size, long seed, String mode) {
        if (!ok) return;
        long seq = -2;
        if (value != null && (value.startsWith("RB1:") || mode.equals("digits"))) {
            try {
                seq = mode.equals("digits") ? Long.parseLong(value.substring(0, 12))
                        : Long.parseLong(value.split(":", 3)[1]);
                event("receive", seq, uuid, true, 0);
            } catch (NumberFormatException | IndexOutOfBoundsException ignored) {
                // 测试头损坏也应留下完整性证据，不中断原业务处理器。
            }
        }
        boolean identical = seq != -2 && makePayload(seq, size, seed, mode).equals(value);
        if (mode.equals("digits") && value != null)
            contentEvent("payload_received", seq, uuid, value, identical);
        if (!identical)
            event("content_mismatch", seq, uuid, false, 0);
    }

    private static String makePayload(long seq, int size, long seed, String mode) {
        String header = mode.equals("digits") ? String.format(Locale.ROOT, "%012d", seq)
                : String.format(Locale.ROOT, "RB1:%012d:", seq);
        if (size < header.length()) throw new IllegalArgumentException("消息长度不足");
        Random random = new Random(seed + seq);
        String chars = "abcdefghijklmnopqrstuvwxyz0123456789";
        StringBuilder value = new StringBuilder(size).append(header);
        if (mode.equals("structured")) {
            String template = "{\"device\":\"sensor-001\",\"status\":\"normal\",\"temperature\":23,\"region\":\"east\"}|";
            while (value.length() < size) {
                int remaining = size - value.length();
                value.append(template, 0, Math.min(remaining, template.length()));
            }
        } else if (mode.equals("digits")) {
            while (value.length() < size) value.append((char)('0' + random.nextInt(10)));
        } else if (mode.equals("random")) {
            while (value.length() < size) value.append(chars.charAt(random.nextInt(chars.length())));
        } else throw new IllegalArgumentException("未知载荷模式：" + mode);
        return value.toString();
    }

    private void publish(Channel channel, String app, long seq, int size, long seed, double lag) {
        PutRequest request = new PutRequest();
        request.setUuid(UUID.randomUUID());
        request.setApplicationName(app);
        request.setKey("load");
        request.setValue(makePayload(seq, size, seed, payloadMode));
        pending.put(request.getUuid(), seq);
        event("send", seq, request.getUuid().toString(), true, lag);
        if (payloadMode.equals("digits"))
            contentEvent("payload_source", seq, request.getUuid().toString(), request.getValue(), true);
        channel.writeAndFlush(request).addListener(future ->
                event("write", seq, request.getUuid().toString(), future.isSuccess(), 0));
    }

    private void run(String[] args) throws Exception {
        String role = args[0], address = args[1], nodesText = args[2], app = args[4];
        int size = Integer.parseInt(args[6]);
        double rate = Double.parseDouble(args[7]), duration = Double.parseDouble(args[8]);
        long seed = Long.parseLong(args[9]);
        payloadSize = size;
        payloadSeed = seed;
        payloadMode = args.length > 11 ? args[11] : "random";
        List<NodeMetadata> nodes = new ArrayList<>();
        for (String text : nodesText.split(",")) {
            String[] node = text.split(":");
            nodes.add(new NodeMetadata(Integer.parseInt(node[0]), node[1], Integer.parseInt(node[2])));
        }
        client = new RippleClient(nodes, new HashingBasedSelector(new ModHashing(nodes.size(), 200)),
                Paths.get(args[10]).resolve(role + "-" + id + ".db").toString(), address);
        client.setApiPort(id == 0 ? 15000 : 15000 + id);
        if (!client.start()) throw new IllegalStateException("客户端启动失败");
        Channel channel = client.findOrConnectToServer(app, "load");
        if (channel == null || !channel.isActive()) throw new IllegalStateException("连接服务端失败");
        hook(channel);
        if (role.equals("subscriber")) {
            client.subscribe(app, "load");
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20);
            boolean callback = false;
            while (System.nanoTime() < deadline) {
                hookConnections();
                callback = false;
                for (Channel incoming : client.getClientConnections().values()) {
                    callback |= incoming.isActive()
                            && ((InetSocketAddress) incoming.localAddress()).getPort() == client.getApiPort()
                            && hooked.contains(incoming);
                }
                if (subscribed.get() && callback) break;
                Thread.sleep(20);
            }
            if (!subscribed.get() || !callback) throw new IllegalStateException("订阅或回调连接未就绪");
        }
        Files.write(root.resolve(role + "-" + id + ".ready"), new byte[]{1});
        if (role.equals("publisher")) {
            while (!Files.exists(root.resolve("start")) && !Files.exists(root.resolve("stop"))) {
                Path probe = root.resolve("probe");
                if (Files.exists(probe)) {
                    publish(channel, app, -1, size, seed, 0);
                    Files.deleteIfExists(probe);
                }
                hookConnections();
                Thread.sleep(20);
            }
            if (!Files.exists(root.resolve("stop"))) {
                event("load_start", -1, "", true, 0);
                long begin = System.nanoTime(), end = begin + (long) (duration * 1e9);
                long next = begin;
                long planned = (long) Math.ceil(rate * duration);
                for (long seq = 0; seq < planned; seq++) {
                    long current = System.nanoTime();
                    if (current < next) TimeUnit.NANOSECONDS.sleep(next-current);
                    current = System.nanoTime();
                    if (current >= end || Files.exists(root.resolve("stop"))) break;
                    if (!channel.isActive()) throw new IllegalStateException("发送连接中断");
                    double lag = Math.max(0, current - (begin + (long) (seq * 1e9 / rate))) / 1e6;
                    publish(channel, app, seq, size, seed, lag);
                    // 不用无上限突发追赶已经错过的调度时隙。
                    next = Math.max(next + (long) (1e9 / rate), current + (long) (1e9 / rate));
                }
                long remaining = end-System.nanoTime();
                if (remaining > 0) TimeUnit.NANOSECONDS.sleep(remaining);
                event("load_end", -1, "", true, 0);
                Files.write(root.resolve("publisher.sent"), new byte[]{1});
            }
        }
        while (!Files.exists(root.resolve("stop"))) {
            hookConnections();
            Thread.sleep(20);
        }
    }

    public static void main(String[] args) throws Exception {
        Driver driver = new Driver(Paths.get(args[3]), Integer.parseInt(args[5]), args[0]);
        int status = 0;
        try {
            driver.run(args);
        } catch (Throwable failure) {
            status = 1;
            driver.event("error", -1, "", false, 0);
            failure.printStackTrace();
        } finally {
            driver.events.close();
            if (driver.client != null) driver.client.stop();
        }
        System.exit(status);
    }
}
