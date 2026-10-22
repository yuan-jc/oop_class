import io.netty.channel.*;
import ripple.common.tcp.*;
import java.net.InetSocketAddress;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** 解码与原处理器返回分别记录，绝不把接收视为处理成功。 */
public final class LabObserver {
    private final LabEvents events;
    private final boolean subscriber;
    private final Map<String,String> peers;
    private final Map<String,LabContent> publishers;
    private final Map<String,Map<String,Object>> correlations = Collections.synchronizedMap(
            new LinkedHashMap<String,Map<String,Object>>(1024, .75f, true) {
                protected boolean removeEldestEntry(Map.Entry<String,Map<String,Object>> e) {
                    if (size() <= 65536) return false;
                    Map<String,Object> gap = events.base("observation_gap");
                    gap.put("request_uuid",e.getKey()); gap.put("dropped",1);
                    gap.put("note","请求关联缓存达到上限，淘汰旧请求；后续响应可能缺少发布者与序号");
                    events.emit(gap); return true;
                }
            });
    public LabObserver(LabEvents events, boolean subscriber, Map<String,String> peers, Map<String,LabContent> publishers) {
        this.events = events; this.subscriber = subscriber; this.peers = peers; this.publishers = publishers;
    }
    private static Object property(Object object, String name) {
        if (object == null) return null;
        try { return object.getClass().getMethod(name).invoke(object); }
        catch (ReflectiveOperationException ignored) { return null; }
    }
    private static Boolean success(Object message) {
        Object value = property(message,"isSuccess");
        if (value instanceof Boolean) return (Boolean)value;
        Object result = property(message,"getResult");
        if (result != null) return result.toString().equals("SUCCESS") || result.toString().equals("DUPLICATED");
        return null;
    }
    public Map<String,Object> describe(String event, Message message, Channel channel, Boolean ok) {
        Map<String,Object> data = events.base(event);
        data.put("type", message.getType().toString());
        String uuid = String.valueOf(message.getUuid());
        data.put("request_uuid", message.getUuid() == null ? null : uuid);
        Object value = property(message,"getValue");
        LabPayload payload = LabPayload.parse(value instanceof String ? (String)value : null);
        if (payload != null) {
            data.put("publisher",payload.publisher); data.put("seq",payload.seq);
            data.put("bytes", LabContent.bytes((String)value));
            data.put("preview", ((String)value).substring(0,Math.min(96,((String)value).length())));
            if (message.getUuid() != null) correlations.put(uuid,new HashMap<>(data));
        } else {
            Map<String,Object> related = correlations.get(uuid);
            if (related != null) for (String key : new String[]{"publisher","seq","bytes","preview","message_uuid"}) data.put(key,related.get(key));
        }
        Object messageUuid = property(message,"getMessageUuid");
        if (messageUuid != null) data.put("message_uuid",messageUuid.toString());
        data.put("ok",ok != null ? ok : success(message));
        if (channel != null && channel.remoteAddress() instanceof InetSocketAddress) {
            String ip = ((InetSocketAddress)channel.remoteAddress()).getAddress().getHostAddress();
            data.put("peer",peers.containsKey(ip) ? peers.get(ip) : channel.remoteAddress().toString());
        }
        return data;
    }
    private boolean isLoad(Message message) {
        Object key = property(message,"getKey");
        return key instanceof String && ((String)key).startsWith("load-") && publishers.containsKey(((String)key).substring(5));
    }
    private void delivery(Message message, Channel channel) {
        Map<String,Object> data = describe("delivery",message,channel,true);
        Object raw = property(message,"getValue");
        String value = raw instanceof String ? (String)raw : null;
        String publisher = ((String)property(message,"getKey")).substring(5);
        LabContent specification = publishers.get(publisher);
        LabPayload parsed = LabPayload.parse(value);
        boolean valid = parsed != null && parsed.publisher.equals(publisher)
                && LabContent.matches(value,publisher,parsed.seq,specification.size,specification.seed);
        data.put("publisher",publisher); data.put("content_ok",valid);
        data.put("bytes",value == null ? 0 : LabContent.bytes(value));
        data.put("payload_sha256",value == null ? null : LabContent.sha256(value));
        events.emit(data);
        if (!valid) {
            Map<String,Object> error = new LinkedHashMap<>(data);
            error.put("event","error"); error.put("ok",false);
            error.put("note","原处理器已返回成功，但完整载荷与配置种子、大小、发布者或序号不匹配");
            events.emit(error);
        }
    }
    public void attach(Channel channel) {
        if (channel == null || !channel.isOpen()) return;
        channel.eventLoop().execute(() -> {
            if (channel.pipeline().get("lab-observer") != null) return;
            ChannelPipeline pipeline = channel.pipeline();
            MessageHandler handler = pipeline.get(MessageHandler.class);
            if (handler == null) return;
            for (Map.Entry<MessageType,Handler> entry : new ArrayList<>(handler.getHandlers().entrySet())) {
                final Handler original = entry.getValue();
                handler.registerHandler(entry.getKey(), (context,message) -> {
                    try {
                        Message result = original.handle(context,message);
                        Boolean success = success(result);
                        events.emit(describe("processed",message,context.channel(),success));
                        if (subscriber && (message.getType() == MessageType.DISPATCH_REQUEST || message.getType() == MessageType.SYNC_REQUEST)
                                && isLoad(message) && Boolean.TRUE.equals(success)) {
                            delivery(message,context.channel());
                        }
                        return result;
                    } catch (RuntimeException e) {
                        Map<String,Object> error = describe("error",message,context.channel(),false);
                        error.put("note",e.toString()); events.emit(error); throw e;
                    }
                });
            }
            pipeline.addBefore(pipeline.context(handler).name(),"lab-observer",new ChannelDuplexHandler() {
                public void channelRead(ChannelHandlerContext ctx,Object msg) throws Exception {
                    if (msg instanceof Message) events.emit(describe("receive",(Message)msg,ctx.channel(),null));
                    super.channelRead(ctx,msg);
                }
                public void write(ChannelHandlerContext ctx,Object msg,ChannelPromise promise) throws Exception {
                    ChannelPromise observedPromise = promise.unvoid();
                    if (msg instanceof Message) {
                        Message message = (Message)msg;
                        events.emit(describe("wire_send",message,ctx.channel(),null));
                        observedPromise.addListener(future -> {
                            Map<String,Object> data = describe("write",message,ctx.channel(),future.isSuccess());
                            if (!future.isSuccess() && future.cause() != null) data.put("note",future.cause().toString());
                            events.emit(data);
                        });
                    }
                    super.write(ctx,msg,observedPromise);
                }
                public void channelInactive(ChannelHandlerContext ctx) throws Exception {
                    events.simple("disconnected",String.valueOf(ctx.channel().remoteAddress()));
                    super.channelInactive(ctx);
                }
            });
            events.simple("connected",String.valueOf(channel.remoteAddress()));
        });
    }
}
