"""实验配置校验；单位和方向在这里统一。"""
import copy
import math
import re


def default_config():
    return {"name": "基础收发实验", "protocol": "hashing", "nodes": [
        {"id": "s1", "role": "server", "label": "服务端 1"},
        {"id": "p1", "role": "publisher", "label": "发布者 1", "server": "s1",
         "size": 1024, "rate": 10, "duration": 10, "seed": 42},
        {"id": "c1", "role": "subscriber", "label": "订阅者 1", "server": "s1"}],
        "links": [], "wait_seconds": 10, "baseline_seconds": 1,
        "warmup_timeout": 60, "open_node_pages": True}


def number(value, label, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label}必须是数字")
    if not math.isfinite(value) or not low <= value <= high or (integer and int(value) != value):
        raise ValueError(f"{label}应在 {low}～{high} 之间" + ("，且为整数" if integer else ""))
    return int(value) if integer else float(value)


def normalize_config(raw):
    if not isinstance(raw, dict):
        raise ValueError("配置必须是 JSON 对象")
    config = copy.deepcopy(raw)
    name = config.get("name", "未命名实验")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("实验名称需要1～80个字符")
    config["name"] = name.strip()
    if config.get("protocol", "hashing") != "hashing":
        raise ValueError("当前已验证协议为 hashing")
    config["protocol"] = "hashing"
    nodes = config.get("nodes")
    if not isinstance(nodes, list) or not 3 <= len(nodes) <= 28:
        raise ValueError("需要服务端、发布者和订阅者，节点总数3～28")
    ids, roles = set(), {"server": [], "publisher": [], "subscriber": []}
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("节点必须为对象")
        identifier, role = node.get("id"), node.get("role")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,19}", identifier):
            raise ValueError("节点ID需以小写字母开头，最多20位，仅含字母、数字、下划线或连字符")
        if identifier in ids or role not in roles:
            raise ValueError("节点ID重复或角色无效")
        ids.add(identifier)
        roles[role].append(node)
        label = node.get("label", identifier)
        if not isinstance(label, str) or len(label) > 80:
            raise ValueError("节点名称最多80个字符")
        node["label"] = label
    for role, maximum in (("server", 8), ("publisher", 4), ("subscriber", 16)):
        if not 1 <= len(roles[role]) <= maximum:
            raise ValueError(f"{role} 节点数需要1～{maximum}")
    servers = {n["id"] for n in roles["server"]}
    for node in roles["publisher"] + roles["subscriber"]:
        node.setdefault("server", roles["server"][0]["id"])
        if node["server"] not in servers:
            raise ValueError(f"{node['id']} 引用的首连服务端不存在")
    for node in roles["publisher"]:
        for key, default, low, high, integer in (("size", 1024, 32, 900000, True),
                ("rate", 10, .1, 10000, False), ("duration", 10, .1, 3600, False),
                ("seed", 42, 0, 2147483647, True)):
            node[key] = number(node.get(key, default), f"{node['id']} 的 {key}", low, high, integer)
        if node["size"] < len(f"RL1:{node['id']}:000000000000:"):
            raise ValueError("消息大小不足以容纳发布者标识与序号")
    for key, default, low, high in (("wait_seconds", 10, 0, 600),
            ("baseline_seconds", 1, 0, 60), ("warmup_timeout", 60, 10, 300)):
        config[key] = number(config.get(key, default), key, low, high)
    if not isinstance(config.get("open_node_pages", True), bool):
        raise ValueError("自动打开节点页必须为布尔值")
    config["open_node_pages"] = config.get("open_node_pages", True)
    links, pairs = config.get("links", []), set()
    if not isinstance(links, list) or len(links) > len(nodes)*(len(nodes)-1):
        raise ValueError("链路列表无效")
    for link in links:
        if not isinstance(link, dict):
            raise ValueError("链路必须为对象")
        source, target = link.get("source"), link.get("target")
        if source not in ids or target not in ids or source == target:
            raise ValueError("链路两端必须为不同的已有节点")
        if (source, target) in pairs:
            raise ValueError("同一方向链路不能重复配置")
        pairs.add((source, target))
        bandwidth = link.get("bandwidth_kbit")
        link["bandwidth_kbit"] = None if bandwidth is None else number(bandwidth, "带宽(kbit/s)", .008, 10000000)
        for key, default, low, high, integer in (("delay_ms", 0, 0, 10000, False),
                ("loss_percent", 0, 0, 100, False), ("queue_bytes", 1048576, 1600, 67108864, True),
                ("fault_duration", 0, 0, 3600, False)):
            link[key] = number(link.get(key, default), key, low, high, integer)
        start = link.get("fault_start")
        link["fault_start"] = None if start is None else number(start, "丢包故障开始秒数", 0, 3600)
        if start is not None and link["fault_duration"] <= 0:
            raise ValueError("定时100%丢包需要大于0的持续时间")
    config["links"] = links
    return {key: config[key] for key in ("name", "protocol", "nodes", "links", "wait_seconds",
                                          "baseline_seconds", "warmup_timeout", "open_node_pages")}
