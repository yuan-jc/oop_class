# Ripple 核心对象 UML

日期：2026-10-22  
源码：`Ripple/`，当前 HEAD `0469814`；带宽基准提交为 `468e9cb`（V0）。  
V1/V2 线格式开关见 `Ripple/documents/BandwidthOptimization.zh-cn.md`。

本文只画 **`put` 传播链路和带宽相关对象**，不包含 UI Servlet、全部编解码器和所有 Overlay 变体。图中的 Mermaid 代码可直接在 GitHub、支持 Mermaid 的 Markdown 预览器中渲染；如果编辑器不支持，可粘贴到 <https://mermaid.live> 查看。

关系符号：`<|--` 继承/实现，`*--` 组合，`o--` 聚合，`-->` 关联，`..>` 调用或依赖。

## 1. 领域消息与实体

```mermaid
classDiagram
direction LR

class AbstractMessage {
  <<abstract>>
  -UUID uuid
  -String type
  -String applicationName
  -String key
  -Date lastUpdate
  -int lastUpdateServerId
  -int fromId
  +getUuid() UUID
  +getType() String
  +getApplicationName() String
  +getKey() String
  +getLastUpdate() Date
  +getLastUpdateServerId() int
  +getFromId() int
}

class UpdateMessage {
  -String value
}

class IncrementalUpdateMessage {
  -UUID baseMessageUuid
  -String atomicOperation
  -String value
}

class DeleteMessage

AbstractMessage <|-- UpdateMessage
AbstractMessage <|-- IncrementalUpdateMessage
AbstractMessage <|-- DeleteMessage

class Item {
  -String applicationName
  -String key
  -String value
  +equals(Object) boolean
  +hashCode() int
}

class NodeMetadata {
  -int id
  -String address
  -int port
  +equals(Object) boolean
  +hashCode() int
}

class ClientMetadata {
  -String address
  -int port
  +compareTo(ClientMetadata) int
}

class Ack {
  -UUID messageUuid
  -Set~Integer~ nodeList
  -Set~Integer~ ackNodes
}

Ack ..> AbstractMessage : messageUuid 指向

note for Ack "nodeList = 应收 ACK 的服务端；ackNodes = 已记录 ACK 的服务端"

note for Item "equals/hashCode 只使用 applicationName + key，value 不参与键身份"
```

要点：

- `UpdateMessage`、`IncrementalUpdateMessage`、`DeleteMessage` 是三种领域消息，`type` 分别是 `update`、`incremental_update`、`delete`。
- `lastUpdateServerId` 表示消息最初由哪个服务端产生；`fromId` 表示当前这一跳由谁发出。
- `Item` 是 `(applicationName, key)` 的索引对象；实际值由消息列表和 `MessageBasedResolver` 合并得到。

## 2. 服务端传播核心

