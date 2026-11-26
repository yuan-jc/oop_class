# Ripple 新阶段提案：冲突合并策略的抽象、聚合度优化、可靠测试

**定位：** 本阶段不复用 v0/v1/v2 带宽数据，面向"面向对象思想 × 关键问题 × 优美解法"。
**基线源码：** `oop/Ripple/Ripple/`（内嵌工作副本）
**对照课程：** 第8课（信息隐藏·高内聚低耦合·单一职责·Parnas）、第9课（组合继承多态）、第10课（抽象类·接口·多态·防御方法）

三条主线，各自是一个"关键问题 → OO 抽象 → 优美解法"的闭环：

- 问题一：**合并语义被写死成 Last-Write-Wins**，无法应对"严格次序""新值覆盖旧值""增长型合并"等多种业务需求 → 用**接口 + 抽象基类 + 多态**做分层抽象。
- 问题二：**`Node`/`RippleClient` 聚合度过低（上帝类）** → 仿课程温度控制例子做职责分离。
- 问题三：**测试载荷单一、可靠性不足** → 用**策略化的载荷生成器 + 不变式校验**做可靠测试。

---

## 问题一　把"合并假设"从写死变成可插拔的策略层次

### 1.1 关键问题（PPT 假设 → 现实落差）

第9/10课反复讲"用接口建模弱是关系、用多态隔离可变行为"。Ripple 现状恰好违背了这一点：**整个系统只有一种合并语义，而且被 `LastWriteWinsResolver` 写死**。

现有唯一接口（已核源码 `ripple-common/.../resolver/`）：
```java
public interface MessageBasedResolver {
    void merge(Item current, List<AbstractMessage> history);
}
```
唯一实现 `LastWriteWinsResolver.merge()` 做的事：
```java
messages.sort((a,b) -> (int)(b.getLastUpdate().getTime() - a.getLastUpdate().getTime())); // 按物理时间倒序
AbstractMessage wins = messages.get(0);   // 时间最大者即赢家 —— 这就是"新值覆盖旧值"的硬编码假设
```

三个问题点,都是可演示的真实缺陷：
1. **仲裁维度写死为 `lastUpdate`（墙上时钟）。** 跨节点时钟漂移时，"新值覆盖旧值"会选错赢家；系统里其实已有 `HybridLogicalClock`（`server.core.hlc`）却没被 resolver 使用——**现成的因果序基础设施被闲置**。
2. **无法表达"严格按次序"。** 乱序到达的消息，LWW 直接按时间挑最大，不检查前驱是否到齐；没有"必须顺序提交"的选项。
3. **合并策略是全局单例，不能按 Key/应用切换。** `Node`/`RippleClient` 构造时写死 `setResolver(new LastWriteWinsResolver())`，一个集群只能有一种语义。

### 1.2 优美解法：三层抽象阶梯（接口 → 抽象基类 → 具体策略）

照第10课"接口定义行为、抽象类沉淀公共实现、子类给出差异"的阶梯，把"如何挑选/合并版本"做成可替换策略。**保持 `MessageBasedResolver` 接口签名不变**（它已被 4 处调用，是稳定扩展点），在其下建抽象层。

**第 1 层——接口（已存在，不动）：** `MessageBasedResolver.merge(Item, List<AbstractMessage>)`
> 对应 L10"接口将使用者与实现者解耦"：4 个调用点（`Node.getWithValue`、`GetRequestHandler`、两个 `GetConfigServlet`）只认接口。

