import ripple.server.RippleServer;
import ripple.common.entity.NodeMetadata;
import ripple.common.hashing.ModHashing;
import java.nio.file.*;
import java.util.*;

/** 只协调原版服务的监听与集群初始化顺序，不替换任何业务处理器。 */
public class ServerDriver {
    static boolean allAlive(Map<NodeMetadata, Boolean> states, List<NodeMetadata> nodes) {
        for (NodeMetadata node : nodes)
            if (!Boolean.TRUE.equals(states.get(node))) return false;
        return true;
    }

    public static void main(String[] args) throws Exception {
        Path root = Paths.get(args[0]);
        int id = Integer.parseInt(System.getProperty("id"));
        List<NodeMetadata> nodes = new ArrayList<>();
        for (String text : System.getProperty("nodes").split(",")) {
            String[] node = text.split(":");
            nodes.add(new NodeMetadata(Integer.parseInt(node[0]), node[1], Integer.parseInt(node[2])));
        }
        RippleServer server = RippleServer.hashingBasedProtocol(id,
            System.getProperty("storageLocation"), System.getProperty("address"),
            Integer.parseInt(System.getProperty("apiPort")), Integer.parseInt(System.getProperty("uiPort", "0")),
            new ModHashing(Integer.parseInt(System.getProperty("candidateCount", "3")),
                           Integer.parseInt(System.getProperty("divisor", "200"))));
        int status = 0;
        try {
            server.getNode().setNodeList(nodes);
            if (!server.start()) throw new IllegalStateException("服务监听启动失败");
            Files.write(root.resolve("server-" + id + ".listening"), new byte[]{1});
            while (!Files.exists(root.resolve("cluster.start")) && !Files.exists(root.resolve("stop")))
                Thread.sleep(20);
            if (!Files.exists(root.resolve("stop"))) {
                server.initCluster(nodes);
                long deadline = System.nanoTime() + 45_000_000_000L;
                while (!allAlive(server.getNode().getHealthManager().getAliveMap(), nodes)) {
                    if (Files.exists(root.resolve("stop"))) break;
                    if (System.nanoTime() >= deadline)
                        throw new IllegalStateException("等待原版集群全部节点存活超时（45秒）");
                    Thread.sleep(20);
                }
                if (!Files.exists(root.resolve("stop"))) {
                    Files.write(root.resolve("server-" + id + ".ready"), new byte[]{1});
                    while (!Files.exists(root.resolve("stop"))) Thread.sleep(20);
                }
            }
        } catch (Throwable failure) {
            status = 1;
            failure.printStackTrace();
        } finally {
            server.stop();
        }
        System.exit(status);
    }
}
