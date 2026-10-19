# Ripple 外部带宽与稳定性测试

该工具放在 Ripple 仓库之外，直接启动已有的服务端发行包，并通过独立编译的 Java 驱动加载原版客户端 JAR。不会向 Ripple 源码、POM 或构建目录写入文件。

支持消息大小、频率、时长、订阅者数、服务端数和共享订阅下行带宽设置。每次运行启动独立测试集群，不使用当前网页测试的数据。

## 快速运行

在 WSL Ubuntu 中执行：

```bash
cd /mnt/d/Ripple/bandwidth_test

# 冒烟测试：256 字节、每秒 5 条、持续 2 秒
sudo bash run.sh --size 256 --rate 5 --duration 2 \
  --baseline-duration 1 --drain-timeout 5

# 正式流量测试：1 KiB、每秒 100 条、持续 60 秒
sudo bash run.sh --size 1024 --rate 100 --duration 60

# 限带宽：下行共享 512 kbit/s，发送后最多等待 30 秒排空
sudo bash run.sh --size 1024 --rate 100 --duration 60 \
  --bandwidth 512kbit --drain-timeout 30

# 增加订阅者
sudo bash run.sh --size 1024 --rate 50 --duration 30 \
  --subscribers 5 --bandwidth 1mbit
```

启动时会打印本次结果目录。发送时长不包括编译、集群启动、订阅探测、空闲基线和排空。启动包含约 11 秒的集群预热，通常还需要一些 JVM 启动时间。

## 环境与发行包

- WSL/Linux、Python 3.12 或更高版本、Java 8 或更高版本，需有 `javac`。
- `iproute2`（ip、tc）、tcpdump；建议安装 ethtool。
- 需要 root 创建命名空间、配置新建接口与抓包。
- 原版 `ripple-server-publish.tar.gz`、`ripple-client-publish.tar.gz` 已构建好。
- 运行时无需访问互联网。工具不自动执行 Maven 或修改项目依赖。

默认发行包位置：

```text
../Ripple/ripple-server/target/ripple-server-publish.tar.gz
../Ripple/ripple-client/target/ripple-client-publish.tar.gz
```

其他项目路径可以通过 `--ripple-root /path/to/Ripple` 指定。首次部署缺少系统工具时可安装：

```bash
sudo apt-get install python3 openjdk-8-jdk-headless iproute2 tcpdump ethtool
```

## 参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--size` | 1024 | value 的总 UTF-8 字节数，包含 17 字节测试头；范围 32～1000000 |
| `--rate` | 100 | 发布者每秒目标提交数；实际速率单独统计 |
| `--duration` | 60 | 发送阶段秒数 |
| `--subscribers` | 1 | 独立客户端数量，范围 1～100 |
| `--servers` | 3 | hashing 节点数，范围 1～20 |
| `--bandwidth` | 不限速 | 订阅侧共享下行，支持 bit/kbit/mbit/gbit，小写或大写均可 |
| `--queue-bytes` | 1048576 | 限速接口队列上限，单位字节，最小 1600 |
| `--drain-timeout` | 30 | 停止发送后最多等待秒数，全部投递与成功响应收齐可提前结束 |
| `--baseline-duration` | 10 | 订阅探测完成后的空闲观测秒数 |
| `--seed` | 42 | Java 伪随机填充种子 |
| `--output` | 工具目录/results | 每次创建独立结果子目录 |
| `--ripple-root` | 同级 Ripple | 只读发行包来源 |

`1 KiB = 1024 字节`；`1 kbit/s = 1000 bit/s`。计划数量为 `ceil(rate × duration)`。如果驱动跟不上，按实际时长停止，不无限追赶发送任务；因此实际提交量可能少于计划量。

测试头格式为 `RB1:<12位序号>:`。正文使用 ASCII 伪随机字符，总大小包含测试头。相同种子及序号的 Java 驱动内容可复现，UUID 和网络时序每次不同。

## 隔离与限速范围

```text
服务端空间                             订阅者空间
3 个原版服务端 + 发布客户端 ── veth ── 多个原版订阅客户端
          lo                   ↓                 lo
  cluster.pcap        服务端出方向 tc       peers.pcap
                          traffic.pcap 在订阅端采集
```

每次使用唯一的 `rb-s-*`、`rb-c-*` 网络命名空间。端口 13001 起为测试服务端，15000 为发布者回调，15001 起为订阅者回调，均处于隔离空间。

`--bandwidth` 限制服务端空间到订阅者空间的**共享下行**，不是每个订阅者单独限速，也不是整个集群的总带宽。反向响应、服务器内部同步以及订阅者之间的本地转发不受该参数限制，但分别抓包统计。

tc 使用 HTB 与字节队列，记录配置、队列积压、丢弃和 overlimits。低带宽下允许短时突发，短窗口平均值可能高于配置值；请结合较长窗口和 `tc-stats.json` 判断整形效果。

原版 hashing 的客户端分发可能使用 DISPATCH，并让客户端再转发；这类流量记录在 `peers.pcap`。订阅者随机选择 hashing 候选节点，拓扑每次可能不同，实际连接分布保存在 flows.csv。

SQL 数据库在 Linux 临时目录中运行，避免 Windows 挂载盘的 SQLite 同步写开销主导结果；退出后归档到结果目录 `databases/`。所有其他产物位于工具结果目录。进程和整形随退出清理，现有主机网络接口不被修改。

## 结果文件

