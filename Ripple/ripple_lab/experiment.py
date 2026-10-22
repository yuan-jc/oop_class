"""真实 JVM、独立网络、暖机与固定观察窗口的实验生命周期。"""
import copy
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import traceback

from .build import build
from .event_store import EventStore
from .network import Network


class Experiment:
    def __init__(self, root, run_id, config, base_url):
        self.root = Path(root) / "runs" / run_id
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ("events", "control", "logs", "captures"):
            (self.root / folder).mkdir(exist_ok=True)
        self.id, self.config, self.base_url = run_id, config, base_url
        self.lock = threading.RLock()
        self.store = EventStore(self.root / "events.sqlite")
        self.cancel = threading.Event()
        self.processes, self.captures, self.handles, self.proxies = [], [], [], []
        self.network = None
        self.state = dict(id=run_id, name=config["name"], status="preparing", stage="checking",
                          started_at=time.time(), ended_at=None, config=config, nodes=[],
                          summary={}, warnings=[], version={}, error=None)
        self.series, self.last_metrics = [], 0
        self.save()

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def save(self):
        with self.lock:
            path = self.root / "state.tmp"
            path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
            path.replace(self.root / "state.json")

    def update(self, **values):
        with self.lock:
            self.state.update(values)
            self.save()

    def warn(self, message):
        with self.lock:
            if message not in self.state["warnings"]:
                self.state["warnings"].append(message)

    def start(self):
        self.thread = threading.Thread(target=self.run, name="实验-"+self.id)
        self.thread.start()

    def stop_sending(self):
        (self.root / "control/stop_sending").touch()

    def stop(self):
        self.cancel.set()
        (self.root / "control/stop").touch()

    def tick(self, check=True):
        for error in self.store.ingest(self.root / "events"):
            self.warn(error)
        if check:
            if self.cancel.is_set():
                raise InterruptedError("用户终止了实验")
            for node, process in self.processes:
                if process.poll() is not None:
                    raise RuntimeError(f"节点 {node} 提前退出，退出码 {process.returncode}；查看该节点日志")
        if time.monotonic()-self.last_metrics >= 1:
            self.last_metrics = time.monotonic()
            subscribers = [n["id"] for n in self.config["nodes"] if n["role"] == "subscriber"]
            summary = self.store.summary(subscribers)
            item = dict(time=time.time(), submitted=summary["submitted"], received=summary["received_unique"], pending=summary["missing"])
            self.series.append(item)
            if len(self.series) > 3600:
                self.series = self.series[-3600:]
            with (self.root / "metrics.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(item, latency_ms=summary["latency_ms"]))+"\n")
            summary["timeseries"] = list(self.series)
            if summary["observation_gaps"]:
                self.warn("观测记录存在缺口，缺失数和响应数不能直接作为业务丢失的结论；请核对原始日志及抓包")
            self.update(summary=summary)

    def wait(self, seconds):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            self.tick()
            self.cancel.wait(min(.1, max(0, deadline-time.monotonic())))

    def until(self, predicate, timeout, message):
        deadline = time.monotonic()+timeout
        while not predicate():
            self.wait(.1)
            if time.monotonic() > deadline:
                raise TimeoutError(message)

    def start_node(self, node, metadata, runtime):
        log = (self.root / "logs" / (node["id"]+".log")).open("wb")
        self.handles.append(log)
        command = ["ip", "netns", "exec", node["namespace"], "java", "-Dio.netty.eventLoopThreads=2",
                   "-cp", metadata["classpath"], "LabNode", str(runtime), node["id"]]
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append((node["id"], process))
        self.until(lambda: (self.root / "control" / ("ready-"+node["id"])).exists(),
                   self.config["warmup_timeout"], "节点启动超时："+node["id"])
        from .proxy import start_proxy
        proxy, thread = start_proxy(node["ip"], node["ui_port"])
        self.proxies.append(proxy)
        with self.lock:
            self.state["nodes"].append(dict(node, state="ready",
                page_url=f"{self.base_url}/?run={self.id}&node={node['id']}",
                original_url=f"http://127.0.0.1:{proxy.server_port}/"))
        self.save()

    def warmup(self):
        self.update(stage="warmup")
        publishers = [n["id"] for n in self.config["nodes"] if n["role"] == "publisher"]
        subscribers = [n["id"] for n in self.config["nodes"] if n["role"] == "subscriber"]
        deadline = time.monotonic()+self.config["warmup_timeout"]
        while True:
            for publisher in publishers:
                (self.root / "control" / ("probe-"+publisher)).touch()
            self.wait(1)
            if all(self.store.has_event(s, "delivery", publisher=p, seq=-1) for s in subscribers for p in publishers):
                return
            if time.monotonic() > deadline:
                raise TimeoutError("端到端暖机失败：未收到所有发布者至所有订阅者的探针，不开始正式负载")

    def faults(self, elapsed, enabled):
        for index, link in enumerate(self.config["links"], 10):
            start = link.get("fault_start")
            active = start is not None and start <= elapsed < start+link["fault_duration"]
            if active != enabled.get(index, False):
                self.network.fault(link, index, active)
                enabled[index] = active
                self.store.add(dict(time=time.time(), node=link["source"], event="fault",
                    note=f"{link['source']} → {link['target']}："+("100% 丢包开始" if active else "恢复配置丢包率")))

    def execute(self):
        self.update(stage="building")
        metadata = build(self.root / "logs/build.log", self.cancel.is_set)
        self.update(version=metadata, stage="network")
        self.network = Network(self.config, self.id.split("-")[-1])
        self.network.create()
        self.database = tempfile.TemporaryDirectory(prefix="ripple-lab-db-")
        runtime = dict(self.config, nodes=self.network.nodes, run_directory=str(self.root),
                       database_directory=self.database.name, application="ripple-lab-"+self.id)
        runtime_path = self.root / "runtime.json"
        runtime_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
        self.update(stage="starting")
        for node in self.network.nodes:
            log = (self.root / "logs" / (node["id"]+"-tcpdump.log")).open("wb")
            self.handles.append(log)
            process = subprocess.Popen(["ip", "netns", "exec", node["namespace"], "tcpdump", "-Z", "root",
                "-i", "eth0", "-nn", "-s", "0", "-U", "-w", str(self.root / "captures" / (node["id"]+".pcap")), "tcp"],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            self.captures.append(process)
        for role in ("server", "subscriber", "publisher"):
            for node in self.network.nodes:
                if node["role"] == role:
                    self.start_node(node, metadata, runtime_path)
            if role == "server":
                self.wait(11)
        self.warmup()
        self.update(stage="baseline")
        self.wait(self.config["baseline_seconds"])
        self.network.shape(self.config["links"])
        (self.root / "tc-start.json").write_text(json.dumps(self.network.stats(), indent=2))
        self.update(status="running", stage="sending")
        origin, enabled = time.monotonic(), {}
        self.faults(0, enabled)
        (self.root / "control/start").touch()
        publishers = [n for n in self.config["nodes"] if n["role"] == "publisher"]
        while not all((self.root / "control" / ("sent-"+n["id"]+".json")).exists() for n in publishers):
            self.faults(time.monotonic()-origin, enabled)
            self.wait(.1)
            if time.monotonic()-origin > max(n["duration"] for n in publishers)+30:
                raise TimeoutError("发送线程在截止后仍未返回；可能阻塞于原版同步重连，保留日志并终止")
        self.update(status="waiting", stage="waiting")
        deadline = time.monotonic()+self.config["wait_seconds"]
        while time.monotonic() < deadline:
            self.faults(time.monotonic()-origin, enabled)
            self.wait(.1)
        (self.root / "tc-end.json").write_text(json.dumps(self.network.stats(), indent=2))

    def cleanup(self):
        def safely(action, label):
            try:
                return action()
            except Exception as error:
                self.warn(f"{label}失败：{error}")
        (self.root / "control/stop").touch()
        deadline = time.monotonic()+10
        while any(p.poll() is None for _, p in self.processes) and time.monotonic() < deadline:
            safely(lambda: self.tick(check=False), "排空事件")
            time.sleep(.1)
        for _, process in self.processes:
            if process.poll() is None:
                safely(lambda p=process: os.killpg(p.pid, signal.SIGKILL), "终止节点")
                safely(lambda p=process: p.wait(timeout=5), "等待节点退出")
                self.warn("有节点未在 10 秒内退出，已强制终止；数据库及尾部观测可能不完整")
        for process in self.captures:
            if process.poll() is None:
                safely(lambda p=process: os.killpg(p.pid, signal.SIGINT), "结束抓包")
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        for handle in self.handles:
            safely(handle.close, "关闭日志")
        for proxy in self.proxies:
            safely(proxy.shutdown, "停止原网页代理")
            safely(proxy.server_close, "关闭原网页代理")
        if self.network:
            safely(self.network.cleanup, "释放网络空间")
        if hasattr(self, "database"):
            safely(lambda: shutil.copytree(self.database.name, self.root / "databases", dirs_exist_ok=True), "保存数据库")
            safely(self.database.cleanup, "释放临时数据库")
        # 分块读取直到所有 JVM 尾部事件都已入库。
        for _ in range(10000):
            self.store.ingest(self.root / "events")
            if all(self.store.offsets.get(p.name, 0) >= p.stat().st_size for p in (self.root / "events").glob("*.jsonl")):
                break
        self.last_metrics = 0
        self.tick(check=False)
        total = sum(json.loads(p.read_text())["submitted"] for p in (self.root / "control").glob("sent-*.json"))
        details = {p.stem[5:]: json.loads(p.read_text()) for p in (self.root / "control").glob("sent-*.json")}
        self.state["summary"]["load_details"] = details
        if any(item.get("in_flight") for item in details.values()):
            self.warn("停止调度时有原版调用仍在途，可能在发送窗口之后写入网络；请结合节点日志分析")
        if total != self.state["summary"].get("submitted", 0):
            self.warn(f"节点提交汇总 {total} 与观测提交 {self.state['summary'].get('submitted', 0)} 不一致，统计需复核")
        from .report import audit
        for message in audit(self.root)["warnings"]:
            self.warn(message)

    def run(self):
        status = "completed"
        try:
            self.execute()
        except InterruptedError as error:
            status = "cancelled"
            self.update(error=str(error))
        except Exception as error:
            status = "failed"
            (self.root / "logs/controller.log").write_text(traceback.format_exc(), encoding="utf-8")
            self.update(error=str(error))
        finally:
            self.update(stage="archiving")
            try:
                self.cleanup()
            except Exception as error:
                status = "failed"
                self.update(error="清理或归档失败："+str(error))
            for node in self.state["nodes"]:
                node["state"] = "stopped"
            self.update(status=status, stage=status, ended_at=time.time())
