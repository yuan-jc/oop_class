"""在独立命名空间中验证原版 Ripple 的断联恢复，保留数据库、抓包和时间线。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import traceback

import runner
from raw_tcp_reset import reset_targets


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def database(path):
    # 只读连接，不添加触发器或改变应用存储策略。
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.2) as conn:
        conn.row_factory = sqlite3.Row
        return {"messages": [dict(row) for row in conn.execute("SELECT * FROM message")],
                "acks": [dict(row) for row in conn.execute("SELECT * FROM ack")],
                "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0]}


class Probe(runner.Experiment):
    def spawn(self, argv, namespace, name, capture=False):
        # 仅提高实验进程日志级别，便于追踪连接、重发及 ACK。
        argv = [arg.replace("defaultLogLevel=warn", "defaultLogLevel=info") for arg in argv]
        return super().spawn(argv, namespace, name, capture)

    def record(self, kind, **values):
        event = {"time": time.time(), "kind": kind, **values}
        with (self.root / "timeline.ndjson").open("a", encoding="utf-8") as out:
            out.write(json.dumps(event, ensure_ascii=False) + "\n")

    def snapshot(self, stage):
        state = {}
        for path in self.database_root.glob("*.db"):
            try:
                state[path.name] = database(path)
            except sqlite3.Error as error:
                state[path.name] = {"read_error": str(error)}
        self.record("snapshot", stage=stage, databases=state)
        return state

    def sockets(self, stage):
        self.record("sockets", stage=stage, states={ns: self.command(
            ["ss", "-tinp"], ns).stdout for ns in self.namespaces})

    def cut_socket(self, port):
        # WSL 的 ss -K 不可靠，使用已捕获的确认号向连接两端注入 RST。
        capture = self.root / ("traffic.pcap" if port == 15001 else "cluster.pcap")
        targets = reset_targets(capture, port)
        if port != 15001:
            # 仅断开源服务端到副本的连接，排除同端口上的客户端监控连接和自连接。
            owner = next(process.pid for name, process in self.processes
                         if name == f"server-{self.config['origin_server']}")
            active = self.command(["ss", "-tnp", "dport", "=", str(port)], self.server_ns).stdout
            ports = {int(line.split()[3].rsplit(":", 1)[1]) for line in active.splitlines()[1:]
                     if re.search(rf"pid={owner},", line)}
            targets = [t for t in targets if (t[1] in ports and t[3] == port)
                       or (t[1] == port and t[3] in ports)]
            if not ports or not targets:
                raise RuntimeError("未找到源服务端持有的副本连接")
        for source, sport, dest, dport, seq in targets:
            namespace = self.client_ns if source == self.client_ip else self.server_ns
            self.command([sys.executable, str(runner.HERE / "raw_tcp_reset.py"), source,
                          str(sport), dest, str(dport), str(seq)], namespace)
        time.sleep(.3)
        states = self.command(["ss", "-tn", "dport", "=", str(port)], self.server_ns).stdout
        old_ports = {t[1] for t in targets if t[3] == port}
        remaining = {int(line.split()[3].rsplit(":", 1)[1]) for line in states.splitlines()[1:]}
        if old_ports & remaining:
            raise RuntimeError("RST 后原连接仍存在，拒绝认定注入成功")
        self.record("socket_reset", port=port, packets=targets, sockets_after=states,
                    original_connections_removed=True)

    def blackhole(self, cluster, port=None):
        interface = "lo" if cluster else "bench0"
        if cluster:
            self.command(["tc", "qdisc", "add", "dev", interface, "root", "handle", "1:",
                          "prio", "bands", "3", "priomap"] + ["0"] * 16, self.server_ns)
            self.command(["tc", "qdisc", "add", "dev", interface, "parent", "1:3",
                          "handle", "30:", "netem", "loss", "100%"], self.server_ns)
            for direction in ("sport", "dport"):
                self.command(["tc", "filter", "add", "dev", interface, "parent", "1:",
                              "protocol", "ip", "prio", "1", "u32", "match", "ip", "protocol", "6", "0xff",
                              "match", "ip", direction, str(port), "0xffff", "flowid", "1:3"], self.server_ns)
        else:
            self.command(["tc", "qdisc", "add", "dev", interface, "root", "netem", "loss", "100%"],
                         self.server_ns)
        self.record("blackhole_start", interface=interface, port=port)
        return interface

    def unblock(self, interface):
        self.record("qdisc_before_restore", output=self.command(
            ["tc", "-s", "qdisc", "show", "dev", interface], self.server_ns).stdout)
        self.command(["tc", "qdisc", "del", "dev", interface, "root"], self.server_ns)
        self.record("blackhole_end", interface=interface)

    def execute(self, condition):
        self.artifacts()
        self.topology()
        self.capture()
        self.start_services()
        self.config["baseline_start"] = time.time()
        time.sleep(1)
        self.config["baseline_end"] = time.time()
        self.config["condition"] = condition
        initial = self.snapshot("before_fault")
        cluster = condition.startswith("cluster")
        origin = next(row["last_update_id"] for data in initial.values()
                      for row in data.get("messages", []) if (row.get("new_value") or "").startswith("RB1:"))
        target = 3 - origin if cluster else None
        self.config.update(origin_server=origin, target_server=target)
        self.sockets("before_fault")
        interface = None
        if "blackhole" in condition:
            interface = self.blackhole(cluster, 13000 + target if cluster else None)
        if condition == "subscriber_reset":
            self.cut_socket(15001)
            time.sleep(.5)
        write_config = lambda: save(self.root / "config.json", self.config)
        write_config()
        begin = time.monotonic()
        (self.root / "start").touch()
        restored, reset = interface is None, False
        fault_seconds = 22 if cluster else 6
        # 固定观察到恢复后 30 秒，避免工具因提前送达而跳过恢复观测。
        observe_seconds = (fault_seconds if interface else 6) + 30
        while time.monotonic() - begin < observe_seconds:
            self.check_alive()
            elapsed = time.monotonic() - begin
            if interface and not restored and elapsed >= fault_seconds:
                self.sockets("before_restore")
                self.unblock(interface)
                if condition == "cluster_blackhole_reset":
                    self.cut_socket(13000 + target)
                    reset = True
                restored = True
            self.snapshot("observing")
            time.sleep(.25)
        self.sockets("at_deadline")
        self.snapshot("at_deadline")
        events = runner.read_events(self.root)
        self.config["send_start"] = next(e["time"] for e in events if e["event"] == "load_start")
        self.config["send_end"] = next(e["time"] for e in events if e["event"] == "load_end")
        self.config["planned_messages"] = 3
        self.config["deadline"] = time.time()
        (self.root / "stop").touch()
        for name, process in self.processes:
            if not name.startswith("server-"):
                process.wait(timeout=15)
                if process.returncode:
                    raise RuntimeError(f"驱动异常结束：{name}")
        self.stop_captures()
        write_config()
        self.report()


def analyze(root):
    config = json.loads((root / "config.json").read_text())
    events = runner.read_events(root, live=False)
    submitted = sorted({e["seq"] for e in events if e["event"] == "send" and e["seq"] >= 0})
    timeline = [json.loads(line) for line in (root / "timeline.ndjson").read_text().splitlines()]
    seen, payloads, mismatches, premature = {}, {}, [], []
    for event in timeline:
        if event["kind"] != "snapshot":
            continue
        state = event["databases"]
        for name, data in state.items():
            for row in data.get("messages", []):
                value = row.get("new_value") or ""
                if not value.startswith("RB1:"):
                    continue
                seq = int(value.split(":", 2)[1])
                if seq < 0:
                    continue
                seen.setdefault(name, set()).add(seq)
                digest = hashlib.sha256(value.encode()).hexdigest()
                expected = payloads.setdefault(seq, digest)
                if expected != digest:
                    mismatches.append({"database": name, "seq": seq, "time": event["time"]})
        target = config.get("target_server")
        if target:
            source = state.get(f"server-{config['origin_server']}.db", {})
            dest = state.get(f"server-{target}.db", {})
            if "read_error" in source or "read_error" in dest:
                continue
            target_uuids = {row["uuid"] for row in dest.get("messages", [])}
            source_rows = {row["uuid"]: row for row in source.get("messages", [])}
            for ack in source.get("acks", []):
                row = source_rows.get(ack["message_uuid"])
                if row and (row.get("new_value") or "").startswith("RB1:"):
                    seq = int(row["new_value"].split(":", 2)[1])
                    if seq >= 0 and target in json.loads(ack["ack_nodes"] or "[]") and row["uuid"] not in target_uuids:
                        premature.append({"time": event["time"], "seq": seq, "uuid": row["uuid"], "ack": ack})
    final = {path.name: database(path) for path in (root / "databases").glob("*.db")}
    logs = {}
    for path in (root / "logs").glob("*.log"):
        selected = [line for line in path.read_text(errors="replace").splitlines()
                    if any(text in line for text in ("Disconnected.", "Reconnecting to", "Send HEARTBEAT request",
                                                     "Retry sync", "Exception", "unreachable"))]
        if selected:
            logs[path.name] = selected
    save(root / "selected-logs.json", logs)
    result = {"condition": config["condition"], "directory": str(root), "submitted_sequences": submitted,
              "successful_put_responses": sorted({e["seq"] for e in events if e["event"] == "put_response" and e["ok"] and e["seq"] >= 0}),
              "database_seen_sequences": {name: sorted(values) for name, values in seen.items()},
              "database_missing_sequences": {name: sorted(set(submitted) - seen.get(name, set())) for name in final if name != "publisher-0.db"},
              "payload_mismatches": mismatches, "observed_payload_sha256": payloads,
              "premature_ack_samples": premature, "final_databases": final,
              "fault_events": [e for e in timeline if e["kind"] != "snapshot"],
              "snapshot_read_errors": sum("read_error" in d for e in timeline if e["kind"] == "snapshot" for d in e["databases"].values()),
              "sql_error_count": sum("SQLiteException" in line for lines in logs.values() for line in lines)}
    save(root / "disconnect-evidence.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--conditions", nargs="+", default=["subscriber_control", "subscriber_blackhole", "subscriber_reset",
                                                           "cluster_control", "cluster_blackhole", "cluster_blackhole_reset"])
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=False)
    manifest = {"purpose": "原版 Ripple 断联恢复实测", "runs": []}
    for condition in options.conditions:
        root = options.output / condition
        (root / "logs").mkdir(parents=True)
        args = argparse.Namespace(size=256, rate=.5, duration=6, subscribers=1,
                                  servers=2 if condition.startswith("cluster") else 1,
                                  drain_timeout=30, baseline_duration=1, seed=42, queue_bytes=1048576,
                                  bandwidth=None, ripple_root=runner.HERE.parent / "Ripple", output=options.output)
        probe = Probe(args, root)
        print(f"开始 {condition}", flush=True)
        success = False
        try:
            probe.execute(condition)
            success = True
        except BaseException as error:
            traceback.print_exc()
            save(root / "probe-failure.json", {"error": str(error)})
        finally:
            probe.cleanup()
        if not success:
            raise RuntimeError(f"实验未完成：{condition}")
        result = analyze(root)
        manifest["runs"].append(result)
        save(options.output / "manifest.json", manifest)
        print(json.dumps({k: result[k] for k in ("condition", "database_seen_sequences", "database_missing_sequences",
                                                "payload_mismatches", "sql_error_count")}, ensure_ascii=False), flush=True)
    hashes = {}
    for path in [Path(__file__), runner.HERE / "raw_tcp_reset.py", runner.HERE / "runner.py", runner.HERE / "java/Driver.java"] + list(
            (runner.HERE.parent / "Ripple").glob("ripple-*/target/*publish.tar.gz")):
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    save(options.output / "provenance.json", hashes)


if __name__ == "__main__":
    main()
