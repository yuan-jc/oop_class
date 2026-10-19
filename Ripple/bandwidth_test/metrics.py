"""测试负载与逐消息统计；所有时间戳均为 Unix 秒。"""
import math
import random
import re


def parse_bandwidth(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(bit|kbit|mbit|gbit)", value.lower())
    if not match:
        raise ValueError("带宽格式应为 64kbit、1mbit 或 100000bit")
    result = float(match[1]) * {"bit": 1, "kbit": 1000, "mbit": 10**6, "gbit": 10**9}[match[2]]
    if not 8 <= result <= 10**12:
        raise ValueError("带宽必须在 8bit/s 到 1tbit/s 之间")
    return int(result)


def validate(size, rate, duration, subscribers, servers):
    if not 32 <= size <= 1000000:
        raise ValueError("value 总大小必须为 32～1000000 字节，包含测试序号")
    if not math.isfinite(rate) or not 0 < rate <= 1000000:
        raise ValueError("频率必须为有限正数，且不超过每秒 1000000 条")
    if not math.isfinite(duration) or not 0 < duration <= 86400:
        raise ValueError("持续时间必须为有限正数，且不超过 86400 秒")
    if not 1 <= subscribers <= 100 or not 1 <= servers <= 20:
        raise ValueError("订阅者数量应为 1～100，服务端数量应为 1～20")


def payload(seq, size, seed):
    header = f"RB1:{seq:012d}:"
    if size < len(header):
        raise ValueError("消息不足以容纳测试头")
    generator = random.Random(seed + seq)
    return header + "".join(generator.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=size-len(header)))


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    position = (len(values)-1)*q
    lower = int(position)
    upper = min(lower+1, len(values)-1)
    return values[lower] + (values[upper]-values[lower])*(position-lower)


def summarize(events, subscribers, size, start, send_end, deadline):
    sends = {e["seq"]: e for e in events if e["event"] == "send" and e["seq"] >= 0}
    successful = {e["seq"] for e in events if e["event"] == "put_response" and e.get("ok")
                  and e["seq"] in sends and e["time"] <= deadline}
    unique, duplicates, during, latencies = {}, 0, 0, []
    counts = {str(i): 0 for i in range(1, subscribers+1)}
    out_of_order = {str(i): 0 for i in range(1, subscribers+1)}
    highest = {i: -1 for i in range(1, subscribers+1)}
    for event in sorted(events, key=lambda e: e["time"]):
        if event["event"] != "receive" or event["seq"] not in sends or event["time"] > deadline:
            continue
        subscriber, seq = event["id"], event["seq"]
        if subscriber not in highest:
            continue
        key = (subscriber, seq)
        if key in unique:
            duplicates += 1
            continue
        unique[key] = event
        counts[str(subscriber)] += 1
        during += event["time"] <= send_end
        latency = (event["time"] - sends[seq]["time"])*1000
        latencies.append(latency)
        out_of_order[str(subscriber)] += seq < highest[subscriber]
        highest[subscriber] = max(highest[subscriber], seq)
    expected = len(sends)*subscribers
    success_deliveries = sum(seq in successful for _, seq in unique)
    return {
        "submitted": len(sends), "put_success": len(successful),
        "expected_deliveries": expected, "received_unique": len(unique),
        "received_during_send": during, "duplicates": duplicates,
        "missing_at_deadline": expected-len(unique),
        "delivery_ratio": len(unique)/expected if expected else None,
        "delivery_ratio_during_send": during/expected if expected else None,
        "delivery_ratio_for_successful_puts": success_deliveries/(len(successful)*subscribers) if successful else None,
        "subscriber_received": counts, "subscriber_out_of_order": out_of_order,
        "subscriber_missing": {i: len(sends)-count for i, count in counts.items()},
        "submitted_value_bytes": len(sends)*size, "delivered_value_bytes": len(unique)*size,
        "actual_submit_rate": len(sends)/(send_end-start) if send_end > start else None,
        "negative_latency_samples": sum(value < 0 for value in latencies),
        "latency_ms": {"samples": len(latencies), "p50": percentile(latencies, .5),
                       "p95": percentile(latencies, .95), "p99": percentile(latencies, .99),
                       "max": max(latencies) if latencies else None},
    }


def time_series(events, packets, start, send_end, deadline, subscribers):
    rows, seen, submitted, received = [], set(), 0, 0
    send_events = sorted((e for e in events if e["event"] == "send" and e["seq"] >= 0), key=lambda e: e["time"])
    valid = {e["seq"] for e in send_events}
    receive_events = sorted((e for e in events if e["event"] == "receive" and e["seq"] in valid), key=lambda e: e["time"])
    packet_events = sorted(packets, key=lambda p: p["time"])
    si = ri = pi = 0
    for second in range(math.ceil(deadline-start)):
        left, right = start+second, min(start+second+1, deadline)
        sent, got, frame_bytes, tcp_bytes = 0, 0, 0, 0
        while si < len(send_events) and send_events[si]["time"] < right:
            si += 1
            sent += 1
        while ri < len(receive_events) and receive_events[ri]["time"] < right:
            event = receive_events[ri]
            key = (event["id"], event["seq"])
            if key not in seen:
                seen.add(key)
                got += 1
            ri += 1
        while pi < len(packet_events) and packet_events[pi]["time"] < right:
            packet = packet_events[pi]
            if packet["time"] >= left:
                frame_bytes += packet["frame_bytes"]
                tcp_bytes += packet["tcp_payload_bytes"]
            pi += 1
        submitted += sent
        received += got
        rows.append(dict(second=second, duration_s=right-left,
                         stage="send" if left < send_end else "drain",
                         submitted=sent, received_unique=got, pending=submitted*subscribers-received,
                         frame_bytes=frame_bytes, tcp_payload_bytes=tcp_bytes,
                         frame_bps=frame_bytes*8/(right-left), tcp_payload_bps=tcp_bytes*8/(right-left)))
    return rows