**第 2 层——新增抽象基类，沉淀公共骨架（模板方法）：**
```java
// 新增 ripple-common/.../resolver/AbstractOrderedResolver.java
public abstract class AbstractOrderedResolver implements MessageBasedResolver {
    @Override
    public final void merge(Item current, List<AbstractMessage> history) {   // 模板方法：固定流程
        if (history == null || history.isEmpty()) { current.setValue(null); return; }
        List<AbstractMessage> ordered = sort(history);        // ① 排序维度   —— 子类定制
        AbstractMessage winner = select(ordered);             // ② 选赢家     —— 子类定制
        apply(current, winner, ordered);                      // ③ 落值       —— 子类定制
    }
    protected abstract List<AbstractMessage> sort(List<AbstractMessage> history);
    protected abstract AbstractMessage select(List<AbstractMessage> ordered);
    protected abstract void apply(Item current, AbstractMessage winner, List<AbstractMessage> ordered);
}
```
> 对应 L10"抽象类沉淀公共实现、把变化点留给子类"，`merge` 设为 `final` = 固定三步流程不被破坏（信息隐藏，L8）。

**第 3 层——具体策略（多态）：**

| 具体类 | sort 维度 | select 规则 | apply 行为 | 对应业务情况 |
|---|---|---|---|---|
| `LastWriteWinsResolver`（重构为继承基类） | 墙上时钟 `lastUpdate` 倒序 | 取第一个 | 覆盖/删除/增量合并（保留原逻辑） | **新值覆盖旧值** |
| `CausalOrderResolver`（新增） | 按 `HybridLogicalClock` 因果序 | 取因果最新且前驱齐备者 | 覆盖 | 跨节点时钟漂移下的**正确"最新"** |
| `StrictSequenceResolver`（新增） | 按 `(sourceId, 序号)` 升序 | 必须连续、缺口则停在缺口前 | 顺序回放到最后一个连续版本 | **必须严格按次序** |
| `GrowOnlyResolver`（新增，可选） | 不排序 | 全集 | 并集/累加（CRDT 风格，幂等可交换） | **增长型、不丢历史** |

> 对应 L9 多态："一个 `MessageBasedResolver` 名字在运行时表现不同子类行为"；对应 L10 "strong is-a 用继承、弱 is-a 用接口"——四种 resolver 是 `AbstractOrderedResolver` 的强 is-a，用继承；`MessageBasedResolver` 是弱 is-a（能力），用接口。

### 1.3 让策略可按情况灵活切换（工厂 + 配置，消除写死）

现状写死：`Node.java:315` / `RippleClient.java:126` 直接 `new LastWriteWinsResolver()`。
**新增 `ResolverFactory`**，把"选哪种语义"从编译期决定改为运行期配置（呼应结构分析里"全仓无配置化加载"的批评）：
```java
// 新增 ripple-common/.../resolver/ResolverFactory.java
public final class ResolverFactory {
    public static MessageBasedResolver fromConfig() {              // 读 ripple.resolver.policy
        switch (System.getProperty("ripple.resolver.policy", "lww")) {
            case "causal":  return new CausalOrderResolver();
            case "strict":  return new StrictSequenceResolver();
            case "grow":    return new GrowOnlyResolver();
            default:        return new LastWriteWinsResolver();
        }
    }
}
```
`Node`/`RippleClient` 的两处 `new LastWriteWinsResolver()` 改为 `ResolverFactory.fromConfig()`。因为 `setResolver(...)` 已存在，也支持测试时注入。

### 1.4 具体改动清单（对象 / 方法 / 思路）

| 动作 | 文件 | 方法/成员 | 思路 |
|---|---|---|---|
| 新增抽象基类 | `resolver/AbstractOrderedResolver.java` | `final merge()` + 三个抽象方法 | 模板方法固定流程，变化点下放 |
| 重构 | `resolver/LastWriteWinsResolver.java` | 实现 `sort/select/apply` | 行为不变，只是落入新框架 |
| 新增 | `resolver/CausalOrderResolver.java` | 用 `HybridLogicalClock.smallerThan` | 激活闲置的 HLC 基础设施 |
| 新增 | `resolver/StrictSequenceResolver.java` | 按序号连续性 select | 支持"严格次序" |
| 新增（可选） | `resolver/GrowOnlyResolver.java` | 幂等并集 | 支持"增长型、不丢" |
| 新增 | `resolver/ResolverFactory.java` | `fromConfig()` | 消除写死、配置化 |
| 改 | `server/core/Node.java:315`、`client/RippleClient.java:126` | 构造处改用工厂 | 两行改动 |
| 测试 | `resolver/*ResolverTest.java` | 每种策略一组用例 | 见问题三 |

