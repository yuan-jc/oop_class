"""汇总有效轮次，排除故障注入失败或被中止的实验。"""
import hashlib
import json
from pathlib import Path

from verify_disconnect_probe import main as verify

BASE = Path(__file__).resolve().parent.parent
RESULTS = BASE / "bandwidth_test/results"
CASES = [
    ("disconnect_20261022_02", "subscriber_control"),
    ("disconnect_20261022_02", "subscriber_blackhole"),
    ("disconnect_20261022_02", "cluster_control"),
    ("disconnect_20261022_rst03", "subscriber_reset"),
    ("disconnect_20261022_rst04", "subscriber_reset"),
    ("disconnect_20261022_cluster03", "cluster_blackhole"),
    ("disconnect_20261022_cluster05", "cluster_blackhole_reset"),
]


def main():
    output = RESULTS / "disconnect_20261022_verified"
    output.mkdir(exist_ok=True)
    runs, engine_hashes, provenance = [], {}, {}
    for group, condition in CASES:
        directory = RESULTS / group / condition
        assert not (directory / "probe-failure.json").exists()
        evidence = json.loads((directory / "disconnect-evidence.json").read_text())
        runs.append(evidence)
        for role in ("server", "client"):
            jar = directory / "assets" / role / f"ripple-{role}.jar"
            digest = hashlib.sha256(jar.read_bytes()).hexdigest()
            assert engine_hashes.setdefault(role, digest) == digest, "各轮引擎 JAR 不一致"
        for path in directory.rglob("*"):
            if path.is_file() and not {"assets", "classes"}.intersection(path.relative_to(directory).parts):
                provenance[str(path.relative_to(BASE))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2), encoding="utf-8")
    verify(output)
    tools = {}
    for name in ("disconnect_probe.py", "raw_tcp_reset.py", "verify_disconnect_probe.py", "summarize_disconnect_probe.py"):
        path = BASE / "bandwidth_test" / name
        tools[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "provenance.json").write_text(json.dumps({"engine_jar_sha256": engine_hashes,
        "final_tool_source_sha256": tools, "evidence_sha256": provenance,
        "note": "实验期间迭代了故障注入工具；工具哈希对应最终可复跑版本，原始证据哈希对应选入的实际轮次。"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    report = BASE / "middle_report/断联恢复实验验证-20261022.md"
    report.write_text("""# Ripple 断联恢复实验验证

实验日期：2026-10-22（北京时间）。有效实验 7 轮、6 种条件。结论仅针对本轮原版发行包和受控故障。

## 主要结论

短时丢包且 TCP 连接保留时，本轮更新最终全部补达，收到的内容与原始载荷一致。但明确断开连接后，当前应用的恢复机制存在缺口：回调连接断开可使订阅者停止收到更新；服务器间已经标记完成的 ACK 也可能并不代表副本实际收到数据。

| 条件 | 正式更新数 | 恢复后的结果 |
|---|---:|---|
| 单服务端正常对照 | 3 | 订阅者 3/3，成功发布响应 3/3 |
| 订阅下行连续 100% 丢包约 6 秒，保留连接 | 3 | 订阅者 3/3，最大端到端延迟约 6.884 秒 |
| 回调 TCP 连接被 RST 断开，第 1 轮 | 3 | 服务端落库 3/3，订阅者 0/3，成功发布响应 0/3 |
| 回调 TCP 连接被 RST 断开，第 2 轮 | 3 | 同上，结果重复 |
| 双服务端正常对照 | 3 | 两个服务器和订阅者均 3/3 |
| 到目标服务器的 TCP 流量连续 100% 丢包约 22 秒，保留连接 | 3 | 目标最终 3/3；丢包期间 3 条均出现提前完成 ACK |
| 到目标服务器丢包约 22 秒，恢复网络后立即 RST 源服务器持有的副本连接 | 3 | 重连成功；恢复后观察约 30 秒，目标副本仍 0/3，源端成功发布响应 3/3 |

最后一组订阅者恰好订阅目标副本，因此订阅者也为 0/3。其他拓扑中，订阅者可能从源服务器收到更新，但另一副本仍缺失；不能只看一个订阅者判断集群一致性。

所有实际观测到的正式载荷均与独立重建的 Java 随机载荷完全一致；没有观测到字节内容被改错。问题表现为未收到更新、数据滞后和确认状态失真。这里的 0/3 表示观察截止时缺失，不外推为永远无法恢复。

## 证据与原因

### 回调连接断开后没有自动恢复推送

两轮 RST 均确认原 TCP 连接消失。服务端和订阅者日志记录了断开，后续每次发布均触发 `NullPointerException`。调用路径为 `EqualDivisionClientDispatcher.notifyClients()` 找不到回调 channel，随后 `Api.sync()` 使用空 channel。

三条更新已经存入服务端数据库，但通知异常使处理路径没有返回成功发布响应。固定观察窗口约 36 秒内，没有恢复该回调连接，也没有补达更新。因此“发布者没收到成功”不能等同于“服务器没有执行”，直接重试还需要考虑重复执行。

可核对 `disconnect_20261022_rst03/subscriber_reset` 与 `disconnect_20261022_rst04/subscriber_reset` 下的 `disconnect-evidence.json`、`timeline.ndjson`、`logs/`、`databases/`。

### ACK 提前完成，连接恢复不等于数据恢复

在两服务器丢包实验中，源端 ACK 记录的 `node_list` 和 `ack_nodes` 均已经包含两个服务器，但目标数据库尚无对应 UUID；这一状态持续出现于多个采样点，而非只在发送后的瞬间出现。`tc` 计数确认故障期间确实发生丢包。

保留原连接时，TCP 后来重传使目标最终收到更新，掩盖了应用确认问题。组合故障中，RST 销毁了源端对应的旧连接；日志显示后台随后重新连接成功，但目标数据库在恢复后约 30 秒内仍没有这三条消息，源端 ACK 仍包含目标节点。

代码对应关系：`Node.doSyncWithServer()` 在调用 `Api.sync()` 后立即 `recordAck()`；`Tracker.retrySending()` 也采用同样顺序，并未在这两个位置等待目标端确认。问题不仅存在于重试路径，首次同步路径也会提前标记。

可核对 `disconnect_20261022_cluster03/cluster_blackhole` 与 `disconnect_20261022_cluster05/cluster_blackhole_reset` 下的证据文件。最后一组源为 server-1、目标为 server-2；日志中可找到源端断开后再次 `Reconnecting to Node-2` 和新连接 `Connected`。

## 方法、范围与排除项

- 使用已有原版 server/client JAR，所有选入轮次的引擎 JAR SHA-256 一致。每轮新建网络命名空间、独立 JVM 与临时 SQLite 数据库。
- 每轮 1 个发布者、1 个订阅者，hashing 协议，消息 value 为 256 字节，以每 2 秒 1 条发送 3 条正式更新；暖机消息不计入正式结果。
- 丢包由测试命名空间的 `tc netem loss 100%` 注入；RST 使用抓包中的对端确认号构造，并验证旧连接已经消失。最终组合实验仅断开源服务端进程持有的副本连接，排除客户端监控连接和目标自连接。
- 每约 250 毫秒只读采样消息表和 ACK 表，并保留最终数据库、三处抓包、日志、连接快照。采样是跨数据库顺序读取，非原子全局快照；持续丢包和最终数据库证据用于进一步约束判断。
- 独立复现 `java.util.Random`，逐条核对完整载荷 SHA-256；检查数据库完整性、SQLite 异常、实际丢包计数及正常对照组。
- 首轮时间线文件名与原工具事件文件通配规则冲突，该轮未计入。`ss -K` 未关闭目标连接的轮次、被中止的轮次，以及 RST 后仍有原连接的轮次均排除。较早一轮关闭端口上全部连接的结果也未作为最终组合实验，以免混入额外变量。
- 正常组固定观察约 36 秒；丢包组恢复网络后继续观察约 30 秒。小样本证明可复现的故障存在，不用于估计线上发生概率，也未覆盖长时间断网、进程崩溃、增量更新、全部节点拓扑或极低带宽下的全部行为。

## 复跑与产物

在 WSL Ubuntu 中以 root 运行，输出目录需尚不存在：

```bash
cd /mnt/d/Ripple
python3 bandwidth_test/disconnect_probe.py --output /mnt/d/Ripple/bandwidth_test/results/disconnect_new
python3 bandwidth_test/verify_disconnect_probe.py /mnt/d/Ripple/bandwidth_test/results/disconnect_new
```

本次选入结果位于 `bandwidth_test/results/disconnect_20261022_verified/`：

- `manifest.json`：7 轮原始分析及各轮目录，未复制原始大文件。
- `verification.json`：独立复核结果。
- `provenance.json`：引擎、最终实验工具及选入证据文件的 SHA-256。

复核本次选入结果：

```bash
python3 bandwidth_test/summarize_disconnect_probe.py
```
""", encoding="utf-8")
    print(f"报告：{report}")


if __name__ == "__main__":
    main()
