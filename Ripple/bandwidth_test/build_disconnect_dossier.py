"""把已完成的独立审计结果整理成可检查的调研与验证说明。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
SOURCES = [
    ("回调断开只移除连接", "ripple-server/src/main/java/ripple/server/tcp/ServerMessageHandler.java", 51, 59),
    ("分发时空连接直接进入发送", "ripple-server/src/main/java/ripple/server/core/dispatcher/EqualDivisionClientDispatcher.java", 70, 77),
    ("持久化早于通知", "ripple-server/src/main/java/ripple/server/core/Node.java", 383, 400),
    ("PUT 响应在 Node.put 返回后构造", "ripple-server/src/main/java/ripple/server/tcp/handler/PutRequestHandler.java", 58, 67),
    ("后台周期只重连服务器节点列表", "ripple-server/src/main/java/ripple/server/core/Worker.java", 38, 50),
    ("首次同步发送后记 ACK", "ripple-server/src/main/java/ripple/server/core/Node.java", 460, 465),
    ("重试发送后记 ACK", "ripple-server/src/main/java/ripple/server/core/Tracker.java", 84, 91),
    ("按 ACK 差集决定重试目标", "ripple-server/src/main/java/ripple/server/core/Tracker.java", 127, 140),
]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    args = parser.parse_args()
    suite = args.suite.resolve()
    audit = suite / "audit"
    data, contract = read(audit / "expected-actual.json"), read(suite / "expectations.json")
    assert data["valid_runs"] == 6
    by_name = {r["condition"]: r for r in data["runs"]}
    assert all(r["source_prediction"] == "MATCH" for r in data["runs"])
    fragments = []
    for description, relative, first, last in SOURCES:
        path = BASE / "Ripple" / relative
        lines = path.read_text(encoding="utf-8").splitlines()
        fragments.append({"description": description, "file": str(path.relative_to(BASE)),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "first_line": first, "last_line": last,
                          "numbered_source": "\n".join(f"{n}: {lines[n-1]}" for n in range(first, last+1))})
    (audit / "source-fragments.json").write_text(json.dumps(fragments, ensure_ascii=False, indent=2), encoding="utf-8")
    proof = read(audit / "cluster_blackhole_reset-raw-proof.json")
    callback = by_name["subscriber_reset"]
    ack_example = proof["final_ack"][0]
    span = proof["premature_ack"]["0"]
    labels = {"subscriber_control": "单服务端正常对照", "subscriber_blackhole": "订阅下行丢包 6 秒，保留连接",
              "subscriber_reset": "断开回调连接", "cluster_control": "双服务端正常对照",
              "cluster_blackhole": "目标链路丢包 22 秒，保留连接",
              "cluster_blackhole_reset": "丢包后断开源服务端的副本连接"}
    table = ["| 测试 | 本研究的可靠性预期 | 源码预测 | 实际结果 |",
             "|---|---|---|---|"]
    for name, row in by_name.items():
        actual = f"源端 {row['source_stored']}/3；订阅端 {row['subscriber_stored']}/3；PUT 成功 {row['put_success']}/3"
        if row["replica_stored"] is not None:
            actual += f"；目标副本 {row['replica_stored']}/3"
        if row["premature_ack_sequences"]:
            actual += "；3 条均出现提前 ACK"
        if row["npe_count"]:
            actual += f"；空指针 {row['npe_count']} 次"
        actual += f"；预测 {row['source_prediction']}，可靠性目标 {row['healthy_target']}"
        table.append(f"| {labels[name]} | {contract['healthy_target'][name]} | {contract['source_based_prediction'][name]} | {actual} |")
    date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    text = f"""# Ripple 断联机制调研、证据和预期／实际对照

生成时间：{date}（北京时间）。本说明使用同一套冻结输入的六场景复跑；前轮探索结果另存，不混作本轮重复次数。前四场景完成后，WSL 会话中断，最后两场景在 `recovery_runs/` 补跑；没有把未完成轮次记作有效结果。

## 1. 可支持的结论