**带宽关联点（让这条线也落到 3.3）：** `StrictSequenceResolver` 确立"只需保留最后一个连续版本"后，可安全丢弃被覆盖的中间全量 Value —— 这正是语义层"减小同步数据量"的依据，且与数据可压缩性无关。

---

## 问题二　聚合度分析与优化（仿课程方法）

### 2.1 课程的分析方法（第8课温度控制例子）

第8课用智慧家居温度控制演示聚合：最初"加热器负责维持固定温度"职责混杂，重构为**温度传感器 / 加热器 / 温度控制器 / 温度计划 / 计划执行器**五个各自内聚的抽象——"关注点分离：不让加热器负责维持温度，而把该职责交给温度控制器"。判据是"有特定关系的信息尽量在一个模块内""每个模块仅暴露必要接口"。

### 2.2 用同一方法量 Ripple 的聚合度

沿用 `reports/java-structure` 已算的 Martin 指标口径（Ca/Ce/I），聚焦两个上帝类：

| 对象 | 行数 | 混在一起的职责（= 低聚合证据） | 类比温度例子 |
|---|---:|---|---|
| `server.core.Node` | 624 | 生命周期、线程 `Worker`、Netty 收发、HTTP `registerServlet`×10、存储、Overlay、Tracker、ACK、resolver 构造 | 相当于"加热器同时管传感、计划、执行" |
| `client.RippleClient` | 598 | 同上客户端版 | 同 |

**低聚合的具体表现（可在报告截图）：** `Node.registerHandlers()` 里一次性 `new` 了 10 个 Servlet 并注册 HTTP 路由——网络核心对象直接知道 UI 的存在，职责跨层。这正是"信息没有尽量留在一个模块内"。

### 2.3 优美解法：按职责切出内聚协作者（组合优先于继承，L9）

仿温度控制的拆法，把 `Node` 的职责分给内聚对象，`Node` 退化为**协调者（持有引用、编排流程）**，不再自己干活：

| 新抽象 | 单一职责 | 从 Node 搬走的内容 | 对应温度例子角色 |
|---|---|---|---|
| `NodeLifecycle` | 启停、线程、端口 | start/stop/Worker | 计划执行器 |
| `ReplicationCoordinator` | 复制/推送编排 | propagateMessage/SYNC | 温度控制器 |
| `MessageApplier` | 收到消息如何落库+合并 | getWithValue/apply + resolver 调用 | 温度控制器 |
| `HttpEndpoints` | 注册所有 Servlet | registerHandlers 的 10 行 | （UI 边界，与核心解耦） |

> 对应 L9"组合优先"：`Node` 用组合持有这些协作者，而不是自己继承一堆能力；对应 L8"最小化耦合，只依赖公开接口"——把 `HttpEndpoints` 抽出后，核心对象不再 import `HttpServlet` 包，可打破结构分析里指出的 UI↔核心循环依赖环。

**范围控制（工程判断，写进报告）：** `Node` 全拆风险高（624 行、循环依赖中心）。建议**只实实在在拆 `HttpEndpoints` 一项**（低风险、直接破环、可量化 Ce 下降），其余三项作为"分析到位、权衡后暂不动核心"的记录——满足大作业"记录未采用思路及原因"。

### 2.4 优化前后的可量化指标（报告用）

拆出 `HttpEndpoints` 后，用 `reports/java-structure/analysis.py` 重算，预期：
- `Node` 的 Ce（依赖数）下降（不再依赖 10 个 Servlet 类）；
- server 侧 17 类循环依赖块缩小（UI↔核心的边被切断）；
- 给出一张"重构前/后 Ca·Ce·I 对照表" + 依赖热力图差异，呼应第8课"依赖分析"。