```mermaid
classDiagram
direction LR

class Node {
  -int id
  -Overlay overlay
  -Storage storage
  -List~NodeMetadata~ nodeList
  -Map~Item,Set~ subscription
  -Set~ClientMetadata~ connectedClients
  -Tracker tracker
  -HealthManager healthManager
  -ClientDispatcher clientDispatcher
  -ClientListCache clientListCache
  -NettyServer apiServer
  -Worker worker
  -ExecutorService executorService
  -MessageBasedResolver resolver
  +put(String app, String key, String value) boolean
  +incrementalUpdate(...) boolean
  +delete(String app, String key) boolean
  +propagateMessage(AbstractMessage message) Result
  -doSyncWithServer(AbstractMessage message, int sourceId, int fromId, int currentId) void
  -doNotifyClients(AbstractMessage message) void
  -applyMessageToStorage(AbstractMessage message) void
  +subscribe(String address, int port, String app, String key) void
  +initCluster(List~NodeMetadata~ nodes) void
}

class Overlay {
  <<interface>>
  +buildOverlay(List~NodeMetadata~ nodes) void
  +calculateNodesToSync(AbstractMessage message, NodeMetadata source, NodeMetadata from, NodeMetadata current) List~NodeMetadata~
  +calculateNodesToCollectAck(AbstractMessage message) List~NodeMetadata~
}

class HashingBasedOverlay {
  -Hashing hashing
  -List~NodeMetadata~ nodeList
}

class Hashing {
  <<interface>>
  +hashing(String app, String key, List~NodeMetadata~ nodes) List~NodeMetadata~
}

class ModHashing {
  -int count
  -int divisor
}

class Tracker {
  -Node node
  -Overlay overlay
  +initProgress(AbstractMessage message) void
  +recordAck(UUID uuid, int sourceId, int nodeId) void
  +retry() void
  +retrySending(UUID uuid) void
  -getNodesToRetry(UUID uuid) Set~Integer~
}

class HealthManager {
  -Node node
  -Map~NodeMetadata,Boolean~ aliveMap
  +init() void
  +checkHealth() void
  +isAlive(NodeMetadata node) boolean
}

class Worker {
  -Node node
  +run() void
}

class ClientDispatcher {
  <<interface>>
  +notifyClients(Set~ClientMetadata~ clients, AbstractMessage message) boolean
}

class EqualDivisionClientDispatcher {
  -Node node
  -int parts
  -averageDivide(List~ClientMetadata~ clients, int parts) List
}

class DefaultClientDispatcher {
  -Node node
}

class Storage {
  <<interface>>
  +getItemService() ItemService
  +getMessageService() MessageService
  +getAckService() AckService
  +close() void
}

class SqliteStorage

class ItemService {
  <<interface>>
  +getItem(String app, String key) Item
  +newItem(String app, String key) boolean
  +getAllItems() List~Item~
}

class MessageService {
  <<interface>>
  +newMessage(AbstractMessage message) boolean
  +exist(UUID uuid) boolean
  +getMessageByUuid(UUID uuid) AbstractMessage
  +findMessages(String app, String key) List~AbstractMessage~
}

class AckService {
  <<interface>>
  +initAck(UUID uuid, List~Integer~ nodes) boolean
  +getAck(UUID uuid) Ack
  +getAllAcks() List~Ack~
  +recordAck(UUID uuid, int serverId) boolean
}

class ClientListCache {
  -Map~String,List~ map
  +get(String signature) List
  +put(String signature, List clients) void
  +calculateSignature(List clients) String
}

class NettyServer {
  -Node node
  -List~Channel~ connectedNodes
  +start() boolean
  +connect(String address, int port) Channel
  +findChannel(String address, int port) Channel
  +sendMessage(String address, int port, Message message) boolean
}

Node o-- Overlay
Node *-- Storage
Node *-- Tracker
Node *-- HealthManager
Node *-- Worker
Node *-- ClientDispatcher
Node *-- ClientListCache
Node *-- NettyServer
Node ..> AbstractMessage : 创建并传播

Overlay <|.. HashingBasedOverlay
HashingBasedOverlay o-- Hashing
Hashing <|.. ModHashing

Tracker --> Node
Tracker --> Overlay
Tracker --> Storage : 读写 Ack
HealthManager --> Node
Worker --> Node
NettyServer --> Node

ClientDispatcher <|.. EqualDivisionClientDispatcher
ClientDispatcher <|.. DefaultClientDispatcher
EqualDivisionClientDispatcher --> ClientListCache

Storage <|.. SqliteStorage
SqliteStorage *-- ItemService
SqliteStorage *-- MessageService
SqliteStorage *-- AckService
```

要点：

- `Node` 是服务端传播的聚合根，组合了存储、Overlay、Tracker、健康检查、分发器和工作线程。
- `Node.subscription` 的实际类型是 `Map<Item, Set<ClientMetadata>>`，图中为排版简写为 `Map<Item, Set>`。
- `HashingBasedOverlay` 只在 **消息源节点** 返回其他候选副本；副本节点收到消息后返回空列表，因此不会继续扩散。
- `Tracker` 的 `initProgress` 只由消息源调用；`retry` 由 `Worker` 每 10 秒调用一次。
- `EqualDivisionClientDispatcher` 把订阅者按 `parts=3` 均分：单元素组直接发 `SYNC_REQUEST`；多元素组只把组首客户端作为入口发 `DISPATCH_REQUEST`，由它再向组内其余客户端转发。
- `SqliteStorage` 内部组合 `SqliteItemService`、`SqliteMessageService`、`SqliteAckService`；图中省略了这三个实现类。