| 文件 | 内容 |
|---|---|
| `summary.json` | 提交、发布响应、唯一投递、延迟、流量与测量状态 |
| `config.json` | 参数、版本、实际阶段时间、数据库位置与整形范围 |
| `messages.csv` | 每条 send/write/put_response/receive 原始事件，Unix 秒时间戳 |
| `timeseries.csv` | 秒级提交量、投递量、待完成量和流量；首尾窗口按真实时长归一化 |
| `flows.csv` | 有载荷 TCP 连接的方向、字节与已解码消息类型数量 |
| `traffic.pcap` | 服务端与订阅者之间的双向流量，在订阅侧 veth 单点采集 |
| `cluster.pcap` | 服务端间以及发布者与服务端间的回环流量 |
| `peers.pcap` | 订阅者之间的回环流量 |
| `tc-stats.json` | 限速设置后与统计截止时的 qdisc/class 状态 |
| `publisher-0.jsonl`、`subscriber-*.jsonl` | 未加工的事件记录 |
| `logs/` | Java 进程与抓包器输出 |
| `databases/` | 结束后保留的测试数据库 |
| `assets/`、`classes/` | 本次使用的原版发行包内容及外部驱动编译产物 |

基线不另存单独 PCAP，而是通过 config.json 的阶段边界和各抓包的 `windows.baseline` 定位。抓包覆盖启动、探测、基线、发送、排空和停止阶段；直接查看整个 PCAP 的总字节会包含这些阶段，正式指标使用 `send` 或 `send_and_drain` 窗口。

## 指标解释

- `submitted`：实际交给 Netty 的唯一测试消息数；`write_failures` 另报写入失败。
- `put_success`：截止时已收到成功 PUT 响应的消息数，不能作为下游送达数。
- `received_unique`：原版客户端业务处理器执行后观察到的唯一“订阅者、序号”数量。
- `expected_deliveries = submitted × subscribers`。
- `missing_at_deadline`：截止时仍未观察到的投递，不声称永久丢失。
- `delivery_ratio`：排空期结束时送达率；`delivery_ratio_during_send` 单独给出发送阶段送达率。
- 延迟：实际提交到原客户端处理器返回，包含 SQLite 处理时间。使用同一 WSL 时钟；Java 8 的当前环境实际时间分辨率约毫秒。
- 延迟分位数：仅针对已经收到的样本，使用线性插值；存在未送达时，不能用较低的 P99 推断整体稳定。
- `tcp_payload_bytes`：TCP 载荷，包含重传。
- `unique_tcp_payload_bytes`：按流和逻辑序列号去重的 TCP 载荷。
- `frame_bytes`：PCAP 原始包长之和，包含可见 Ethernet/IP/TCP 头和纯 ACK；PCAP 文件头不计。
- `frame_bps`、`tcp_payload_bps`：字节数乘 8 除以实际窗口秒数。
- `captures.traffic.downlink_send*`：只统计服务端到订阅者方向，适合与带宽上限对照。
- `total_send_and_drain_*`：三处采集点的实际窗口流量相加，同一链路不在两端重复计数。
- `pending`：已提交的预期投递减去已唯一收到的投递，不等同于内核队列长度。

完整包的截止捕获可能停在一条尚未传完的 Ripple 帧中。此情况单独记录为 `unfinished_frames`：已有包字节统计仍有效，消息类型计数只包含完整解码的帧。抓包丢包、序号缺口和损坏数据则使测量标记为 `measurement_incomplete`。

`status=complete` 表示本次观测和统计完成，不代表全部消息送达。是否送达必须查看 `stability`、`missing_at_deadline` 与每个订阅者的统计。空闲、探测与序号 -1 的暖机事件不计入正式业务投递。

## 实现限制

- 第一版只支持一个发布者及 hashing 协议。
- 原版服务端连接表存在并发建连竞态；工具串行建立订阅并进行探测，无法保证规避引擎内所有竞态。若探测失败，保留失败结果和日志，不输出成功测试结论。
- 驱动包装实际处理器并逐消息写事件，统计本身会有 CPU/I/O 开销。高负载时应同时检查实际提交速率、调度迟延、进程资源及存储性能。
- 回环/veth 捕获不等同于物理链路线速，不包含前导码、帧间间隔等成本；关闭 veth 卸载的结果记录在配置中。
- PCAP 分析当前支持经典 Ethernet/IPv4 TCP 抓包，内存随抓包大小增长。长时间大消息测试应留足磁盘和内存，先做短时试跑。
- 重连后的新回调连接通过周期检查安装观测器，第一条消息可能在观测器就绪前到达；本工具用于受控稳定连接及带宽实验，不用于精确认证断线恢复性能。
- 连续超过半个 TCP 序号空间的乱序/离线缺口不能可靠推断，正常流量按到达顺序展开序号，支持累计跨越 4 GiB。

## 测试与退出

```bash
python3 -m unittest discover -s tests -v

# 可选：自动等待限速负载开始，再模拟 Ctrl+C 并检查清理结果
sudo python3 tests/interrupt_check.py
```

Ctrl+C 会停止本次子进程、删除新建网络空间，并保留原始抓包和失败/中断状态。不会删除用户先前运行的 Ripple 进程。无需手动清空数据库。

退出码：0 为观测完成（即使截止仍有积压）；2 为参数错误或观测不完整；1 为运行失败；130 为收到中断。请结合 summary.json 区分失败原因。