---

## 问题三　让测试更可靠：多长度 × 多文本 × 不变式校验

### 3.1 关键问题

现有测试（无论外层还是 bundle 版）载荷偏单一，判"收敛"曾依赖 HTTP 页面轮询（脆弱，之前触发过 NPE 误判）。可靠性不足体现在：载荷类型少、长度单一、正确性只看"收到"不看"内容对不对、不覆盖新的 resolver 语义。

### 3.2 优美解法：策略化载荷生成 + 不变式断言

**① 载荷生成器做成策略接口（L10 接口 + L9 多态）：**
```java
// 测试侧 ripple-common/src/test/.../PayloadGenerator.java
public interface PayloadGenerator {
    String next(int sequence);
    String name();
}
```
实现族（与带宽实验的三类载荷一致，保证可对照）：

| 实现 | 文本特征 | 覆盖的边界 |
|---|---|---|
| `StructuredTextPayload` | 重复 JSON/YAML 式（高可压） | 压缩收益上限 |
| `RandomBytesPayload` | 高熵随机（不可压） | 压缩收益下限、紧凑编码仍有效 |
| `SmallControlPayload` | 极短（< 64 B） | 控制流量、UUID 占比 |

**② 长度矩阵参数化：** 1 KiB / 16 KiB / 256 KiB × 上述三类 = 9 组，用 JUnit 参数化跑。

**③ 用"不变式"断言替代"看页面"（可靠性核心）：**
- **内容不变式**：收端按 `(seed, sequence)` 重算原文，逐条比对 UTF-8 字节与 SHA-256（你弱网实验已用过这招，提炼成通用断言）。
- **合并语义不变式**（配合问题一）：
  - LWW：最终值 == 时间戳最大的那条；
  - Strict：缺口前的最后一个连续版本；
  - GrowOnly：结果为所有增量的并集，且**与到达顺序无关**（打乱 history 顺序 merge 两次，结果相等 = 幂等可交换）。
- **幂等性不变式**：同一 history 调 `merge` 两次，`Item.value` 不变。

### 3.3 具体改动清单

| 动作 | 文件 | 思路 |
|---|---|---|
| 新增 | `test/.../PayloadGenerator.java` + 3 实现 | 策略模式，载荷可插拔 |
| 新增 | `test/.../ResolverContractTest.java` | 对每种 resolver 跑同一组不变式（面向接口测试） |
| 新增 | `test/.../PayloadMatrixTest.java` | 3 文本 × 3 长度参数化 |
| 复用 | 弱网逐条 SHA-256 校验 | 提炼为 `MessageIntegrity.assertExact(...)` |

> 对应 L10"面向接口编程"：`ResolverContractTest` 只依赖 `MessageBasedResolver`，任何新策略加进来自动套用同一批不变式——测试本身也是解耦的。

---

## 三条线的统一主张（研讨主线句）

> "Ripple 把两类'假设'写死在了代码里：合并语义写死成 Last-Write-Wins，核心职责写死在 Node 上帝类里。我用第10课的抽象阶梯（接口→抽象基类→多态策略）把合并语义变成可按情况切换的 resolver 层次，覆盖'新值覆盖''严格次序''增长型'多种需求；用第8课的聚合度方法把 Node 的 UI 职责切出去、打破循环依赖；再用策略化载荷和不变式断言让测试覆盖多长度多文本。三者共同的 OO 思想是：把变化点交给多态，把稳定接口留给使用者。"

## 建议落地顺序

1. **先做问题一的三层抽象 + `StrictSequenceResolver`**（改动集中在 resolver 包，低风险、最出彩、且关联带宽）。
2. **再做问题三的 `ResolverContractTest` + 载荷矩阵**（给问题一的策略提供证据）。
3. **最后做问题二里只拆 `HttpEndpoints` 一项**（破环，出重构前后指标对照）。