## 3. 客户端与选服

```mermaid
classDiagram
direction LR

class RippleClient {
  -Worker worker
  -Storage storage
  -List~NodeMetadata~ nodeList
  -Map~Item,NodeMetadata~ mappingCache
  -Map~Item,NodeMetadata~ subscriptions
  -Map~NodeMetadata,Channel~ serverConnections
  -Map~ClientMetadata,Channel~ clientConnections
  -NodeSelector nodeSelector
  -ClientListCache clientListCache
  -Map~String,Queue~ pendingMessages
  -MessageBasedResolver resolver
  +put(String app, String key, String value) void
  +delete(String app, String key) void
  +incrementalUpdate(...) void
  +subscribe(String app, String key) void
  +unsubscribe(String app, String key) void
  +findOrConnectToServer(String app, String key) Channel
  -doConnect(String address, int port) Channel
  +start() boolean
  +stop() boolean
}

class NodeSelector {
  <<interface>>
  +selectNodeToConnect(String app, String key, List~NodeMetadata~ nodes) NodeMetadata
}

class HashingBasedSelector {
  -Hashing hashing
}

class LoadBalancedSelector {
  -Hashing hashing
  -RippleClient rippleClient
  -double backupRatio
  -double cpuThreshold
}

class Hashing {
  <<interface>>
  +hashing(String app, String key, List~NodeMetadata~ nodes) List~NodeMetadata~
}

class ModHashing {
  -int count
  -int divisor
}

class Worker {
  -RippleClient rippleClient
  +run() void
}

class ClientListCache {
  -Map~String,List~ map
  +get(String signature) List
  +put(String signature, List clients) void
  +calculateSignature(List clients) String
}

class Storage {
  <<interface>>
  +getItemService() ItemService
  +getMessageService() MessageService
  +getAckService() AckService
}

RippleClient o-- NodeSelector
RippleClient *-- Worker
RippleClient *-- Storage
RippleClient *-- ClientListCache
NodeSelector <|.. HashingBasedSelector
NodeSelector <|.. LoadBalancedSelector
HashingBasedSelector o-- Hashing
LoadBalancedSelector o-- Hashing
Hashing <|.. ModHashing
Worker --> RippleClient
```

要点：

- `RippleClient.findOrConnectToServer` 先用 `mappingCache` 缓存 `(app, key) -> 服务端`；未命中时调用 `NodeSelector`，再按需建立 Netty 连接。
- 默认的 `HashingBasedSelector` 先由 `ModHashing` 算出候选副本列表，再在候选中 **随机选 1 个** 作为本次发布入口。
- `LoadBalancedSelector` 会读取服务端 CPU 使用率，超过阈值时扩大候选范围。
- `RippleClient` 没有客户端侧 PUT 重试；连接断开由 `ClientMessageHandler.channelInactive` 清理，下一次 `put/subscribe` 再惰性重连。

## 4. 网络协议与处理器

