"""在独立网络中调用原版 Ripple 发行包，并输出可复核的带宽实验。"""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

from capture import analyze_pcap, window_totals
from metrics import parse_bandwidth, summarize, time_series, validate
from support import code_identity, content_integrity, dependency_identity, drain_complete, file_sha256, git_commit, server_log_warnings, wire_options

HERE = Path(__file__).resolve().parent


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_events(root, live=True):
    events = []
    for path in root.glob("*.jsonl"):
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for index, line in enumerate(lines):
            if live and index == len(lines)-1 and not line.endswith("\n"):
                continue
            try:
                event = json.loads(line)
                if not {"event", "seq", "id", "time"}.issubset(event) or not math.isfinite(event["time"]):
                    raise ValueError("缺少事件字段或时间无效")
                events.append(event)
            except (json.JSONDecodeError, TypeError, ValueError) as failure:
                raise ValueError(f"事件文件损坏：{path.name} 第 {index+1} 行：{failure}") from failure
    return events


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class Experiment:
    def __init__(self, args, root):
        self.args, self.root = args, root
        self.processes, self.captures, self.files, self.namespaces = [], [], [], []
        self.runtime = tempfile.TemporaryDirectory(prefix="ripple-bandwidth-")
        self.database_root = Path(self.runtime.name)
        self.config = dict(vars(args), run_id=root.name, clock="同一 WSL 系统时钟，Java Instant.now()",
                           latency_boundary="原版客户端业务处理器返回后；包含存储处理时间",
                           bandwidth_scope="服务端到全部订阅者的共享下行；反向不限制",
                           protocol="hashing", capture_points="订阅侧 veth、服务端 lo、订阅侧 lo，各链路单点计数")
        self.config = {key: str(value) if isinstance(value, Path) else value for key, value in self.config.items()}
        self.config["database_runtime_directory"] = str(self.database_root)
        self.config.update(code_identity(args.ripple_root))
        self.config["tool_git_commit"] = git_commit(HERE)
        self.config["wire_jvm_options"] = wire_options(args.wire_mode)
        self.config["database_storage"] = "运行时使用 Linux 临时目录，结束后复制到结果目录 databases/"
        token = uuid.uuid4().hex[:8]
        self.server_ns, self.client_ns = "rb-s-"+token, "rb-c-"+token
        self.server_ip, self.client_ip = "10.203.0.1", "10.203.0.2"
        self.nodes = ",".join(f"{i}:{self.server_ip}:{13000+i}" for i in range(1, args.servers+1))
        self.app = "bench_"+token

    def command(self, argv, namespace=None, **kwargs):
        if namespace:
            argv = ["ip", "netns", "exec", namespace] + list(argv)
        return subprocess.run(argv, check=True, text=True, capture_output=True, **kwargs)

    def spawn(self, argv, namespace, name, capture=False):
        stream = (self.root/"logs"/(name+".log")).open("w", encoding="utf-8")
        self.files.append(stream)
        process = subprocess.Popen(["ip", "netns", "exec", namespace]+list(argv), stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        (self.captures if capture else self.processes).append((name, process))
        return process

    def check_alive(self):
        warnings = server_log_warnings(self.root/"logs")
        if warnings:
            self.config["measurement_warnings"] = warnings
            self.config["server_log_scan_stage"] = "live"
            raise RuntimeError("运行期间检测到服务日志异常：" + "; ".join(warnings))
        for name, process in self.processes+self.captures:
            if process.poll() is not None:
                raise RuntimeError(f"进程 {name} 提前退出，请查看 logs/{name}.log")

    def wait(self, condition, description, timeout=45):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            self.check_alive()
            if condition():
                return
            time.sleep(.1)
        raise RuntimeError(f"等待超时：{description}")

    def topology(self):
        for namespace in (self.server_ns, self.client_ns):
            self.command(["ip", "netns", "add", namespace])
            self.namespaces.append(namespace)
            self.command(["ip", "link", "set", "lo", "up"], namespace)
        self.command(["ip", "link", "add", "bench0", "type", "veth", "peer", "name", "bench1"], self.server_ns)
        self.command(["ip", "link", "set", "bench1", "netns", self.client_ns], self.server_ns)
        self.command(["ip", "link", "set", "bench1", "name", "bench0"], self.client_ns)
        for namespace, address in ((self.server_ns, self.server_ip), (self.client_ns, self.client_ip)):
            self.command(["ip", "addr", "add", address+"/30", "dev", "bench0"], namespace)
            self.command(["ip", "link", "set", "bench0", "up"], namespace)
        # 关闭测试接口的分段/聚合卸载，便于逐帧带宽核算；仅作用于新建接口。
        self.config["offload"] = {}
        if shutil.which("ethtool"):
            for namespace in self.namespaces:
                result = subprocess.run(["ip", "netns", "exec", namespace, "ethtool", "-K", "bench0",
                                         "tso", "off", "gso", "off", "gro", "off"], capture_output=True, text=True)
                self.config["offload"][namespace] = {"disabled": result.returncode == 0, "detail": result.stderr}
        else:
            self.config["offload"]["warning"] = "未安装 ethtool，抓包可能受聚合卸载影响，不应当作物理线速"

    def artifacts(self):
        for role in ("server", "client"):
            archive = self.args.ripple_root/f"ripple-{role}"/"target"/f"ripple-{role}-publish.tar.gz"
            target = self.root/"assets"/role
            target.mkdir(parents=True)
            with tarfile.open(archive) as source:
                source.extractall(target, filter="data")
        classes = self.root/"classes"
        classes.mkdir()
        client = self.root/"assets"/"client"
        classpath = f"{client}/ripple-client.jar:{client}/lib/*"
        self.command(["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8",
                      "-cp", classpath, "-d", str(classes), str(HERE/"java"/"Driver.java")])
        self.classpath = f"{classes}:{classpath}"
        if self.args.staged_start:
            server = self.root/"assets"/"server"
            self.server_classpath = f"{classes}:{server}/ripple-server.jar:{server}/lib/*"
            self.command(["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8",
                "-cp", self.server_classpath, "-d", str(classes), str(HERE/"java/ServerDriver.java")])
        self.config["java_version"] = self.command(["java", "-version"]).stderr.strip()
        self.config["python_version"] = sys.version
        self.config["jar_sha256"] = {role: file_sha256(
            self.root/"assets"/role/f"ripple-{role}.jar") for role in ("server", "client")}
        self.config["dependency_sha256"] = dependency_identity(self.root/"assets")

    def capture(self):
        definitions = [(self.client_ns, "bench0", "traffic", "tcp"),
                       (self.server_ns, "lo", "cluster", "tcp and (portrange 13001-13020 or port 15000)"),
                       (self.client_ns, "lo", "peers", "tcp and portrange 15001-15100")]
        for namespace, interface, name, expression in definitions:
            self.spawn(["tcpdump", "-Z", "root", "-i", interface, "-nn", "-s", "0", "-U",
                        "-w", str(self.root/(name+".pcap")), expression], namespace, name, True)
            self.wait(lambda name=name: "listening on" in (self.root/"logs"/(name+".log")).read_text(),
                      "抓包器启动", 10)

    def start_services(self):
        jar = self.root/"assets"/"server"/"ripple-server.jar"
        staged = getattr(self.args, "staged_start", False)
        launch = ["-cp", self.server_classpath, "ServerDriver", str(self.root)] if staged else ["-jar", str(jar)]
        for server in range(1, self.args.servers+1):
            self.spawn(["java"] + wire_options(self.args.wire_mode) + ["-Dio.netty.eventLoopThreads=2", "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
                        f"-Did={server}", f"-Daddress={self.server_ip}", f"-DapiPort={13000+server}", "-DuiPort=0",
                        f"-DstorageLocation={self.database_root}/server-{server}.db", f"-Dnodes={self.nodes}",
                        "-Dprotocol=hashing", f"-DcandidateCount={self.args.servers}"] + launch,
                       self.server_ns, f"server-{server}")
        def ports_ready():
            result = self.command(["ss", "-ltnH"], self.server_ns)
            listening = set()
            for line in result.stdout.splitlines():
                fields = line.split()
                if len(fields) >= 4:
                    host, _, port = fields[3].rpartition(":")
                    host = host.strip("[]").removeprefix("::ffff:")
                    if host in (self.server_ip, "0.0.0.0", "::", "*"):
                        listening.add(port)
            return all(str(13000+i) in listening for i in range(1, self.args.servers+1))
        if staged:
            self.wait(lambda: all((self.root/f"server-{i}.listening").exists()
                for i in range(1, self.args.servers+1)), "全部服务监听")
            (self.root/"cluster.start").touch()
            self.wait(lambda: all((self.root/f"server-{i}.ready").exists()
                for i in range(1, self.args.servers+1)), "全部集群初始化")
        else:
            self.wait(ports_ready, "服务端 API 端口")
            # 原版启动重连窗口中也及时发现异常，避免日志风暴。
            for _ in range(110):
                self.check_alive()
                time.sleep(.1)
        for subscriber in range(1, self.args.subscribers+1):
            self.driver("subscriber", subscriber, self.client_ns, self.client_ip)
            # 原版服务端的连接表是 ArrayList，避免同时握手触发并发添加竞态。
            self.wait(lambda subscriber=subscriber: (self.root/f"subscriber-{subscriber}.ready").exists(),
                      f"订阅者 {subscriber} 就绪")
        self.driver("publisher", 0, self.server_ns, self.server_ip)
        self.wait(lambda: all((self.root/f"subscriber-{i}.ready").exists()
                             for i in range(1, self.args.subscribers+1))
                  and (self.root/"publisher-0.ready").exists(), "订阅确认及回调观测器就绪")
        last_probe = [0.0]
        def probe_received():
            got = {e["id"] for e in read_events(self.root) if e["event"] == "receive" and e["seq"] == -1}
            if len(got) == self.args.subscribers:
                return True
            # DISPATCH 首次转发会新建客户端连接，用重复暖机确保观测器已安装。
            if time.monotonic()-last_probe[0] >= 1:
                (self.root/"probe").touch()
                last_probe[0] = time.monotonic()
            return False
        self.wait(probe_received, "全部订阅者收到探测消息")

    def driver(self, role, identifier, namespace, address):
        self.spawn(["java"] + wire_options(self.args.wire_mode) + ["-Dio.netty.eventLoopThreads=2", "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
                    "-cp", self.classpath, "Driver", role, address, self.nodes, str(self.root), self.app,
                    str(identifier), str(self.args.size), str(self.args.rate), str(self.args.duration),
                    str(self.args.seed), str(self.database_root), self.args.payload], namespace, f"{role}-{identifier}")

    def shape(self):
        if not self.args.bandwidth:
            return
        rate = str(parse_bandwidth(self.args.bandwidth))+"bit"
        commands = [["qdisc", "add", "dev", "bench0", "root", "handle", "1:", "htb", "default", "10"],
                    ["class", "add", "dev", "bench0", "parent", "1:", "classid", "1:10", "htb",
                     "rate", rate, "ceil", rate, "burst", "1600", "cburst", "1600"],
                    ["qdisc", "add", "dev", "bench0", "parent", "1:10", "handle", "10:",
                     "bfifo", "limit", str(self.args.queue_bytes)]]
        for arguments in commands:
            self.command(["tc"]+arguments, self.server_ns)
        self.config["bandwidth_bps"] = parse_bandwidth(self.args.bandwidth)
        self.tc_stats("configured")

    def tc_stats(self, stage):
        path = self.root/"tc-stats.json"
        stats = json.loads(path.read_text()) if path.exists() else {}
        stats[stage] = {kind: json.loads(self.command(["tc", "-s", "-j", kind, "show", "dev", "bench0"],
                                                     self.server_ns).stdout)
                        for kind in ("qdisc", "class")}
        write_json(path, stats)

    def run(self):
        print(f"结果目录：{self.root}", flush=True)
        self.artifacts()
        self.topology()
        self.capture()
        print("启动独立集群并等待订阅探测……", flush=True)
        self.start_services()
        self.config["baseline_start"] = time.time()
        time.sleep(self.args.baseline_duration)
        self.config["baseline_end"] = time.time()
        self.shape()
        self.config["measurement_warnings"] = server_log_warnings(self.root/"logs")
        self.config["server_log_scan_stage"] = "before_send"
        write_json(self.root/"config.json", self.config)
        if self.config["measurement_warnings"]:
            raise RuntimeError("正式发送前检测到服务日志异常：" + "; ".join(self.config["measurement_warnings"]))
        print("开始发送模拟消息……", flush=True)
        (self.root/"start").touch()
        self.wait(lambda: (self.root/"publisher.sent").exists(), "发送结束", self.args.duration+30)
        events = read_events(self.root)
        self.config["send_start"] = next(e["time"] for e in events if e["event"] == "load_start")
        self.config["send_end"] = next(e["time"] for e in events if e["event"] == "load_end")
        self.config["planned_messages"] = math.ceil(self.args.rate*self.args.duration)
        drain_end = time.monotonic()+self.args.drain_timeout
        while True:
            self.check_alive()
            events = read_events(self.root)
            result = summarize(events, self.args.subscribers, self.args.size,
                               self.config["send_start"], self.config["send_end"], time.time())
            if drain_complete(result, self.args.fixed_drain, time.monotonic(), drain_end):
                break
            time.sleep(.1)
        self.config["measurement_server_log_sizes"] = {path.name: path.stat().st_size
            for path in (self.root/"logs").glob("server-*.log")}
        self.config["measurement_warnings"] = server_log_warnings(
            self.root/"logs", self.config["measurement_server_log_sizes"])
        self.config["server_log_scan_stage"] = "measurement_deadline_before_shutdown"
        self.config["deadline"] = time.time()
        self.tc_stats("at_deadline")
        (self.root/"stop").touch()
        for name, process in self.processes:
            if not name.startswith("server-"):
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired as failure:
                    raise RuntimeError(f"驱动 {name} 未能正常结束，不能确认事件完整性") from failure
                if process.returncode != 0:
                    raise RuntimeError(f"驱动 {name} 异常结束，请检查对应日志")
        self.stop_captures()
        write_json(self.root/"config.json", self.config)
        return self.report()

    def stop_captures(self):
        for _, process in self.captures:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    def report(self):
        events = read_events(self.root, live=False)
        start, end, deadline = (self.config[key] for key in ("send_start", "send_end", "deadline"))
        summary = summarize(events, self.args.subscribers, self.args.size, start, end, deadline)
        summary.update(content_integrity(events, deadline))
        summary["planned_messages"] = self.config["planned_messages"]
        summary["send_duration_s"], summary["drain_duration_s"] = end-start, deadline-end
        summary["scheduling_lag_ms_max"] = max((e["lag_ms"] for e in events if e["event"] == "send"), default=None)
        summary["write_failures"] = sum(e["event"] == "write" and not e["ok"] for e in events)
        summary["measurement_warnings"] = server_log_warnings(
            self.root/"logs", self.config.get("measurement_server_log_sizes"))
        summary["server_log_scan_stage"] = self.config.get("server_log_scan_stage", "report")
        if summary["corrupt_content"]:
            summary["measurement_warnings"].append("收到的载荷与确定性原文不一致")
        captures, flow_rows, packet_rows = {}, [], []
        for point in ("traffic", "cluster", "peers"):
            capture = analyze_pcap(self.root/(point+".pcap"))
            capture["windows"] = {name: window_totals(capture["packets"], left, right) for name, left, right in
                                  (("baseline", self.config["baseline_start"], self.config["baseline_end"]),
                                   ("send", start, end), ("send_and_drain", start, deadline))}
            if point == "traffic":
                downlink = [p for p in capture["packets"] if p["flow"][0] == self.server_ip]
                capture["downlink_send"] = window_totals(downlink, start, end)
                capture["downlink_send_and_drain"] = window_totals(downlink, start, deadline)
            for flow in capture.pop("flows"):
                flow["capture_point"] = point
                flow["message_counts"] = json.dumps(flow["message_counts"], ensure_ascii=False)
                flow_rows.append(flow)
            packet_rows.extend(capture.pop("packets"))
            log = (self.root/"logs"/(point+".log")).read_text()
            dropped = re.search(r"(\d+) packets dropped by kernel", log)
            capture["kernel_dropped_packets"] = int(dropped[1]) if dropped else None
            if not dropped or int(dropped[1]):
                summary["measurement_warnings"].append(f"{point} 抓包丢包统计缺失或非零")
            summary["measurement_warnings"].extend(capture["decode_issues"])
            captures[point] = capture
        if summary["negative_latency_samples"]:
            summary["measurement_warnings"].append("存在负延迟，系统时钟可能跳变")
        if summary["submitted"] == 0:
            summary["measurement_warnings"].append("未实际提交任何测试消息，不能评价稳定性")
        summary["captures"] = captures
        summary["status"] = "complete" if not summary["measurement_warnings"] else "measurement_incomplete"
        summary["stability"] = ("no_load" if summary["submitted"] == 0 else
                                "all_delivered" if summary["missing_at_deadline"] == 0 else "pending_at_deadline")
        summary["total_send_and_drain_frame_bytes"] = sum(c["windows"]["send_and_drain"]["frame_bytes"] for c in captures.values())
        summary["total_send_and_drain_tcp_payload_bytes"] = sum(c["windows"]["send_and_drain"]["tcp_payload_bytes"] for c in captures.values())
        summary["frame_bytes_per_submission"] = summary["total_send_and_drain_frame_bytes"]/summary["submitted"] if summary["submitted"] else None
        rows = time_series(events, packet_rows, start, end, deadline, self.args.subscribers)
        write_csv(self.root/"timeseries.csv", rows, ["second", "duration_s", "stage", "submitted", "received_unique",
                  "pending", "frame_bytes", "tcp_payload_bytes", "frame_bps", "tcp_payload_bps"])
        write_csv(self.root/"messages.csv", sorted(events, key=lambda e: e["time"]),
                  ["event", "id", "seq", "time", "uuid", "ok", "lag_ms"])
        write_csv(self.root/"flows.csv", flow_rows, ["capture_point", "src_ip", "src_port", "dst_ip", "dst_port",
                  "frame_bytes", "tcp_payload_bytes", "unique_tcp_payload_bytes", "message_counts"])
        write_json(self.root/"summary.json", summary)
        print(json.dumps({key: summary[key] for key in ("status", "submitted", "put_success", "received_unique",
              "expected_deliveries", "missing_at_deadline", "delivery_ratio", "corrupt_content", "latency_ms")}, ensure_ascii=False, indent=2), flush=True)
        return summary

    def cleanup(self):
        (self.root/"stop").touch()
        self.stop_captures()
        for _, process in reversed(self.processes):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for _, process in reversed(self.processes):
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        for namespace in reversed(self.namespaces):
            subprocess.run(["ip", "netns", "del", namespace], capture_output=True)
        for stream in self.files:
            stream.close()
        shutil.copytree(self.database_root, self.root/"databases", dirs_exist_ok=True)
        self.runtime.cleanup()


def argument_parser():
    parser = argparse.ArgumentParser(description="外部调用原版 Ripple：负载、带宽与限速稳定性测试")
    for name, kind, default in (("size", int, 1024), ("rate", float, 100), ("duration", float, 60),
                                ("subscribers", int, 1), ("servers", int, 3), ("drain-timeout", float, 30),
                                ("baseline-duration", float, 10), ("seed", int, 42), ("queue-bytes", int, 1048576)):
        parser.add_argument("--"+name, type=kind, default=default)
    parser.add_argument("--bandwidth", help="共享订阅下行，例如 64kbit 或 1mbit")
    parser.add_argument("--ripple-root", type=Path, default=HERE.parent/"Ripple")
    parser.add_argument("--output", type=Path, default=HERE/"results")
    parser.add_argument("--wire-mode", choices=("legacy", "compact", "adaptive"), default="legacy")
    parser.add_argument("--payload", choices=("random", "structured"), default="random")
    parser.add_argument("--fixed-drain", action="store_true", help="始终等待完整排空期限")
    parser.add_argument("--staged-start", action="store_true", help="先监听全部节点再初始化集群")
    return parser


def main():
    parser = argument_parser()
    args = parser.parse_args()
    try:
        validate(args.size, args.rate, args.duration, args.subscribers, args.servers)
        for value in (args.drain_timeout, args.baseline_duration):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("基线时长和排空期限必须为有限正数")
        if args.queue_bytes < 1600:
            raise ValueError("整形队列至少需要 1600 字节")
        if args.bandwidth:
            parse_bandwidth(args.bandwidth)
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("请在 WSL/Linux 内使用 sudo bash run.sh 运行，隔离网络与抓包需要 root")
        for tool in ("ip", "tc", "ss", "tcpdump", "java", "javac"):
            if not shutil.which(tool):
                raise ValueError(f"缺少工具：{tool}")
        args.ripple_root = args.ripple_root.resolve()
        for role in ("server", "client"):
            if not (args.ripple_root/f"ripple-{role}"/"target"/f"ripple-{role}-publish.tar.gz").is_file():
                raise ValueError(f"缺少 {role} 发行包，请先在 Ripple 项目中运行 mvn install")
    except ValueError as failure:
        parser.error(str(failure))
    root = args.output.resolve()/(time.strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:6])
    (root/"logs").mkdir(parents=True)
    experiment = Experiment(args, root)
    write_json(root/"config.json", experiment.config)
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    previous_term = signal.signal(signal.SIGTERM, interrupted)
    try:
        summary = experiment.run()
        return 0 if summary["status"] == "complete" else 2
    except (Exception, KeyboardInterrupt) as failure:
        detail = "用户中断测试" if isinstance(failure, KeyboardInterrupt) else str(failure)
        if isinstance(failure, subprocess.CalledProcessError):
            detail += "\n" + (failure.stderr or "")
        write_json(root/"summary.json", {"status": "interrupted" if isinstance(failure, KeyboardInterrupt) else "failed",
                   "error": detail, "result_directory": str(root),
                   "measurement_warnings": experiment.config.get("measurement_warnings", [])})
        write_json(root/"config.json", experiment.config)
        print(f"测试未完成：{detail}；日志保留在 {root}", file=sys.stderr)
        return 130 if isinstance(failure, KeyboardInterrupt) else 1
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        experiment.cleanup()
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    sys.exit(main())
