# Ripple 带宽优化开发日志

**对照基线：** GitHub 上游 `ISCAS-SSG/Ripple` 的原始归档提交 `468e9cb`（`bandwidth-v0-original`）。**开发分支：** `v2.1`。以下按提交顺序记录相对该基线的改动；后续每次修改在末尾追加，记录提交号、涉及的类与方法、设计和验证结果。

## 1. 紧凑 UUID 与同步操作码 — `7c308d2`

- **`TypeHelper.writeUuid/readUuid`**：集中处理 UUID 线格式。紧凑模式把 `4 B 长度 + 36 B 文本` 改成两个 `long`，每个 UUID 从 40 B 缩到 16 B。已有调用者共用此规则，消息对象仍使用 `UUID`。
- **`SyncRequestEncoder.encode` / `SyncRequestDecoder.decode`**：将同步操作名 `update`、`delete`、`incremental_update` 映射为单字节 `1`、`2`、`3`，解码后恢复原操作名。消息对象和业务处理器沿用原字段。
- **设计与验证**：将 UUID 的公共表示放在 `TypeHelper`，将同步请求特有的操作码放在对应编解码器。普通同步请求少 **57 B**，增量同步请求少 **93 B**。`CompactWireTest` 验证旧格式字节与紧凑格式往返。

## 2. 连接表与通道查找 — `ce6b78f`

- **`NettyServer.connectedNodes` / `findChannel`**：连接表改用 `CopyOnWriteArrayList`；查找时先筛选活动且具有有效网络地址的通道，再按 IP 或主机名与端口匹配。
- **设计与验证**：并发遍历和通道筛选统一由传输层负责。`NettyServerTest` 验证连接表遍历和地址匹配。这一项调整连接管理，帧格式不变。

## 3. 帧长与消息类型位打包 — `8b88842`

- **`PackedFrame` / `PackedFrameDecoder.decode`**：把 4 B 长度和 1 B 消息类型合并到 4 B 头，布局为 `[7 bit 保留 | 5 bit 类型 | 20 bit 帧体长度]`。拆帧器从低 20 位取长度，保持 1 MiB 整帧上限。
- **`MessageEncoder.encode` / `MessageDecoder.decode`**：在头部写入、读取消息类型；客户端和服务端的通道初始化器共用 `PackedFrame.configure`。
- **设计与验证**：位布局、TCP 拆帧和业务字段编解码分开。开启 `ripple.wire.packedFrame` 后，每帧在紧凑编码基础上再少 **1 B**。测试覆盖字节对照、拆包、粘包和帧头校验。

## 4. 正文自适应压缩与帧头标记 — `8d0e6dc`

- **`PayloadCodec.write/readCompressed`**：封装 UTF-8 正文与 raw DEFLATE 的转换，使用 `Deflater.BEST_SPEED`。从 512 B 起尝试压缩，计入额外的 4 B 原文长度后仍更短才采用压缩。
- **`SyncRequestEncoder.encodePacked` / `SyncRequestDecoder.decodePacked`**：普通同步更新的 `value` 走压缩读写；编码端返回本帧是否压缩，接收端依据帧头标志恢复原字符串。删除、增量更新及其他消息仍按各自的原有格式处理。
- **`PackedFrame` / `MessageEncoder` / `MessageDecoder`**：第 25 位标记当前帧的正文是否压缩，帧头继续占 4 B。标志为 `0` 时写 `[原文长度][原文]`，为 `1` 时写 `[压缩长度][原文长度][压缩数据]`。启用配置为 `ripple.wire.frameCompression`，与打包帧头配合使用。
- **设计与验证**：压缩状态随帧传递，不写入业务对象。`mvn test` 共通过 18 个测试；应用层编码对照覆盖 32–16384 B。1024 B 正文下，重复结构文本从 **1098 B 降至 125 B**，随机可打印 ASCII 从 **1098 B 降至 950 B**（均与同配置下关闭正文压缩对比）。