```mermaid
classDiagram
direction LR

class Message {
  -MessageType type
  -UUID uuid
}

class PutRequest {
  -String applicationName
  -String key
  -String value
}

class PutResponse {
  -boolean success
}

class SyncRequest {
  -UUID messageUuid
  -String operationType
  -String applicationName
  -String key
  -UUID baseMessageUuid
  -String atomicOperation
  -String value
  -Date lastUpdate
  -int lastUpdateServerId
  -int fromId
}

class SyncResponse {
  -Result result
}

class DispatchRequest {
  -String clientListSignature
  -UUID messageUuid
  -String operationType
  -String applicationName
  -String key
  -UUID baseMessageUuid
  -String atomicOperation
  -String value
  -Date lastUpdate
  -int lastUpdateServerId
}

class DispatchResponse {
  -boolean success
}

Message <|-- PutRequest
Message <|-- PutResponse
Message <|-- SyncRequest
Message <|-- SyncResponse
Message <|-- DispatchRequest
Message <|-- DispatchResponse

class Handler {
  <<interface>>
  +handle(ChannelHandlerContext ctx, Message message) Message
}

class MessageHandler {
  -Map~MessageType,Handler~ handlers
  +channelRead0(ChannelHandlerContext ctx, Message message) void
  +registerHandler(MessageType type, Handler handler) void
}

class ServerMessageHandler
class PutRequestHandler {
  -Node node
}
class SyncRequestHandler {
  -Node node
}
class SyncResponseHandler {
  -Node node
}
class DispatchResponseHandler {
  -Node node
}
class AckRequestHandler {
  -Node node
}

MessageHandler <|-- ServerMessageHandler
Handler <|.. PutRequestHandler
Handler <|.. SyncRequestHandler
Handler <|.. SyncResponseHandler
Handler <|.. DispatchResponseHandler
Handler <|.. AckRequestHandler
MessageHandler *-- Handler
PutRequestHandler --> Node : put()
SyncRequestHandler --> Node : propagateMessage()
SyncResponseHandler ..> SyncResponse : 只打印日志
AckRequestHandler --> Node : tracker.recordAck()

class NettyServer
class ServerChannelInitializer
NettyServer --> ServerChannelInitializer : 装配 pipeline
ServerChannelInitializer ..> MessageHandler
ServerChannelInitializer ..> MessageEncoder
ServerChannelInitializer ..> MessageDecoder
```

要点：

- `PutRequest.uuid` 是 **请求关联 UUID**；`Node.put()` 会新建 `UpdateMessage`，其 `uuid` 是 **消息 UUID**，两者不是同一个值。
- `SyncRequest.uuid` 是本次同步请求的关联 UUID；`SyncRequest.messageUuid` 才是原消息的 UUID。
- `MessageHandler.channelRead0` 按 `MessageType` 找到 `Handler`；`Handler.handle` 返回非 `null` 时，Netty 自动写回响应。
- `SyncResponseHandler` 在服务端和客户端都只打印日志并返回 `null`；`SYNC_RESPONSE` 不参与业务逻辑，也不更新 ACK。
- `NettyServer` 的 pipeline 由 `ServerChannelInitializer` 装配：长度帧解码、长度帧编码、`MessageEncoder`、`MessageDecoder`、`ServerMessageHandler`。
- 当前 HEAD 的 V1/V2 开关只改线格式，不改上面的对象关系：`TypeHelper.isCompactWire()` 把 UUID 从 40 B 文本改为 16 B 二进制，并把同步操作类型压成 1 B；`PayloadCodec` 对 `SYNC_REQUEST`/`DISPATCH_REQUEST` 的 value 做自适应 Deflate。默认关闭；`PUT_REQUEST` 不压缩。

## 5. 一次 PUT 的对象协作时序

```mermaid
sequenceDiagram
  autonumber
  actor P as 发布者
  participant RC as RippleClient
  participant SA as 服务端 A / Node
  participant ST as Storage
  participant TR as Tracker
  participant CD as ClientDispatcher
  participant SB as 副本 B
  participant SC as 副本 C
  participant SUB as 订阅者客户端

  P->>RC: put(app, key, value)
  RC->>RC: findOrConnectToServer(app, key)
  RC->>SA: PUT_REQUEST(uuid, app, key, value)
  SA->>SA: PutRequestHandler.handle()
  SA->>SA: Node.put(): new UpdateMessage(UUID.randomUUID())
  SA->>ST: exist(message.uuid)
  ST-->>SA: false
  SA->>ST: newItem(app, key) + newMessage(message)
  SA->>TR: initProgress(message)
  TR->>ST: initAck(uuid, 候选副本列表)
  SA->>CD: doNotifyClients(message)
  CD->>SUB: SYNC_REQUEST（单订阅者）
  SA-)SB: 异步 SYNC_REQUEST
  SA-)SC: 异步 SYNC_REQUEST
  SA->>TR: recordAck(uuid, B/C)
  SA-->>RC: PUT_RESPONSE(success)
  Note over SA,RC: PUT 响应只代表本地落库并已提交异步同步
  Note over SA,TR: recordAck 在异步 doSyncWithServer 内，与 PUT_RESPONSE 无严格先后

  SB->>SB: SyncRequestHandler -> propagateMessage()
  SB->>SB: 落库 + 通知本地订阅者
  SB-->>SA: SYNC_RESPONSE
  SC-->>SA: SYNC_RESPONSE

  SUB->>SUB: SyncRequestHandler.applyMessage()
  SUB-->>SA: SYNC_RESPONSE
  Note over SA: SyncResponseHandler 只打印日志，不更新 Ack
```