1. 回调连接被明确复位后，服务端仍保存更新，但推送使用空 channel，触发异常；本轮观察窗口内未恢复推送。
2. `ack_nodes` 不能解释为“目标已经处理并保存”。故障期目标尚无消息时，它已经包含目标节点；而重试目标又直接取 `node_list - ack_nodes`。
3. 原连接保留时最终可补达；复位原连接后，即使源服务端自动重连成功，目标在本轮约 30 秒恢复窗口内仍缺失三条更新。

没有发现已收到载荷的字节内容错误。不能把这些小样本结论外推成线上失效率、永久丢失或任意协议／拓扑的保证。

## 2. 外部一手资料与本地证据如何对应

- [Netty 4.1.109.Final 的 Channel 源码文档](https://github.com/netty/netty/blob/netty-4.1.109.Final/transport/src/main/java/io/netty/channel/Channel.java)：I/O 调用异步返回，返回时不保证操作已完成。本轮运行依赖正是 4.1.109.Final；这解释了为什么调用发送不能直接充当远端完成确认。
- [Netty ChannelFuture 官方文档](https://netty.io/4.1/api/io/netty/channel/ChannelFuture.html)：Future 表示 I/O 操作的状态。本文不把 Future 成功等同于远端数据库持久化；后者由目标数据库和应用处理结果另外验证。
- [RFC 9293，第 3.10.7.4 节](https://www.rfc-editor.org/rfc/rfc9293.html#section-3.10.7.4)：已建立连接接收有效 RST 后，连接关闭并清理队列。由此推断：新连接的应用需要自行决定补发哪些更新，不能假定旧连接的未完成数据会由新连接继承。

以上资料只支持机制解释，不证明 Ripple 存在缺陷。缺陷证据来自本项目源码、运行 JAR 反汇编、原始抓包、日志及 SQLite 数据。

本地仓库记录的 HEAD 为 `{read(suite / 'execution.json')['git_head']}`，但版本归属以 `execution.json` 中的发行包哈希和运行 JAR 哈希为准，不能只依赖 HEAD。WSL 看到的工作区状态原样保留，没有据此假定运行 JAR 与所有源文件逐字对应；本次只核对与结论相关的字节码路径。

## 3. 事前登记与实验条件

`expectations.json` 在启动新实验前写入，分别登记可靠性目标、基于源码和前轮探索的预测，以及拒绝无效实验的条件。它属于确认性复跑，不是对未知结果的盲测。

可靠性目标由本研究设定，**不是从项目 README 推导出的官方 SLA**。例如，“恢复后约 30 秒内补齐”是本实验的工程验收窗口；超过窗口只记为截止时缺失。

- 六场景均为全新隔离网络、独立服务端／客户端进程和数据库。
- 1 个发布者、1 个订阅者，hashing 协议；单服务端或双服务端。
- 每轮 3 条更新，序号 0、1、2，value 256 字节，每 2 秒 1 条。暖机不计入正式结果。
- 正常组及回调 RST 组固定观察约 36 秒；丢包组解除故障后继续观察约 30 秒。
- 故障通过命名空间内的 `tc netem loss 100%`、合法序号的双向 RST 注入；不操作用户原有网络连接。
- 实验前复制代码快照并记录 SHA-256，结束后再次检查输入未改变。运行时原版 JAR 由 `javap -p -c` 独立核对相关调用顺序。
- 分段执行记录与最终哈希核对位于 `recovery-validation.json`；原始 `execution.json` 保留中断前状态，未伪造为整套连续执行退出 0。

## 4. 预期结果与实际结果

{chr(10).join(table)}

`MATCH` 只表示现有缺陷的预测被复现，**不表示系统通过可靠性测试**。`FAIL` 才是对应可靠性目标未达到的判定。

## 5. 回调问题的证据链

测试过程：先建立订阅并验证暖机可达，再对回调连接双向发送 RST，核查旧连接消失，随后发布三条正式更新。

独立审计在 PCAP 中核实了 {callback['rst_packets_verified']} 个对应 RST 包，逐包检查连接四元组、序号、时间和 TCP 校验和；不是仅凭注入命令返回码认定断联。

结果：服务端保存 {callback['source_stored']}/3，订阅者保存 {callback['subscriber_stored']}/3，成功 PUT 响应 {callback['put_success']}/3，源端空指针异常 {callback['npe_count']} 次。

源码顺序为：`applyMessageToStorage` → `doNotifyClients` → 返回结果；PUT 响应在 `Node.put` 正常返回后才构造。回调查找为空时 `Api.sync` 解引用空 channel，异常从通知路径向上传播。因此本地已经落库，却没有成功响应，是同一调用链可以解释的结果。

后台 `Worker` 的周期重连遍历服务器节点列表；它没有在该位置为订阅回调地址建立相同的恢复流程。这里证明的是所测路径没有自行恢复，不排除其他操作（如显式重新订阅或主动拉取）可能恢复状态；这两种操作本轮未测试。

详细日志行号、RST 包与结果位于 `audit/subscriber_reset-raw-proof.json`。该文件的 `logs` 字段给出原始日志文件名和一基行号。

## 6. ACK 问题的证据链

测试过程：双服务器暖机后确定源与目标，阻断到目标端口的 TCP 流量约 22 秒，在故障期采样两端消息表与源端 ACK 表。保留原连接和复位原连接两组使用相同负载。

组合故障组的实际丢包计数至少为 {by_name['cluster_blackhole_reset']['tc_dropped']} 包；解除丢包后，立即复位源服务端进程持有的目标连接，排除目标自连接和客户端监控连接。

取序号 0 的真实样本：

```json
{json.dumps(ack_example | {'sync_send_log_entries': '详见原始证据 JSON'}, ensure_ascii=False, indent=2)}
```

这条业务消息在目标缺失且源 ACK 已包含目标的状态下，被连续观测到 {span['samples']} 次，首尾跨度约 {span['span_seconds']:.3f} 秒。不是把异步发送后一个瞬间的数据库差异直接当作长期故障。

恢复后目标仍缺消息，但根据相同 ACK 差集算法计算的重试目标为空。原始源端日志中的发送记录与消息 UUID 关联保存在 `final_ack[*].sync_send_log_entries`，可检查是否发生额外应用发送。

独立审计还从截止前的 socket 快照确认：**持有连接的仍是源服务端进程，但到目标端口使用了不同的新本地端口**，并结合日志检查重新连接动作。因此没有把“其他客户端还有连接”误判成源服务端恢复。

```text
{chr(10).join(proof['reconnect_socket_lines'])}
```

运行 JAR 反汇编证据位于 `audit/ripple.server.core.Node.javap.txt` 与 `audit/ripple.server.core.Tracker.javap.txt`：两个路径均先调用 `Api.sync`，后调用 `recordAck`。`audit/ripple.server.helper.Api.javap.txt` 显示 `writeAndFlush` 返回的 Future 随后被丢弃。

上述证据支持“确认与实际处理脱节，并导致重试漏选目标”的机制解释。尚未通过修改 ACK 的反事实实验量化修复效果，本文不声称已经完成修复或已证明唯一可能原因。

## 7. 对照、排除项和局限

- 两个正常对照组均核对源端／副本／订阅端，避免把一般启动失败当作断联故障。
- 独立审计不读取旧 `disconnect-evidence.json` 的结论，直接重算消息事件、最终数据库和故障期快照，并重建完整发送载荷。
- 三处抓包的内核丢包统计均要求为零；数据库要求完整性检查通过、无 SQLite 异常；出现无效故障注入或正式提交不足时拒绝该轮。
- 数据库跨进程顺序读取，非原子全局快照；持续多次的故障期差异及最终数据库检查用于降低瞬时异步差异的误判。
- 本轮没有测量自然断联发生概率，没有证明永远无法补齐，没有验证所有订阅拓扑、增量更新、重启恢复、磁盘掉电持久性或任意低带宽。
- “收到的内容一致”不意味着所有内容都收到；缺失样本独立记账。

## 8. 测试脚本与复跑命令

执行环境为 WSL Ubuntu／Linux root，使用系统 Python 标准库；需要 Java、javac、javap、iproute2、tc、tcpdump，以及已有 server/client 发行包。root 用于新建命名空间、整形和 RST 注入。

完整六场景复跑（输出目录必须不存在）：

```bash
cd /mnt/d/Ripple
python3 bandwidth_test/run_disconnect_audit.py --output /mnt/d/Ripple/bandwidth_test/results/disconnect_reproduce_new
python3 bandwidth_test/audit_disconnect_evidence.py --suite /mnt/d/Ripple/bandwidth_test/results/disconnect_reproduce_new
```

只验证回调问题：

```bash
python3 bandwidth_test/disconnect_probe.py --conditions subscriber_control subscriber_reset --output /mnt/d/Ripple/bandwidth_test/results/callback_reproduce_new
python3 bandwidth_test/audit_disconnect_evidence.py --runs /mnt/d/Ripple/bandwidth_test/results/callback_reproduce_new/subscriber_control /mnt/d/Ripple/bandwidth_test/results/callback_reproduce_new/subscriber_reset --output /mnt/d/Ripple/bandwidth_test/results/callback_reproduce_audit
```

只验证 ACK 与重连问题：

```bash
python3 bandwidth_test/disconnect_probe.py --conditions cluster_control cluster_blackhole cluster_blackhole_reset --output /mnt/d/Ripple/bandwidth_test/results/ack_reproduce_new
python3 bandwidth_test/audit_disconnect_evidence.py --runs /mnt/d/Ripple/bandwidth_test/results/ack_reproduce_new/cluster_control /mnt/d/Ripple/bandwidth_test/results/ack_reproduce_new/cluster_blackhole /mnt/d/Ripple/bandwidth_test/results/ack_reproduce_new/cluster_blackhole_reset --output /mnt/d/Ripple/bandwidth_test/results/ack_reproduce_audit
```

审计脚本退出 0：原始证据检查通过且代码预测被复现；退出 2：预测与观察不符；断言异常：证据完整性、注入或对照不满足要求。**退出 0 不等于产品可靠性通过**，必须检查 `healthy_target`。

## 9. 本次产物索引

本次冻结实验目录：`{suite.relative_to(BASE)}`。

| 文件 | 用途 |
|---|---|
| `expectations.json` | 开始实验前登记的两类预期与排除条件 |
| `execution.json`、`code_snapshot/` | 执行状态、输入哈希及代码快照 |
| `runs/<场景>/` | 每轮 PCAP、消息事件、数据库、日志和采样时间线 |
| `audit/expected-actual.csv`、`.json` | 机器可读的预期／实际结果与判定 |
| `audit/*-raw-proof.json` | 原始证据摘录、消息 UUID、ACK 状态、日志行号、RST 和重连证明 |
| `audit/*.javap.txt` | 实际运行 JAR 的字节码 |
| `audit/source-fragments.json` | 源码位置、摘录和对应源文件 SHA-256 |
| `audit/audit_code/` | 独立审计及文档生成工具的代码快照和 SHA-256 |
| `audit/input-evidence-sha256.json` | 本次使用的原始证据文件哈希 |

## 10. 直接用于中期汇报的表述

> 已构建可控断联验证环境，完成冻结版本的六场景复跑，并结合原始抓包、数据库、日志及运行字节码进行独立审计。结果显示：保留连接的短时丢包可以延迟补达；明确复位回调连接会触发通知异常；服务器间还存在确认记录早于实际接收的情况。组合故障下，即使连接重建，目标副本在观察窗口内仍未补齐。因此后续拥塞优化将分别评价资源约束、端到端送达与断联恢复，不能只以发布响应或连接状态作为正确性指标。
"""
    report = BASE / "middle_report/断联机制调研与证据-20261022.md"
    report.write_text(text, encoding="utf-8")
    hashes = {}
    for path in suite.rglob("*"):
        if path.is_file() and "audit" not in path.relative_to(suite).parts and not {"assets", "classes"}.intersection(path.relative_to(suite).parts):
            hashes[str(path.relative_to(suite))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (audit / "input-evidence-sha256.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成：{report}")


if __name__ == "__main__":
    main()
