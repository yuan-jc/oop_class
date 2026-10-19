"""读取经典 Ethernet/IPv4 PCAP，区分包字节、TCP 载荷和 Ripple 消息。"""
import socket
import struct
from collections import Counter, defaultdict

TYPES = ("HEARTBEAT_REQUEST", "HEARTBEAT_RESPONSE", "ACK_REQUEST", "ACK_RESPONSE",
         "SYNC_REQUEST", "SYNC_RESPONSE", "DELETE_REQUEST", "DELETE_RESPONSE",
         "GET_REQUEST", "GET_RESPONSE", "PUT_REQUEST", "PUT_RESPONSE",
         "SUBSCRIBE_REQUEST", "SUBSCRIBE_RESPONSE", "UNSUBSCRIBE_REQUEST", "UNSUBSCRIBE_RESPONSE",
         "INCREMENTAL_UPDATE_REQUEST", "INCREMENTAL_UPDATE_RESPONSE", "DISPATCH_REQUEST",
         "DISPATCH_RESPONSE", "GET_CLIENT_LIST_REQUEST", "GET_CLIENT_LIST_RESPONSE",
         "SYSTEM_INFO_REQUEST", "SYSTEM_INFO_RESPONSE")


def analyze_pcap(path):
    packets, streams, issues, unfinished = [], defaultdict(list), [], []
    with open(path, "rb") as source:
        header = source.read(24)
        formats = {b"\xd4\xc3\xb2\xa1": ("<", 1e6), b"\xa1\xb2\xc3\xd4": (">", 1e6),
                   b"\x4d\x3c\xb2\xa1": ("<", 1e9), b"\xa1\xb2\x3c\x4d": (">", 1e9)}
        if len(header) != 24 or header[:4] not in formats:
            raise ValueError(f"无效的经典 PCAP 文件：{path}")
        endian, scale = formats[header[:4]]
        if struct.unpack(endian+"I", header[20:24])[0] != 1:
            raise ValueError("仅支持 Ethernet 链路类型，请用 tcpdump -i lo 或专用 veth 抓取")
        while True:
            record = source.read(16)
            if not record:
                break
            if len(record) != 16:
                raise ValueError("PCAP 记录头不完整")
            sec, fraction, included, original = struct.unpack(endian+"IIII", record)
            data = source.read(included)
            if len(data) != included:
                raise ValueError("PCAP 数据不完整")
            if included < original:
                issues.append("捕获包被截断")
            if len(data) < 34 or data[12:14] != b"\x08\x00":
                issues.append("捕获了不支持的非 IPv4/Ethernet 包")
                continue
            ip = 14
            tcp = ip + (data[ip] & 15)*4
            if data[ip+9] != 6 or len(data) < tcp+20:
                issues.append("捕获了非 TCP 或不完整包")
                continue
            if struct.unpack("!H", data[ip+6:ip+8])[0] & 0x3fff:
                issues.append("不支持 IP 分片")
                continue
            ip_length = struct.unpack("!H", data[ip+2:ip+4])[0]
            src_port, dst_port, seq = struct.unpack("!HHI", data[tcp:tcp+8])
            offset = tcp+(data[tcp+12] >> 4)*4
            body = data[offset:ip+ip_length]
            flow = (socket.inet_ntoa(data[ip+12:ip+16]), src_port,
                    socket.inet_ntoa(data[ip+16:ip+20]), dst_port)
            packet = dict(time=sec+fraction/scale, frame_bytes=original, tcp_payload_bytes=len(body),
                          flow=flow, seq=seq, syn=bool(data[tcp+13] & 2), unique_tcp_payload_bytes=0)
            packets.append(packet)
            if body:
                streams[flow].append((seq, body, packet))
    messages = Counter()
    flows = []
    for flow, segments in streams.items():
        # 按到达顺序动态展开 32 位序号，支持累计超过 2 GiB/4 GiB 的流。
        reference = segments[0][0]
        normalized, observed = [], []
        for seq, body, packet in segments:
            logical = reference + ((seq-reference+2**31) % 2**32)-2**31
            reference = max(reference, logical+len(body))
            left, right = logical, logical+len(body)
            overlap = sum(max(0, min(right, b)-max(left, a)) for a, b in observed)
            packet["unique_tcp_payload_bytes"] = len(body)-overlap
            merged, inserted = [], False
            for a, b in observed:
                if b < left:
                    merged.append((a, b))
                elif a > right:
                    if not inserted:
                        merged.append((left, right))
                        inserted = True
                    merged.append((a, b))
                else:
                    left, right = min(left, a), max(right, b)
            if not inserted:
                merged.append((left, right))
            observed = merged
            normalized.append((logical, body, packet))
        normalized.sort(key=lambda item: (item[0], item[2]["time"]))
        end, buf = normalized[0][0], bytearray()
        discontinuous = False
        for seq, body, packet in normalized:
            if seq > end:
                issues.append(f"TCP 序列存在缺口：{flow}")
                discontinuous = True
                end = seq
            skip = max(0, end-seq)
            new = body[skip:]
            buf.extend(new)
            end = max(end, seq+len(body))
        flow_messages = Counter()
        if not discontinuous:
            position = 0
            while position+4 <= len(buf):
                size = struct.unpack("!I", buf[position:position+4])[0]
                if size < 1 or size > 1048576:
                    issues.append(f"无法对齐 Ripple 帧（可能抓包从连接中途开始）：{flow}")
                    break
                if position+4+size > len(buf):
                    break
                kind = buf[position+4]
                name = TYPES[kind] if kind < len(TYPES) else f"UNKNOWN_{kind}"
                flow_messages[name] += 1
                position += 4+size
            if position != len(buf):
                unfinished.append(dict(flow=flow, captured_tail_bytes=len(buf)-position))
        messages.update(flow_messages)
        flow_packets = [p for p in packets if p["flow"] == flow]
        flows.append(dict(src_ip=flow[0], src_port=flow[1], dst_ip=flow[2], dst_port=flow[3],
                          frame_bytes=sum(p["frame_bytes"] for p in flow_packets),
                          tcp_payload_bytes=sum(len(body) for _, body, _ in segments),
                          unique_tcp_payload_bytes=sum(p["unique_tcp_payload_bytes"] for _, _, p in segments),
                          message_counts=dict(flow_messages)))
    total = sum(p["tcp_payload_bytes"] for p in packets)
    unique = sum(p["unique_tcp_payload_bytes"] for p in packets)
    return dict(packet_count=len(packets), frame_bytes=sum(p["frame_bytes"] for p in packets),
                tcp_payload_bytes=total, unique_tcp_payload_bytes=unique,
                retransmitted_payload_bytes=total-unique, message_counts=dict(messages),
                decode_issues=sorted(set(issues)), unfinished_frames=unfinished, packets=packets, flows=flows)


def window_totals(packets, start, end):
    selected = [p for p in packets if start <= p["time"] < end]
    result = {key: sum(p[key] for p in selected)
              for key in ("frame_bytes", "tcp_payload_bytes", "unique_tcp_payload_bytes")}
    result["packet_count"] = len(selected)
    result["duration_s"] = end-start
    result["frame_bps"] = result["frame_bytes"]*8/(end-start) if end > start else None
    result["tcp_payload_bps"] = result["tcp_payload_bytes"]*8/(end-start) if end > start else None
    return result
