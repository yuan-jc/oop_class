"""每节点独立网络空间；流量规则仅作用于本次创建的接口。"""
import json
import random
import subprocess


def run_command(argv, namespace=None, check=True):
    command = ["ip", "netns", "exec", namespace] + list(argv) if namespace else list(argv)
    return subprocess.run(command, text=True, capture_output=True, check=check)


def link_commands(source, target, link, index):
    class_id, handle = str(index), str(index+100)
    rate = str(int((link.get("bandwidth_kbit") or 10000000)*1000))+"bit"
    delay = str(link.get("delay_ms", 0))+"ms"
    loss = str(link.get("loss_percent", 0))+"%"
    limit = str(link.get("queue_bytes", 1048576))
    return [
        ["tc", "class", "add", "dev", "eth0", "parent", "1:", "classid", "1:"+class_id,
         "htb", "rate", rate, "ceil", rate, "burst", "1600", "cburst", "1600"],
        ["tc", "qdisc", "add", "dev", "eth0", "parent", "1:"+class_id, "handle", handle+":",
         "netem", "delay", delay, "loss", loss, "limit", "1000000"],
        ["tc", "qdisc", "replace", "dev", "eth0", "parent", handle+":1", "bfifo", "limit", limit],
        ["tc", "filter", "add", "dev", "eth0", "parent", "1:", "protocol", "ip", "prio", str(index),
         "u32", "match", "ip", "dst", target["ip"]+"/32", "flowid", "1:"+class_id]]


class Network:
    def __init__(self, config, token):
        self.token = token[:6]
        self.bridge = "rlb"+self.token
        self.created, self.peers, self.shaped = [], [], []
        # 不复用宿主已有子网；只在当前私有实验地址段内选择。
        routes = run_command(["ip", "-j", "route", "show"]).stdout
        occupied = {r.get("dst", "") for r in json.loads(routes)}
        candidates = [n for n in range(20, 240) if f"10.210.{n}.0/24" not in occupied]
        if not candidates:
            raise RuntimeError("没有可用的实验子网")
        self.octet = random.SystemRandom().choice(candidates)
        self.gateway = f"10.210.{self.octet}.1"
        self.nodes = []
        server_number = 0
        for index, original in enumerate(config["nodes"], 1):
            node = dict(original)
            if node["role"] == "server":
                server_number += 1
            node.update(ip=f"10.210.{self.octet}.{index+1}", namespace=f"rl-{self.token}-{index}",
                        api_port=13000 if node["role"] == "server" else 15000, ui_port=18080,
                        server_number=server_number if node["role"] == "server" else 0)
            self.nodes.append(node)
        self.by_id = {node["id"]: node for node in self.nodes}

    def create(self):
        run_command(["ip", "link", "add", self.bridge, "type", "bridge"])
        self.peers.append(self.bridge)
        run_command(["ip", "addr", "add", self.gateway+"/24", "dev", self.bridge])
        run_command(["ip", "link", "set", self.bridge, "up"])
        for index, node in enumerate(self.nodes, 1):
            namespace, peer = node["namespace"], f"rlv{self.token}{index}"
            run_command(["ip", "netns", "add", namespace])
            self.created.append(namespace)
            run_command(["ip", "link", "add", peer, "type", "veth", "peer", "name", "eth0", "netns", namespace])
            self.peers.append(peer)
            run_command(["ip", "link", "set", peer, "master", self.bridge])
            run_command(["ip", "link", "set", peer, "up"])
            for argv in (["ip", "link", "set", "lo", "up"],
                         ["ip", "addr", "add", node["ip"]+"/24", "dev", "eth0"],
                         ["ip", "link", "set", "eth0", "up"]):
                run_command(argv, namespace)
            run_command(["ethtool", "-K", "eth0", "tso", "off", "gso", "off", "gro", "off"], namespace, check=False)

    def shape(self, links):
        for index, link in enumerate(links, 10):
            source, target = self.by_id[link["source"]], self.by_id[link["target"]]
            namespace = source["namespace"]
            if namespace not in self.shaped:
                for argv in (["tc", "qdisc", "add", "dev", "eth0", "root", "handle", "1:", "htb", "default", "1"],
                             ["tc", "class", "add", "dev", "eth0", "parent", "1:", "classid", "1:1", "htb", "rate", "10gbit", "ceil", "10gbit"]):
                    run_command(argv, namespace)
                self.shaped.append(namespace)
            for command in link_commands(source, target, link, index):
                run_command(command, namespace)

    def fault(self, link, index, enabled):
        loss = 100 if enabled else link.get("loss_percent", 0)
        run_command(["tc", "qdisc", "change", "dev", "eth0", "parent", f"1:{index}",
                     "handle", f"{index+100}:", "netem", "delay", str(link.get("delay_ms", 0))+"ms",
                     "loss", str(loss)+"%", "limit", "1000000"], self.by_id[link["source"]]["namespace"])

    def stats(self):
        return {node["id"]: {kind: json.loads(run_command(
            ["tc", "-s", "-j", kind, "show", "dev", "eth0"], node["namespace"]).stdout)
            for kind in ("qdisc", "class")} for node in self.nodes}

    def cleanup(self):
        for namespace in reversed(self.created):
            # 名称与创建清单都来自本次对象，不扫描和清除其他实验。
            run_command(["ip", "netns", "del", namespace], check=False)
        for peer in reversed(self.peers):
            run_command(["ip", "link", "del", peer], check=False)
