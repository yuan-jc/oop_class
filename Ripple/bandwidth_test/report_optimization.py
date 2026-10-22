"""从真实结果生成中位数对照报告；不把未完成传输当作瘦身。"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics


def median(rows, key):
    values = [row[key] for row in rows if row.get(key) is not None]
    return statistics.median(values) if values else None


def text(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        if not row["valid"]:
            raise ValueError("结果含无效观测，不可直接形成优化结论")
        groups[row["case"], row["version"]].append(row)
    return {key: dict(repeats=len(values),
        **{name: median(values, name) for name in (
            "submitted", "received", "missing", "actual_rate", "p50_ms", "p99_ms", "delivery_ratio",
            "during_ratio", "pending_peak", "qdisc_backlog_at_deadline", "downlink_bytes_per_delivered",
            "complete_downlink_bytes_per_message", "total_frame_bytes")},
        rate_min=min(v["actual_rate"] for v in values), rate_max=max(v["actual_rate"] for v in values),
        corrupt=sum(v["corrupt"] for v in values)) for key, values in groups.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-runs", type=int, default=45)
    args = parser.parse_args()
    root = args.root.resolve()
    rows = json.loads((root / "results.json").read_text())
    if len(rows) != args.expected_runs:
        raise ValueError(f"预期{args.expected_runs}组，实际{len(rows)}组；禁止把部分结果写为完整验证")
    groups = aggregate(rows)
    ledger = json.loads((root / "codec-ledger.json").read_text())
    suite = json.loads((root / "suite.json").read_text())
    lines = ["# Ripple 带宽优化真实验证结果", "", "## 版本与实现", "",
        "| 版本 | Git标签 | 提交 | 实际改动 |", "| --- | --- | --- | --- |"]
    descriptions = {"v0": "原版", "v1": "UUID二进制化、同步操作枚举化", "v2": "V1加同步/分发value自适应Deflate压缩"}
    for mode in ("v0", "v1", "v2"):
        item = next(r for r in ledger if r["version"] == mode)
        lines.append(f"| {mode} | bandwidth-{mode}-stable | `{item['commit'][:12]}` | {descriptions[mode]} |")
    lines += ["", "三个stable版本共同包含完全相同的连接表并发安全修复，避免原版空指针异常风暴污染测量；V0称原版线格式稳定基线，不是逐字未修改的原版。未经修复的原始标签仍为bandwidth-v0-original。三版连接表生产文件与测试文件的Git blob逐字一致。",
        "协议优化只改变传输表示，不改变副本数、ACK、订阅、更新与存储逻辑。未移除SYNC_RESPONSE，未实现微批。本次压缩为JDK内置Deflate低等级，不冒称Snappy/Zstd。", "",
        "## 测量条件", "",
        f"真实3服务端、1订阅者、Linux命名空间与tc；每组发送{suite['duration']}秒并固定等待{suite['wait']}秒，三次重复。1024 B目标100条/秒，32 B目标500条/秒；实际速率另列。",
        f"并行实验数为{suite['workers']}；各实验网络完全隔离，同一WSL宿主CPU仍可能存在相互影响。表中P99为三次运行各自P99的中位数，不是合并样本P99。",
        "仅服务端到订阅者的共享下行限速，反向与服务端复制不限速。所有版本通过同一外部ServerDriver，待全部服务监听后才调用原initCluster；未改业务处理路径。随机载荷为36字符表生成的ASCII，不是不可压缩随机字节；结构化载荷为重复字段模板的合成文本，不能代表所有真实业务。",
        "事件、数据库与抓包在Linux运行盘；节点结束后归档Windows。预备阶段遇到Windows挂载盘Errno61，以及原版重连线程空指针刷日志，均保留证据并排除于正式结果。正式工具使用ss监听表检查，避免创建即断开的探测TCP连接，并拒绝带服务异常的运行。", "",
        "## 相同DTO的精确编码账本", "",
        "每种载荷与大小编码并解码1000条，逐条验证请求UUID、消息UUID、完整value一致及缓冲耗尽；含4字节应用层帧长度，不含TCP/IP、链路头与响应。", "",
        "| 载荷 | 字节 | V0同步帧均值 | V1同步帧均值 | V2同步帧均值 | V1减少 | V2减少 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for payload, size in (("random", 32), ("random", 1024), ("structured", 1024)):
        values = {mode: next(r["sync_frame_bytes_mean"] for r in ledger if r["version"] == mode and r["payload"] == payload and r["size"] == size) for mode in ("v0", "v1", "v2")}
        lines.append(f"| {payload} | {size} | {text(values['v0'])} | {text(values['v1'])} | {text(values['v2'])} | {(1-values['v1']/values['v0'])*100:.2f}% | {(1-values['v2']/values['v0'])*100:.2f}% |")
    lines += ["", "codec-ledger中的loop_ms包含载荷生成、编码、解码和JIT差异，不作为压缩CPU微基准。", "",
        "## 固定窗口真实处理结果", "",
        "| 场景 | 版本 | 提交中位数 | 实际条/秒范围 | P50 ms | P99 ms | 截止处理率 | 发送期间处理率 | 最大待处理数中位数 |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
    for (case, mode), group in sorted(groups.items()):
        lines.append(f"| {case} | {mode} | {text(group['submitted'],0)} | {group['rate_min']:.1f}～{group['rate_max']:.1f} | {text(group['p50_ms'])} | {text(group['p99_ms'])} | {group['delivery_ratio']*100:.2f}% | {group['during_ratio']*100:.2f}% | {text(group['pending_peak'],0)} |")
    lines += ["", "最大待处理数由每秒业务时间序列计算，包含端到端在途与排队，不是Netty内存或qdisc字节峰值。未完成消息不进入已处理样本P99，须与截止处理率一起阅读。", "",
        "## V2相对原版的变化", "",
        "| 场景 | P99变化 | 截止处理率变化 | 待处理峰值变化 |", "| --- | ---: | ---: | ---: |"]
    for case in sorted({r["case"] for r in rows}):
        baseline, optimized = groups[case, "v0"], groups[case, "v2"]
        pending_change = f"{(1-optimized['pending_peak']/baseline['pending_peak'])*100:.2f}%下降" if baseline["pending_peak"] else "—"
        lines.append(f"| {case} | {(1-optimized['p99_ms']/baseline['p99_ms'])*100:.2f}%下降 | {(optimized['delivery_ratio']-baseline['delivery_ratio'])*100:+.2f}个百分点 | {pending_change} |")
    lines += ["", "## 字节效率与正确性", "",
        "| 场景 | 版本 | 完成交付组的下行B/消息中位数 | 截止qdisc backlog B中位数 | 内容异常总数 |",
        "| --- | --- | ---: | ---: | ---: |"]
    for (case, mode), group in sorted(groups.items()):
        lines.append(f"| {case} | {mode} | {text(group['complete_downlink_bytes_per_message'])} | {text(group['qdisc_backlog_at_deadline'],0)} | {group['corrupt']} |")
    lines += ["", "未完成组不填完整交付的单位字节效率，防止把尚未发出的消息误当节省。编码账本始终比较相同DTO，因此不受截止缺失影响。原始CSV另外保留实际总帧字节和每条已处理消息对应的下行字节，后者含控制、重传与在途帧，不作为独立压缩率。", "",
        f"正式运行共{len(rows)}组，全部通过抓包与内容观测检查；已处理内容异常合计{sum(r['corrupt'] for r in rows)}。所有源码、主JAR及依赖JAR摘要在各运行config.json，控制工具提交为`{suite['tool_commit']}`。", "",
        "## 结论边界", "",
        "紧凑编码对小消息有直接字节收益；压缩对高重复模板的收益不能外推到高熵数据。即使优化减少了字节，输入需求仍高于链路容量时仍会排队，不能以短跑收齐证明长期稳定。",
        "32 B高频场景应结合实际输入速率范围判断，不能将更低的实际输入当成全部时延收益。固定窗口结果与每消息编码账本共同解释。",
        "本次为单宿主WSL模拟，三次重复仅用于初步稳定性验证，不是生产环境容量承诺；真实边缘部署仍需丢包、重连、资源受限设备和更多数据分布测试。", "",
        "## 复现", "", "```bash", "cd /mnt/d/Ripple",
        "python3 bandwidth_test/optimization_suite.py --workers 1 --repeats 3 --duration 10 --wait 10 --output /tmp/ripple-wire-reproduce --archive-to /mnt/d/Ripple/optimization_results/reproduce",
        "```", "", "使用Linux/WSL root及Java8、Maven、Python3、iproute2、tcpdump、ethtool。以workers=1复现可排除并行实验间的CPU干扰。", "",
        f"正式原始运行目录：`{root}`；Windows归档见`optimization_results/validated_20261022/`。每条results.csv记录都能追溯至单次运行的config.json、summary.json、messages.csv、timeseries.csv、tc-stats.json和三个PCAP。"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines)+"\n", encoding="utf-8")
    (args.output.with_suffix(".json")).write_text(json.dumps(
        {case+"/"+mode: group for (case, mode), group in groups.items()}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
