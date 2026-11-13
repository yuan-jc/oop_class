package ripple.server.tcp;

import io.netty.channel.Channel;
import io.netty.channel.socket.nio.NioSocketChannel;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import ripple.common.storage.sqlite.SqliteStorage;
import ripple.server.core.Node;

import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

import static org.junit.Assert.*;

public class NettyServerTest {
    private Node node;
    private NettyServer server;

    @Before
    public void createServer() {
        node = new Node(1, null, ":memory:", "127.0.0.1") {
            @Override
            public void updateCpuLoad(long delay) {
                // 通道查找测试无需采样真实CPU或等待。
            }
        };
        server = new NettyServer(node, "127.0.0.1", 0);
    }

    @After
    public void releaseNode() throws Exception {
        node.getExecutorService().shutdownNow();
        ((SqliteStorage) node.getStorage()).getConnection().close();
    }

    @Test
    public void connectedNodesAreReadyBeforeStartAndIterationHasStableSnapshot() {
        List<Channel> channels = server.getConnectedNodes();
        assertNotNull(channels);
        Channel first = channel(true, new InetSocketAddress("127.0.0.1", 1111));
        Channel second = channel(true, new InetSocketAddress("127.0.0.1", 2222));
        channels.add(first);
        Iterator<Channel> snapshot = channels.iterator();
        channels.remove(first);
        channels.add(second);
        assertSame(first, snapshot.next());
        assertFalse(snapshot.hasNext());
        assertSame(second, server.findChannel("127.0.0.1", 2222));
    }

    @Test
    public void nullSlotsAreIgnored() throws Exception {
        channels().add(null);
        assertNull(server.findChannel("127.0.0.1", 1111));
    }

    @Test
    public void unconnectedNioChannelIsIgnored() throws Exception {
        NioSocketChannel channel = new NioSocketChannel();
        try {
            channels().add(channel);
            assertNull(server.findChannel("127.0.0.1", 1111));
        } finally {
            channel.unsafe().closeForcibly();
        }
    }

    @Test
    public void inactiveChannelIsIgnoredEvenWhenItsAddressMatches() throws Exception {
        channels().add(channel(false, new InetSocketAddress("127.0.0.1", 1111)));
        assertNull(server.findChannel("127.0.0.1", 1111));
    }

    @Test
    public void missingNonInternetAndUnresolvedAddressesAreIgnored() throws Exception {
        channels().add(channel(true, null));
        channels().add(channel(true, new SocketAddress() { }));
        channels().add(channel(true, InetSocketAddress.createUnresolved("missing.invalid", 1111)));
        assertNull(server.findChannel("missing.invalid", 1111));
    }

    @Test
    public void activeInternetChannelMatchesHostAndPortWithoutConcreteChannelCast() throws Exception {
        Channel expected = channel(true, new InetSocketAddress("127.0.0.1", 2222));
        channels().add(null);
        channels().add(channel(false, new InetSocketAddress("127.0.0.1", 2222)));
        channels().add(channel(true, new InetSocketAddress("127.0.0.1", 3333)));
        channels().add(expected);
        assertSame(expected, server.findChannel("127.0.0.1", 2222));
        assertNull(server.findChannel("127.0.0.2", 2222));
        assertNull(server.findChannel("127.0.0.1", 4444));
    }

    private List<Channel> channels() throws Exception {
        if (server.getConnectedNodes() == null) {
            // 旧实现仅在start初始化；直接注入旧容器以单独复现查找缺陷。
            Field field = NettyServer.class.getDeclaredField("connectedNodes");
            field.setAccessible(true);
            field.set(server, new ArrayList<Channel>());
        }
        return server.getConnectedNodes();
    }

    private static Channel channel(boolean active, SocketAddress address) {
        return (Channel) Proxy.newProxyInstance(Channel.class.getClassLoader(), new Class<?>[]{Channel.class},
                (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "isActive": return active;
                        case "remoteAddress": return address;
                        case "equals": return proxy == args[0];
                        case "hashCode": return System.identityHashCode(proxy);
                        case "toString": return "测试通道";
                        default: throw new AssertionError("不应调用: " + method.getName());
                    }
                });
    }
}
