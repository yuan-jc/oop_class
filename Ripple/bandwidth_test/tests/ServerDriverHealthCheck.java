import ripple.common.entity.NodeMetadata;
import java.util.*;

/** 只验证现有健康状态的读取，不发送心跳或更改引擎状态。 */
public class ServerDriverHealthCheck {
    public static void main(String[] args) {
        List<NodeMetadata> nodes = Arrays.asList(new NodeMetadata(1, "127.0.0.1", 13001),
                new NodeMetadata(2, "127.0.0.1", 13002));
        Map<NodeMetadata, Boolean> states = new HashMap<>();
        if (ServerDriver.allAlive(states, nodes)) throw new AssertionError("缺少节点状态时不可就绪");
        states.put(nodes.get(0), true);
        states.put(nodes.get(1), false);
        if (ServerDriver.allAlive(states, nodes)) throw new AssertionError("节点尚未存活时不可就绪");
        states.put(nodes.get(1), true);
        if (!ServerDriver.allAlive(states, nodes)) throw new AssertionError("全部存活时应就绪");
    }
}
