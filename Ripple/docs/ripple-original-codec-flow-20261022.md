# Ripple 原版：一条字符串如何编码、传输、解码

依据原版标签 `bandwidth-v0-original`，提交 `468e9cb4296110467e3cfdafed412b3dbecfd52a`。下文不使用优化版的二进制 UUID 或正文压缩。

拓扑：一个发布者、一个服务端、一个订阅者；订阅已完成，连接已建立。只分析普通写入 `update`，不混入删除、增量更新和多订阅者转发。

## 1. 画图用的主线

```text
发布者的字符串
    ↓ 放进 PUT 请求：请求编号＋应用名＋键＋正文
PUT 编码器：各字段按顺序写成字节
    ↓ 在前面加 4 B 帧长度
网络传输：发布者 → 服务端
    ↓ 按帧长度取出完整消息，再按字段顺序解码
服务端恢复原文并保存
    ↓ 生成业务消息编号、更新时间和节点编号
    ↓ 另建一个 SYNC 请求，生成新的同步请求编号
SYNC 编码器：各字段按顺序写成字节
    ↓ 在前面加 4 B 帧长度
网络传输：服务端 → 订阅者
    ↓ 按帧长度取出完整消息，再按字段顺序解码
订阅者恢复原文，处理收到的数据，例如更新页面
```

同一个正文经过两次编码、两次解码。服务端不是把收到的 PUT 字节原样转发，而是构造字段更多的 SYNC 消息。

## 2. 字段的长度由谁决定

`1 B = 8 bit`。这里的位宽是线上编码占用，不能直接用 Java 对象在内存中的大小代替。

| 字段种类 | 原版写法 | 线上长度 | 长度如何确定 |
| --- | --- | --- | --- |
| 整帧长度 | `LengthFieldPrepender(4)` | 4 B／32 bit | 协议固定；数值是后续消息体的字节数，不包含这 4 B 自身 |
| 消息类型 | `writeByte(type)` | 1 B／8 bit | 协议固定；PUT=10，SYNC=4 |
| 字符串 | `writeInt(N)`＋`writeBytes(bytes)` | 4＋N B／32＋8N bit | 先转 UTF-8，N 是编码后的字节数 |
| UUID | `writeString(uuid.toString())` | 40 B／320 bit | 标准 UUID 文本 36 个 ASCII 字符，再加 4 B 长度 |
| 更新时间 | `writeLong(date.getTime())` | 8 B／64 bit | 协议固定；内容是 Unix 纪元起的毫秒数 |
| 节点编号 | `writeInt(id)` | 4 B／32 bit | 协议固定；编号即使是 1，也占 4 B |
| 布尔／结果码 | `writeByte(...)` | 1 B／8 bit | 协议固定；不会按 Java 对象大小发送 |

整数采用大端顺序：高位字节在前。例如长度 9 写成十六进制 `00 00 00 09`。长度字段本身永远是 4 B，长度数值变小不会自动减少该字段的字节数。

字符串长度取决于内容，而非字符个数：ASCII 字符通常 1 B，本例中的汉字每个 3 B。例如 `"温度=23"` 有 5 个字符，但 UTF-8 编码后为 **9 B**。

UUID 的标识值是 128 bit，但原版选择转成带连字符的文本再发送，因此实际占 **320 bit**。这两者不能混为一谈。

## 3. 第一段：发布者 → 服务端（PUT）

取一个便于画图的例子：

```text
应用名 app = "demo"          → UTF-8：4 B
数据键 key = "temperature"  → UTF-8：11 B
正文 value = "温度=23"       → UTF-8：9 B
```

字段严格按下列顺序发送；偏移从 0 开始，包含最前面的帧长度：