时序中的关键事实：

1. `PUT_RESPONSE` 在 `Node.put` 返回后发出；此时服务端间同步是异步任务，可能尚未完成。
2. `Tracker.initProgress` 在消息源初始化 ACK 目标；`doSyncWithServer` 在每次 `Api.sync` 写出后立刻 `recordAck`，并不等待对端真正处理完。
3. 哈希 Overlay 下，副本 B/C 的 `calculateNodesToSync` 返回空列表，所以它们只落库和通知本地订阅者，不会继续向其他副本扩散。
4. 单订阅者时服务端直接发 `SYNC_REQUEST`；多订阅者时按 `parts=3` 均分，组首客户端收 `DISPATCH_REQUEST` 并负责组内转发，单元素组直接收 `SYNC_REQUEST`。
5. `SYNC_RESPONSE` 在这条链路里只产生日志流量，可以作为后续协议裁剪对象。

## 6. 对象与线上字节的对应关系

以下为 `bandwidth_test` 在 1024 B、3 服务端、1 订阅者、不限速场景下的观测值；包含 TCP/IP 和抓包点开销，不是单纯的对象字段大小。

| 对象/环节 | 线上消息 | 约每消息帧字节 | 说明 |
| --- | --- | ---: | --- |
| 发布者 → 服务端 | `PUT_REQUEST` | 1,165 B | `uuid + app + key + value` |
| 服务端 → 副本 2 | `SYNC_REQUEST` | 1,231 B | 完整 value 再传一份 |
| 服务端 → 副本 3 | `SYNC_REQUEST` | 1,231 B | 完整 value 再传一份 |
| 服务端 → 订阅者 | `SYNC_REQUEST` | 1,231 B | 单订阅者路径 |
| 服务端 → 发布者 | `PUT_RESPONSE` | 46 B 级 | 只含成功标志 |
| 副本/订阅者 → 服务端 | `SYNC_RESPONSE` × 3 | 约 337 B 合计 | 只用于日志 |
| 其他 | 心跳、ACK、TCP 控制等 | 约 450 B | 随运行时间变化 |

结论：在当前 1024 B、3 副本场景中，主要带宽不是对象头，而是 **同一份 value 被完整发送了 4 次**（1 次 PUT + 2 次副本同步 + 1 次订阅下行）。因此对象级优化应优先减少复制份数或复制范围，其次才是压缩 `UUID`、字符串和响应消息。

## 7. 源码入口

- [Node.java](../Ripple/ripple-server/src/main/java/ripple/server/core/Node.java#L350-L420)
- [Node.java 的 doSyncWithServer](../Ripple/ripple-server/src/main/java/ripple/server/core/Node.java#L442-L473)
- [Tracker.java](../Ripple/ripple-server/src/main/java/ripple/server/core/Tracker.java)
- [HashingBasedOverlay.java](../Ripple/ripple-server/src/main/java/ripple/server/core/overlay/hashing/HashingBasedOverlay.java)
- [EqualDivisionClientDispatcher.java](../Ripple/ripple-server/src/main/java/ripple/server/core/dispatcher/EqualDivisionClientDispatcher.java)
- [RippleClient.java](../Ripple/ripple-client/src/main/java/ripple/client/RippleClient.java)
- [PutRequestHandler.java](../Ripple/ripple-server/src/main/java/ripple/server/tcp/handler/PutRequestHandler.java)
- [SyncRequestHandler.java](../Ripple/ripple-server/src/main/java/ripple/server/tcp/handler/SyncRequestHandler.java)
- [SyncResponseHandler.java](../Ripple/ripple-server/src/main/java/ripple/server/tcp/handler/SyncResponseHandler.java)
- [SyncRequestEncoder.java](../Ripple/ripple-common/src/main/java/ripple/common/tcp/encoder/SyncRequestEncoder.java)
