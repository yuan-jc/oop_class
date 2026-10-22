"""独立审计原始证据，分别输出可靠性目标和事前代码预测的符合情况。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import socket
import sqlite3
import struct
import subprocess


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def original_value(seq, size, seed):
    # 独立重建发送端的 java.util.Random 载荷，不读取旧汇总中的校验结果。
    state = ((seed + seq) ^ 0x5DEECE66D) & ((1 << 48) - 1)
    text, alphabet = f"RB1:{seq:012d}:", "abcdefghijklmnopqrstuvwxyz0123456789"
    while len(text) < size:
        state = (state * 0x5DEECE66D + 11) & ((1 << 48) - 1)
        bits = state >> 17
        index = bits % 36
        if bits - index + 35 < 2**31:
            text += alphabet[index]
    return text


def read_database(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", path
        return {"messages": [dict(row) for row in conn.execute("SELECT * FROM message")],
                "acks": [dict(row) for row in conn.execute("SELECT * FROM ack")]}


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    value = sum(struct.unpack("!" + "H" * (len(data)//2), data))
    while value >> 16:
        value = (value & 65535) + (value >> 16)
    return (~value) & 65535


def pcap_packets(path):
    # 不调用实验 runner 或其 PCAP 分析器，直接解析原始 Ethernet/IPv4/TCP。
    packets = []
    with path.open("rb") as stream:
        header = stream.read(24)
        formats = {b"\xd4\xc3\xb2\xa1": ("<", 1e6), b"\xa1\xb2\xc3\xd4": (">", 1e6),
                   b"\x4d\x3c\xb2\xa1": ("<", 1e9), b"\xa1\xb2\x3c\x4d": (">", 1e9)}
        assert len(header) == 24 and header[:4] in formats, path
        endian, scale = formats[header[:4]]
        assert struct.unpack(endian + "I", header[20:24])[0] == 1, path
        while record := stream.read(16):
            assert len(record) == 16
            sec, fraction, included, original = struct.unpack(endian + "IIII", record)
            data = stream.read(included)
            assert len(data) == included == original
            if len(data) < 54 or data[12:14] != b"\x08\x00" or data[23] != 6:
                continue
            tcp = 14 + (data[14] & 15)*4
            length = struct.unpack("!H", data[16:18])[0]
            segment = data[tcp:14+length]
            sport, dport, seq, ack = struct.unpack("!HHII", segment[:12])
            flags = segment[13]
            pseudo = data[26:34] + struct.pack("!BBH", 0, 6, len(segment))
            packets.append({"time": sec+fraction/scale,
                            "flow": [socket.inet_ntoa(data[26:30]), sport,
                                     socket.inet_ntoa(data[30:34]), dport],
                            "seq": seq, "ack": ack, "flags": flags,
                            "payload_bytes": len(segment)-(segment[12] >> 4)*4,
                            "rst_checksum_valid": checksum(pseudo+segment) == 0 if flags & 4 else None})
    return packets


def formal_rows(data):
    result = {}
    for row in data["messages"]:
        value = row.get("new_value") or ""
        if value.startswith("RB1:") and (seq := int(value.split(":", 2)[1])) >= 0:
            assert seq not in result, "同一序号出现多个消息 UUID"
            result[seq] = row
    return result


def log_hits(lines, fragments):
    return [{"line": i+1, "text": line} for i, line in enumerate(lines)
            if any(fragment in line for fragment in fragments)]


def socket_lines(event):
    return [line for name, value in event["states"].items() if name.startswith("rb-s-")
            for line in value.splitlines() if line.startswith("ESTAB")]


def audit_run(root, output):
    config = load(root / "config.json")
    condition = config["condition"]
    timeline = [json.loads(line) for line in (root / "timeline.ndjson").read_text().splitlines()]
    events = [json.loads(line) for path in [root / "publisher-0.jsonl", root / "subscriber-1.jsonl"]
              for line in path.read_text().splitlines()]
    submitted = {e["seq"] for e in events if e["event"] == "send" and e["seq"] >= 0}
    assert submitted == {0, 1, 2}, "正式提交量或序号不符"
    assert {e["seq"] for e in events if e["event"] == "write" and e["seq"] >= 0} == submitted, "正式写操作结果不完整"
    assert not any(e["event"] == "write" and not e["ok"] for e in events)
    assert not (root / "probe-failure.json").exists(), "该轮未完成"
    db = {p.name: read_database(p) for p in (root / "databases").glob("*.db")}
    rows = {name: formal_rows(data) for name, data in db.items()}
    assert f"server-{config['origin_server']}.db" in rows and "subscriber-1.db" in rows
    for name, table in rows.items():
        for seq, row in table.items():
            assert row["new_value"] == original_value(seq, config["size"], config["seed"]), (name, seq)
    logs = {p.name: p.read_text(errors="replace").splitlines() for p in (root / "logs").glob("*.log")}
    assert not any("SQLiteException" in line for lines in logs.values() for line in lines)
    captures = {point: pcap_packets(root / f"{point}.pcap") for point in ("traffic", "cluster", "peers")}
    for point in captures:
        match = re.search(r"(\d+) packets dropped by kernel", "\n".join(logs[f"{point}.log"]))
        assert match and int(match[1]) == 0, "抓包器丢包或统计缺失"
    faults = [e for e in timeline if e["kind"] != "snapshot"]
    snapshots = [e for e in timeline if e["kind"] == "snapshot"]
    assert all("read_error" not in d for e in snapshots for d in e["databases"].values())
    start = next((e["time"] for e in faults if e["kind"] == "blackhole_start"), None)
    end = next((e["time"] for e in faults if e["kind"] == "blackhole_end"), None)
    qdisc = next((e["output"] for e in faults if e["kind"] == "qdisc_before_restore"), "")
    dropped = max([int(n) for n in re.findall(r"dropped (\d+)", qdisc)] or [0])
    if start:
        assert end > start and dropped > 0, "未证明实际丢包"
    reset = next((e for e in faults if e["kind"] == "socket_reset"), None)
    rst_proof, reconnect_proof = [], []
    if "reset" in condition:
        assert reset and reset["original_connections_removed"]
        point = "traffic" if condition == "subscriber_reset" else "cluster"
        for source, sport, dest, dport, seq in reset["packets"]:
            hits = [p for p in captures[point] if p["flow"] == [source, sport, dest, dport]
                    and p["flags"] & 4 and p["seq"] == seq and p["rst_checksum_valid"]
                    and reset["time"]-5 <= p["time"] <= reset["time"]+.1]
            assert hits, "原始 PCAP 未找到指定 RST，或校验和无效"
            rst_proof.extend(hits)
    source_name = f"server-{config['origin_server']}.db"
    source_rows = rows[source_name]
    assert set(source_rows) == submitted, "源端没有保存全部正式更新"
    source_log = logs[f"server-{config['origin_server']}.log"]
    selected = {name: log_hits(lines, ["Disconnected.", "NullPointerException", "Reconnecting to", "Connected."])
                for name, lines in logs.items() if name.startswith(("server-", "subscriber-"))}
    premature = {}
    target_name = f"server-{config['target_server']}.db" if config.get("target_server") else None
    if target_name:
        for event in snapshots:
            if not start or not start <= event["time"] < end:
                continue
            state = event["databases"]
            source = state[source_name]
            target_ids = {row["uuid"] for row in state[target_name]["messages"]}
            ack_by_uuid = {ack["message_uuid"]: ack for ack in source["acks"]}
            for seq, row in formal_rows(source).items():
                ack = ack_by_uuid.get(row["uuid"])
                if ack and config["target_server"] in json.loads(ack["ack_nodes"] or "[]") and row["uuid"] not in target_ids:
                    premature.setdefault(seq, []).append({"time": event["time"], "uuid": row["uuid"], "ack": ack})
    premature_proof = {seq: {"first": samples[0], "last": samples[-1], "samples": len(samples),
                              "span_seconds": samples[-1]["time"]-samples[0]["time"]}
                       for seq, samples in premature.items()}
    final_ack = {ack["message_uuid"]: ack for ack in db[source_name]["acks"]}
    ack_proof = []
    for seq, row in source_rows.items():
        ack = final_ack.get(row["uuid"])
        if ack:
            expected, completed = set(json.loads(ack["node_list"])), set(json.loads(ack["ack_nodes"] or "[]"))
            ack_proof.append({"seq": seq, "uuid": row["uuid"], "node_list": sorted(expected),
                              "ack_nodes": sorted(completed), "computed_retry_nodes": sorted(expected-completed),
                              "sync_send_log_entries": log_hits(source_log, [f"Message UUID = {row['uuid']}"])})
    if condition == "cluster_blackhole_reset":
        old_ports = {p[1] for p in reset["packets"] if p[3] == reset["port"]}
        before = next(e for e in faults if e["kind"] == "sockets" and e["stage"] == "before_fault")
        owner_ids = {re.search(r"pid=(\d+),", line)[1] for line in socket_lines(before)
                     if int(line.split()[3].rsplit(":", 1)[1]) in old_ports}
        deadline = next(e for e in faults if e["kind"] == "sockets" and e["stage"] == "at_deadline")
        for line in socket_lines(deadline):
            fields = line.split()
            if (int(fields[4].rsplit(":", 1)[1]) == reset["port"]
                    and int(fields[3].rsplit(":", 1)[1]) not in old_ports
                    and any(f"pid={pid}," in line for pid in owner_ids)):
                reconnect_proof.append(line)
        assert reconnect_proof, "截止时未确认源服务端已经建立新的目标连接"
        assert any(f"Reconnecting to Node-{config['target_server']}" in line for line in source_log)
    received = {e["seq"] for e in events if e["event"] == "receive" and e["seq"] >= 0}
    put_success = {e["seq"] for e in events if e["event"] == "put_response" and e["ok"] and e["seq"] >= 0}
    npe_count = sum("java.lang.NullPointerException" in line for line in source_log)
    subscriber = set(rows["subscriber-1.db"])
    target = set(rows[target_name]) if target_name else None
    premature_all = set(premature) == submitted and all(p["span_seconds"] > 1 for p in premature_proof.values())
    if condition in ("subscriber_control", "subscriber_blackhole"):
        prediction = subscriber == received == put_success == submitted and npe_count == 0
        healthy = subscriber == submitted
    elif condition == "subscriber_reset":
        prediction = not subscriber and not received and not put_success and npe_count >= 3
        healthy = subscriber == submitted and npe_count == 0
    elif condition == "cluster_control":
        prediction = target == subscriber == received == put_success == submitted
        healthy = prediction
    elif condition == "cluster_blackhole":
        prediction = premature_all and target == submitted
        healthy = target == submitted and not premature
    else:
        prediction = (premature_all and not target and put_success == submitted and bool(reconnect_proof)
                      and len(ack_proof) == 3 and all(not p["computed_retry_nodes"] for p in ack_proof))
        healthy = target == submitted
    if condition.endswith("control"):
        assert healthy, "正常对照组未达到要求，不能继续故障归因"
    row = {"condition": condition, "directory": str(root), "submitted": len(submitted),
           "source_stored": len(source_rows), "subscriber_stored": len(subscriber),
           "subscriber_receive_events": len(received), "put_success": len(put_success),
           "replica_stored": len(target) if target is not None else None,
           "npe_count": npe_count, "tc_dropped": dropped,
           "premature_ack_sequences": sorted(premature), "rst_packets_verified": len(rst_proof),
           "reconnected_source_verified": bool(reconnect_proof),
           "healthy_target": "PASS" if healthy else "FAIL",
           "source_prediction": "MATCH" if prediction else "MISMATCH",
           "blackhole_seconds": round(end-start, 3) if start else None,
           "after_restore_seconds": round(config["deadline"]-end, 3) if end else None}
    save(output / f"{root.name}-raw-proof.json", {"result": row, "rst_packets": rst_proof,
         "premature_ack": premature_proof, "final_ack": ack_proof,
         "reconnect_socket_lines": reconnect_proof, "logs": selected, "qdisc": qdisc})
    return row


def bytecode_proof(root, output):
    jar = root / "assets/server/ripple-server.jar"
    classes = ["ripple.server.core.Node", "ripple.server.core.Tracker", "ripple.server.helper.Api",
               "ripple.server.core.Worker", "ripple.server.core.dispatcher.EqualDivisionClientDispatcher"]
    results = {}
    for name in classes:
        result = subprocess.run(["javap", "-p", "-c", "-classpath", str(jar), name],
                                text=True, capture_output=True, check=True)
        (output / f"{name}.javap.txt").write_text(result.stdout, encoding="utf-8")
        results[name] = result.stdout
    for name, signature in [(classes[0], "private void doSyncWithServer("),
                            (classes[1], "public void retrySending(")]:
        section = results[name].split(signature, 1)[1]
        section = re.split(r"\n  (?:public|private|protected) ", section)[0]
        sync = section.index("ripple/server/helper/Api.sync")
        ack = section.index("recordAck")
        assert sync < ack and "ChannelFuture" not in section, "运行 JAR 与提前 ACK 的代码路径不符"
    return {"jar": str(jar), "sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
            "initial_sync_then_record_ack": True, "retry_sync_then_record_ack": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--runs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    if options.suite:
        suite = options.suite.resolve()
        execution = load(suite / "execution.json")
        assert execution["exit_code"] == 0 and execution["inputs_unchanged"]
        assert execution["namespaces_before"] == execution["namespaces_after"], "隔离网络未清理"
        contract = load(suite / "expectations.json")
        runs = [suite / "runs" / name for name in contract["healthy_target"]]
        output = (options.output or suite / "audit").resolve()
    else:
        assert options.runs and options.output
        runs, output = [p.resolve() for p in options.runs], options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = [audit_run(root, output) for root in runs]
    bytecode = bytecode_proof(runs[0], output)
    for root in runs:
        assert hashlib.sha256((root / "assets/server/ripple-server.jar").read_bytes()).hexdigest() == bytecode["sha256"]
    save(output / "expected-actual.json", {"valid_runs": len(rows), "runs": rows, "runtime_bytecode": bytecode})
    with (output / "expected-actual.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save(output / "audit-sha256.json", {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in output.iterdir() if path.is_file() and path.name != "audit-sha256.json"})
    print(json.dumps({"valid_runs": len(rows), "results": rows}, ensure_ascii=False, indent=2))
    # MATCH 表示预测得到复现；healthy_target=FAIL 明确表示可靠性目标未达成。
    if any(row["source_prediction"] != "MATCH" for row in rows):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