| 偏移（字节） | 字段 | 示例或含义 | 占用 |
| --- | --- | --- | ---: |
| 0–3 | 帧长度 | 后续消息体长 77，十六进制 `00 00 00 4D` | 4 B |
| 4 | 消息类型 | PUT_REQUEST，数值 10 | 1 B |
| 5–44 | PUT 请求 UUID | 4 B 长度值 36＋36 B UUID 文本 | 40 B |
| 45–52 | 应用名 | 4 B 长度值 4＋`demo` | 8 B |
| 53–67 | 键 | 4 B 长度值 11＋`temperature` | 15 B |
| 68–80 | 正文 | 4 B 长度值 9＋`温度=23` 的 UTF-8 字节 | 13 B |
| — | **完整 PUT 帧** | **包含最前面的 4 B 长度** | **81 B／648 bit** |

画字段条时可直接使用：

```text
PUT：共 81 B
[帧长4][类型1][请求UUID40][应用名8][键15][正文13]
```

这里没有更新时间、业务消息 UUID、节点编号；它们是服务端处理写入后才产生的。

通用公式：设应用名、键、正文的 UTF-8 字节数分别是 A、K、V：

```text
PUT 总长 = 4 + 1 + 40 + (4+A) + (4+K) + (4+V)
          = 57 + A + K + V 字节
```

## 4. 服务端中间做了什么

1. 从 PUT 解码出应用名、键和原文。
2. `Node.put` 获取当前毫秒时间，并使用当前服务端编号。
3. 创建 `UpdateMessage`，生成新的业务消息 UUID，保存到本地。
4. 通知订阅者时，`Api.sync` 再生成一个同步请求 UUID，并把业务消息 UUID、操作类型、时间等放入 SYNC 请求。

因此有三种编号：**PUT 请求编号、业务消息编号、SYNC 请求编号**。它们都用 UUID 表示，但含义不同，不是同一个编号一直沿用。每个响应使用对应请求的编号，以便关联请求与响应。

## 5. 第二段：服务端 → 订阅者（SYNC）

正文仍是同一份 `温度=23`。普通写入操作类型是字符串 `"update"`，6 B ASCII，再加 4 B 长度，因此共 10 B。

| 偏移（字节） | 字段 | 示例或含义 | 占用 |
| --- | --- | --- | ---: |
| 0–3 | 帧长度 | 后续消息体长 143，十六进制 `00 00 00 8F` | 4 B |
| 4 | 消息类型 | SYNC_REQUEST，数值 4 | 1 B |
| 5–44 | SYNC 请求 UUID | 新生成的请求编号，含字符串长度 | 40 B |
| 45–84 | 业务消息 UUID | 服务端生成的业务消息编号，含字符串长度 | 40 B |
| 85–94 | 操作类型 | 4 B 长度值 6＋`update` | 10 B |
| 95–102 | 应用名 | 4 B 长度值 4＋`demo` | 8 B |
| 103–117 | 键 | 4 B 长度值 11＋`temperature` | 15 B |
| 118–130 | 正文 | 4 B 长度值 9＋原文 UTF-8 字节 | 13 B |
| 131–138 | 更新时间 | 服务端生成的毫秒时间戳 | 8 B |
| 139–142 | 最后更新服务端编号 | `lastUpdateServerId` | 4 B |
| 143–146 | 来源节点编号 | `fromId` | 4 B |
| — | **完整 SYNC 帧** | **包含最前面的 4 B 长度** | **147 B／1176 bit** |

```text
SYNC：共 147 B
[帧长4][类型1][请求UUID40][业务UUID40][操作10]
[应用名8][键15][正文13][时间8][更新节点4][来源节点4]
```

通用公式（仅普通 `update`）：

```text
SYNC 总长 = 123 + A + K + V 字节
比 PUT 多 = 业务UUID40 + 操作10 + 时间8 + 两个节点编号8
          = 66 字节
```

应用名、键相同，正文改为 1024 B 时：PUT 为 **1096 B**，SYNC 为 **1162 B**。这组值对应本例 `demo` 和 `temperature`；应用名或键的长度不同，总长也会变化。

