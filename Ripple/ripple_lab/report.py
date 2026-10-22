"""结束时核对抓包完整性和数据库可读性；不把快照当作历史送达证明。"""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct


def capture_summary(path):
    packets, captured, original = 0, 0, 0
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        header = stream.read(24)
        digest.update(header)
        endian = {b"\xd4\xc3\xb2\xa1": "<", b"\xa1\xb2\xc3\xd4": ">",
                  b"\x4d\x3c\xb2\xa1": "<", b"\xa1\xb2\x3c\x4d": ">"}.get(header[:4])
        if len(header) != 24 or endian is None:
            raise ValueError("无效 PCAP 头部")
        while True:
            record = stream.read(16)
            if not record:
                break
            if len(record) != 16:
                raise ValueError("PCAP 记录尾部不完整")
            _, _, size, wire_size = struct.unpack(endian+"IIII", record)
            if size > 16*1024*1024:
                raise ValueError("PCAP 包长度异常")
            data = stream.read(size)
            if len(data) != size:
                raise ValueError("PCAP 包内容不完整")
            digest.update(record)
            digest.update(data)
            packets += 1
            captured += size
            original += wire_size
    return dict(packet_count=packets, captured_bytes=captured, original_bytes=original,
                sha256=digest.hexdigest())


def audit(root):
    root = Path(root)
    result = {"captures": {}, "databases": {}, "warnings": [],
              "notes": ["各节点抓包包含收发两个方向，同一链路两端记录不可直接相加作为线速。",
                        "抓包长度与摘要检查不等于 TCP 重组或业务内容验证；业务内容由 delivery.content_ok 全文校验。",
                        "数据库为结束快照，原版保留策略可能删除历史版本，不以其行数统计总送达。"]}
    for path in (root / "captures").glob("*.pcap"):
        try:
            item = capture_summary(path)
            log = root / "logs" / (path.stem+"-tcpdump.log")
            text = log.read_text(errors="replace") if log.exists() else ""
            dropped = re.search(r"(\d+) packets dropped by kernel", text)
            item["kernel_dropped"] = int(dropped.group(1)) if dropped else None
            if not dropped or int(dropped.group(1)):
                result["warnings"].append(path.name+" 抓包有丢失或没有正常退出统计")
            result["captures"][path.stem] = item
        except Exception as error:
            result["warnings"].append(path.name+"："+str(error))
    for path in (root / "databases").glob("*.sqlite"):
        connection = None
        try:
            connection = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            tables = [name for name, in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            result["databases"][path.stem] = dict(integrity=integrity, tables=tables)
            if integrity != "ok":
                result["warnings"].append(path.name+" 数据库完整性异常")
        except Exception as error:
            result["warnings"].append(path.name+"："+str(error))
        finally:
            if connection:
                connection.close()
    (root / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
