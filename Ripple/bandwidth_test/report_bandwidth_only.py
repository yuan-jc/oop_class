"""只对完成全部交付的工作负载比较实际字节，不作时延或稳定性结论。"""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    rows = json.loads((root / "results.json").read_text())
    ledger = json.loads((root / "codec-ledger.json").read_text())
    if len(rows) != 9 or len({(r["case"], r["version"]) for r in rows}) != 9:
        raise ValueError("需要3类载荷×3个版本的完整九组结果")
    if any(not r["valid"] or r["missing"] or r["corrupt"] for r in rows):
        raise ValueError("含未完成交付或异常记录，不能直接比较单位字节占用")
    by_key = {(r["case"], r["version"]): r for r in rows}
    message_counts = {}
    for row in rows:
        summary = json.loads((Path(row["directory"])/"summary.json").read_text())
        counts = {}
        for capture in summary["captures"].values():
            for kind, count in capture["message_counts"].items():
                counts[kind] = counts.get(kind, 0)+count
        message_counts[row["case"], row["version"]] = counts
    control_heavy = {case for case, _ in by_key if any(
        message_counts[case, version].get("ACK_REQUEST", 0) > 10*by_key[case, version]["submitted"]
        for version in ("v0", "v1", "v2"))}
    lines = ["# Ripple 带宽优化：代码版本与实际字节验证", "",
        "## 本次范围", "",
        "按最新要求只验证网络带宽占用，不扩展故障处理，也不以本轮短跑宣称P99或生产稳定性提升。实现了紧凑UUID/同步操作和自适应压缩；未实现微批、Varint，也未移除回执。", "",
        "三个stable版本共用逐字相同的连接表稳定性补丁，避免异常线程污染字节测量。V0是原版线格式的共同修复基线；未经修改的原始代码仍保留在bandwidth-v0-original。", "",
        "## Git版本", "", "| 版本 | 标签 | 提交 | 改动 |", "| --- | --- | --- | --- |"]
    descriptions = {"v0": "原版线格式＋共同修复", "v1": "V0＋UUID二进制与同步操作枚举", "v2": "V1＋自适应Deflate载荷压缩"}
    for version in ("v0", "v1", "v2"):
        row = next(r for r in rows if r["version"] == version)
        lines.append(f"| {version} | bandwidth-{version}-stable | `{row['commit']}` | {descriptions[version]} |")
    lines += ["", "## 相同消息的应用层同步帧", "",
        "每项1000条确定性消息，真实调用各版编码器和解码器，逐条验证请求UUID、消息UUID和完整value一致、输入耗尽。包含4字节帧长度，不包含TCP/IP、链路头和回执。", "",
        "| 载荷 | 原始B | V0帧B | V1帧B | V2帧B | V1减少 | V2减少 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for payload, size in (("random", 32), ("random", 1024), ("structured", 1024)):
        values = {v: next(r["sync_frame_bytes_mean"] for r in ledger if r["version"] == v and r["payload"] == payload and r["size"] == size) for v in ("v0", "v1", "v2")}
        lines.append(f"| {payload} | {size} | {values['v0']:.2f} | {values['v1']:.2f} | {values['v2']:.2f} | {(1-values['v1']/values['v0'])*100:.2f}% | {(1-values['v2']/values['v0'])*100:.2f}% |")
    lines += ["", "V1普通同步帧固定减少57B：两个UUID各减少24B，update操作由10B降为1B。V2只压缩同步/分发value，采用JDK Deflate低等级；小于512B或完整编码无净收益时发送原文。", "",
        "## 真实网络抓包验证", "",
        "3服务端、1订阅者；服务端至订阅者下行512kbit/s，其余方向不限速。两种大小均目标50条/秒；发送2秒，固定等待3秒，单实验串行运行。所有版本使用同一ServerDriver等待全部服务监听和原心跳存活后才正式发送。",
        "为避免比较实际提交量略有差异，以下字节均按本轮实际提交/完成数量归一化；每组一轮，仅作为初步带宽验证。完整原始总字节、消息数和包数保留在JSON/CSV。", "",
        "| 场景 | 版本 | 提交/处理 | 下行帧B/消息 | 相对V0减少 | 跨抓包点总帧B/提交 | 相对V0减少 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for case in ("bytes_random", "bytes_structured", "bytes_small"):
        baseline = by_key[case, "v0"]
        base_down = baseline["complete_downlink_bytes_per_message"]
        base_total = baseline["total_frame_bytes"]/baseline["submitted"]
        for version in ("v0", "v1", "v2"):
            row = by_key[case, version]
            down = row["complete_downlink_bytes_per_message"]
            total = row["total_frame_bytes"]/row["submitted"]
            total_change = "不单独归因" if case in control_heavy else f"{(1-total/base_total)*100:.2f}%"
            lines.append(f"| {case} | {version} | {row['submitted']}/{row['received']} | {down:.2f} | {(1-down/base_down)*100:.2f}% | {total:.2f} | {total_change} |")
    lines += ["", "下行帧字节来自服务端→订阅者单方向抓包，包含该方向TCP/IP、链路头、控制流量和重传；不是纯协议帧。总帧字节是三个不重叠抓包点的窗口合计，服务端间为本机loopback，不能直接称为真实物理链路总线速。", "",
        "## 传输次数与正确性", "",
        "| 场景 | 版本 | PUT_REQUEST | SYNC_REQUEST | SYNC_RESPONSE | ACK_REQUEST | ACK_RESPONSE | 全部抓包TCP包数 | 内容异常 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in sorted(rows, key=lambda r: (r["case"], r["version"])):
        # 运行目录保持为原始Linux路径；归档后相对目录结构相同。
        source = Path(row["directory"]) / "summary.json"
        summary = json.loads(source.read_text())
        counts = {}
        packets = 0
        for capture in summary["captures"].values():
            packets += capture["packet_count"]
            for kind, count in capture["message_counts"].items():
                counts[kind] = counts.get(kind, 0)+count
        lines.append(f"| {row['case']} | {row['version']} | {counts.get('PUT_REQUEST',0)} | {counts.get('SYNC_REQUEST',0)} | {counts.get('SYNC_RESPONSE',0)} | {counts.get('ACK_REQUEST',0)} | {counts.get('ACK_RESPONSE',0)} | {packets} | {row['corrupt']} |")
    lines += ["", "消息与包数来自全PCAP，含暖机、心跳和收尾，不能直接除以正式提交量声称精确每写入次数。编码优化不以减少副本/回执次数取得收益；每次正式写入的载荷路径仍为提交、两个副本同步、一次订阅下发。", "",
        "所有九组正式负载均完整交付，内容异常为0；因此本表没有把少发送或未完成交付当作压缩收益。抓包内核丢失与测量期间服务异常均通过工具校验。", "",
        "另一次32B、300条/秒预备测试出现大量ACK_REQUEST/ACK_RESPONSE及一组运行异常，未纳入本轮单位字节对照，数据单独保留。按最新要求不继续扩展修复控制流程，最终三版小消息统一50条/秒比较。若某组仍出现大量ACK，则总流量变化不单独归因于单帧编码。", "",
        "## 边界与结论", "",
        "随机数据为36字符表的ASCII，仍可被压缩，不能代表不可压缩字节。结构化正文为重复字段模板，是高可压缩合成文本，其收益不能外推到所有业务。",
        "本次直接证明的是同步帧和实际网络字节减少。未证明任意载荷都能跨越256/512kbit/s容量阈值，也不将本轮数据写成长期稳定性或P99改善结论。", "",
        "源码、源码摘要、主JAR及全部依赖JAR摘要在各运行config.json；原始事件、PCAP、flows.csv、tc-stats.json和summary.json均保留。", "",
        "## 复现", "", "```bash", "cd /mnt/d/Ripple",
        "python3 bandwidth_test/optimization_suite.py --cases bytes_random bytes_structured bytes_small --repeats 1 --workers 1 --duration 2 --wait 3 --output /var/tmp/ripple-bytes-reproduce --archive-to /mnt/d/Ripple/optimization_results/bytes-reproduce",
        "```", "",
        f"本次运行目录：`{root}`；Windows归档：`optimization_results/bandwidth_only_20261022/`。",
        "原始失败和未完成的性能预备批次单独保留，未纳入本报告。"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