## 6. 接收方怎么知道每段多长

接收端不靠分隔符猜字段边界，而是依次执行：

```text
① 读最前面的 4 B → 知道一整条消息还需要多少字节
② 缓存直到完整帧到齐 → 去掉这 4 B 长度
③ 读 1 B 类型 → 选择 PUT 或 SYNC 解码器
④ 按编码时相同的顺序读取字段
   字符串：读 4 B 长度 N → 再读 N B → 按 UTF-8 还原
   UUID：按字符串读取 → UUID.fromString(...)
   时间：直接读 8 B → new Date(...)
   节点编号：各读 4 B
⑤ 恢复消息对象 → 交给对应处理器
```

Netty 配置为 `LengthFieldBasedFrameDecoder(1024 * 1024, 0, 4, 0, 4)`：长度字段在偏移 0，占 4 B，解码时去掉这 4 B，完整帧上限为 1 MiB。32 bit 长度字段的表示范围不等于允许发送的最大帧长。

TCP 提供字节流；一条 Ripple 帧可以分多次到达，多条帧也可以一起到达。帧长度字段用于恢复消息边界，不能把“一条 Ripple 消息”直接等同于“一个 TCP 包”。

## 7. 图上另画的回复与网络头

普通成功路径还包括两条反向回复，每条 **46 B**：

```text
服务端 → 发布者：PUT_RESPONSE
[帧长4][类型1][对应PUT请求UUID40][成功标记1] = 46 B

订阅者 → 服务端：SYNC_RESPONSE
[帧长4][类型1][对应SYNC请求UUID40][结果码1] = 46 B
```

本例四条应用帧合计 `81 + 147 + 46 + 46 = 320 B`，不含订阅建立、心跳、重试及 TCP/IP 等开销，也不代表四条消息必定按上述书写顺序完成。

画图建议把 TCP/IP 等网络头放在 Ripple 帧外面，标注“由网络栈添加，大小取决于协议、选项和分段”。不要给每个 Ripple 帧机械加一个固定的网络头长度；本文件的精确字节数均止于应用协议层。

## 8. 原版代码核对位置

以下均为标签 `bandwidth-v0-original` 下的路径；当前工作树的同名文件可能已包含优化。

| 内容 | 源码路径 |
| --- | --- |
| 字符串、UUID 的原始编码 | `ripple-common/src/main/java/ripple/common/helper/TypeHelper.java` |
| PUT 字段顺序 | `ripple-common/src/main/java/ripple/common/tcp/encoder/PutRequestEncoder.java` |
| PUT 解码 | `ripple-common/src/main/java/ripple/common/tcp/decoder/PutRequestDecoder.java` |
| SYNC 字段顺序 | `ripple-common/src/main/java/ripple/common/tcp/encoder/SyncRequestEncoder.java` |
| SYNC 解码 | `ripple-common/src/main/java/ripple/common/tcp/decoder/SyncRequestDecoder.java` |
| 类型编码和解码器选择 | `ripple-common/src/main/java/ripple/common/tcp/MessageType.java`、`MessageEncoder.java`、`MessageDecoder.java` |
| 帧长度的添加和移除 | `ripple-server/src/main/java/ripple/server/tcp/ServerChannelInitializer.java`、`ripple-client/src/main/java/ripple/client/core/tcp/ClientChannelInitializer.java` |
| 生成时间、保存与通知 | `ripple-server/src/main/java/ripple/server/core/Node.java` |
| 业务消息 UUID 生成 | `ripple-common/src/main/java/ripple/common/entity/UpdateMessage.java` |
| 创建同步请求 | `ripple-server/src/main/java/ripple/server/helper/Api.java` 的 `sync` |
| 回复格式 | `ripple-common/src/main/java/ripple/common/tcp/encoder/PutResponseEncoder.java`、`SyncResponseEncoder.java` |

查看任意原版文件：`git -C Ripple show bandwidth-v0-original:上述路径`。
