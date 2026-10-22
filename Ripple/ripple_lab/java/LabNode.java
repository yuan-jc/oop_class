import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.netty.channel.Channel;
import ripple.client.RippleClient;
import ripple.common.entity.NodeMetadata;
import ripple.common.hashing.ModHashing;
import ripple.server.RippleServer;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** 独立实验入口，所有业务处理继续使用未经修改的 Ripple。 */
public final class LabNode {
    private final JsonNode config;
    private final JsonNode node;
    private final String id;
    private final Path run;
    private final Path control;
    private final LabEvents events;
    private final LabObserver observer;
    private final ScheduledExecutorService scanner = Executors.newSingleThreadScheduledExecutor();
    private RippleServer server;
    private RippleClient client;
    private volatile boolean shuttingDown;
    private LabNode(JsonNode config, String id) throws Exception {
        this.config = config; this.id = id;
        JsonNode selected = null;
        Map<String,String> peers = new HashMap<>();
        Map<String,LabContent> publishers = new HashMap<>();
        for (JsonNode candidate : config.path("nodes")) {
            if (candidate.path("id").asText().equals(id)) selected = candidate;
            peers.put(candidate.path("ip").asText(),candidate.path("id").asText());
            if (candidate.path("role").asText().equals("publisher")) publishers.put(candidate.path("id").asText(),
                    new LabContent(candidate.path("size").asInt(),candidate.path("seed").asLong()));
        }
        if (selected == null) throw new IllegalArgumentException("未知节点：" + id);
        node = selected; run = Paths.get(config.path("run_directory").asText()); control = run.resolve("control");
        Files.createDirectories(control); Files.createDirectories(databaseDirectory());
        events = new LabEvents(run.resolve("events").resolve(id + ".jsonl"),id);
        observer = new LabObserver(events,role().equals("subscriber"),peers,publishers);
    }
    private String role() { return node.path("role").asText(); }
    private Path databaseDirectory() {
        return config.hasNonNull("database_directory") ? Paths.get(config.path("database_directory").asText()) : run.resolve("databases");
    }
    private boolean stopped() { return shuttingDown || Files.exists(control.resolve("stop")); }
    private List<NodeMetadata> servers() {
        List<NodeMetadata> list = new ArrayList<>();
        for (JsonNode candidate : config.path("nodes")) if (candidate.path("role").asText().equals("server")) {
            list.add(new NodeMetadata(candidate.path("server_number").asInt(),candidate.path("ip").asText(),candidate.path("api_port").asInt()));
        }
        return list;
    }
    private void start() throws Exception {
        List<NodeMetadata> list = servers();
        String database = databaseDirectory().resolve(id + ".sqlite").toString();
        String ip = node.path("ip").asText();
        if (role().equals("server")) {
            server = RippleServer.hashingBasedProtocol(node.path("server_number").asInt(),database,ip,
                    node.path("api_port").asInt(),node.path("ui_port").asInt(),new ModHashing(list.size(),200));
            server.getNode().setNodeList(list);
            if (!server.start()) throw new IllegalStateException("服务端启动失败");
        } else {
            String targetId = node.path("server").asText();
            NodeMetadata target = null;
            for (JsonNode candidate : config.path("nodes")) if (candidate.path("id").asText().equals(targetId)) {
                target = new NodeMetadata(candidate.path("server_number").asInt(),candidate.path("ip").asText(),candidate.path("api_port").asInt());
            }
            if (target == null) throw new IllegalArgumentException("未知服务端：" + targetId);
            final NodeMetadata selected = target;
            client = new RippleClient(list,(application,key,nodes) -> selected,database,ip,"chinese");
            client.setApiPort(node.path("api_port").asInt()); client.setUiPort(node.path("ui_port").asInt());
            if (!client.start()) throw new IllegalStateException("客户端启动失败");
        }
        events.simple("observation_notice","新连接每 10 毫秒安装观测器；首次回调可能早于安装，原始日志保留该边界，暖机确认订阅链路");
        scanner.scheduleWithFixedDelay(() -> {
            try { scan(); } catch (Exception e) { events.simple("error","扫描连接：" + e); }
        },0,10,TimeUnit.MILLISECONDS);
        if (server != null) server.initCluster(list);
        if (client != null) {
            // 预先建立配置的首连，等观测器安装后再提交订阅或负载。
            for (JsonNode publisher : config.path("nodes")) if (publisher.path("role").asText().equals("publisher")) {
                Channel channel = client.findOrConnectToServer(application(),"load-" + publisher.path("id").asText());
                observer.attach(channel); channel.eventLoop().submit(() -> {}).sync();
                if (role().equals("subscriber")) {
                    client.subscribe(application(),"load-" + publisher.path("id").asText());
                    events.simple("subscribe","load-" + publisher.path("id").asText());
                }
            }
        }
        Files.write(control.resolve("ready-" + id),new byte[0]);
        events.simple("ready","已启动并提交全部订阅；端到端就绪由控制器暖机确认");
    }
    private String application() { return config.path("application").asText("ripple-lab"); }
    private void scan() {
        if (server != null && server.getNode().getApiServer().getConnectedNodes() != null) {
            for (Channel channel : new ArrayList<>(server.getNode().getApiServer().getConnectedNodes())) observer.attach(channel);
        }
        if (client != null) {
            for (Channel channel : new ArrayList<>(client.getServerConnections().values())) observer.attach(channel);
            for (Channel channel : new ArrayList<>(client.getClientConnections().values())) observer.attach(channel);
            if (client.getConnectedNodes() != null) for (Channel channel : new ArrayList<>(client.getConnectedNodes())) observer.attach(channel);
        }
    }
    private void publish(long seq) {
        String value = LabPayload.create(id,seq,node.path("size").asInt(),node.path("seed").asLong());
        if (seq >= 0) {
            Map<String,Object> event = events.base("send");
            event.put("type","PUT_REQUEST"); event.put("publisher",id); event.put("seq",seq);
            event.put("bytes",LabContent.bytes(value)); event.put("payload_sha256",LabContent.sha256(value));
            event.put("preview",value.substring(0,Math.min(96,value.length())));
            event.put("peer",node.path("server").asText());
            event.put("note","开始调用 RippleClient.put；不代表已写入网络或收到成功响应");
            events.emit(event);
        }
        client.put(application(),"load-" + id,value);
    }
    private void loop() throws Exception {
        boolean loaded = false;
        while (!stopped()) {
            events.check();
            if (role().equals("publisher")) {
                Path probe = control.resolve("probe-" + id);
                if (Files.deleteIfExists(probe)) publish(-1);
                if (!loaded && Files.exists(control.resolve("start"))) { loaded = true; load(); }
            }
            Thread.sleep(10);
        }
    }
    private void load() throws Exception {
        double start = System.currentTimeMillis()/1000.0;
        long origin = System.nanoTime();
        double duration = node.path("duration").asDouble();
        double rate = node.path("rate").asDouble();
        LabPacer pacing = new LabPacer(rate,origin);
        LabLoadDispatcher dispatcher = new LabLoadDispatcher(origin + (long)(duration*1e9),System::nanoTime,
                () -> stopped() || Files.exists(control.resolve("stop_sending")), seq -> {
                    try { publish(seq); }
                    catch (Throwable error) {
                        Map<String,Object> event = events.base("error");
                        event.put("publisher",id); event.put("seq",seq); event.put("ok",false);
                        event.put("note","RippleClient.put 调用失败：" + error); events.emit(event);
                    }
                });
        events.simple("load_start","开始正式负载");
        try { while (!stopped() && !Files.exists(control.resolve("stop_sending"))) {
            events.check();
            long now = System.nanoTime();
            if ((now-origin)/1e9 >= duration) break;
            if (pacing.isDue(now)) {
                dispatcher.offer();
                pacing.advance(System.nanoTime());
            } else {
                long pause = Math.min(10000000L,pacing.remaining(now));
                Thread.sleep(pause/1000000L,(int)(pause%1000000L));
            }
        } } finally { dispatcher.finish(); }
        Map<String,Object> sent = new LinkedHashMap<>();
        sent.put("submitted",dispatcher.submitted()); sent.put("start",start); sent.put("end",System.currentTimeMillis()/1000.0);
        sent.put("in_flight",dispatcher.inFlight()); sent.put("blocked_slots",dispatcher.blockedSlots());
        sent.put("semantics","submitted 是已开始调用 put 的次数；end 是停止调度时间，已进入的原库调用可能继续阻塞或稍后写网");
        Path temporary = control.resolve("sent-" + id + ".tmp");
        new ObjectMapper().writeValue(temporary.toFile(),sent);
        Files.move(temporary,control.resolve("sent-" + id + ".json"),StandardCopyOption.REPLACE_EXISTING);
        events.simple("load_end","停止调度；已开始 put " + dispatcher.submitted() + " 条，忙碌跳过时隙 "
                + dispatcher.blockedSlots() + "，调用仍在执行=" + dispatcher.inFlight());
    }
    private synchronized void close() throws Exception {
        if (shuttingDown) return;
        shuttingDown = true;
        scanner.shutdown(); scanner.awaitTermination(5,TimeUnit.SECONDS);
        // 先等待业务网络停止，最后排空事件，保留断开与写回调尾部。
        if (client != null) client.stop();
        if (server != null) server.stop();
        events.close();
    }
    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--self-test")) { LabSelfTest.run(); return; }
        if (args.length != 2) throw new IllegalArgumentException("用法：LabNode <runtime.json> <nodeId>");
        LabNode process = new LabNode(new ObjectMapper().readTree(Paths.get(args[0]).toFile()),args[1]);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try { process.close(); } catch (Exception e) { e.printStackTrace(); }
        },"实验节点退出"));
        int status = 0;
        try { process.start(); process.loop(); }
        catch (Throwable e) { process.events.simple("error",e.toString()); e.printStackTrace(); status = 1; }
        finally {
            try { process.close(); }
            catch (Throwable error) { error.printStackTrace(); status = 1; }
            // 即使最终写盘失败，也不能遗留原项目 SQLite 非守护线程。
            System.exit(status);
        }
    }
}
