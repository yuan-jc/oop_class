"""磁盘事件存储和独立业务统计，避免用无限内存列表保存记录。"""
import json
import math
from pathlib import Path
import sqlite3
import threading
import time


class EventStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS events (idx INTEGER PRIMARY KEY, time REAL, node TEXT,
              event TEXT, type TEXT, publisher TEXT, seq INTEGER, body TEXT);
            CREATE INDEX IF NOT EXISTS events_node_idx ON events(node,idx);
            CREATE INDEX IF NOT EXISTS events_kind ON events(event,type,idx);
            CREATE TABLE IF NOT EXISTS submissions(publisher TEXT,seq INTEGER,time REAL,PRIMARY KEY(publisher,seq));
            CREATE TABLE IF NOT EXISTS deliveries(publisher TEXT,seq INTEGER,node TEXT,time REAL,PRIMARY KEY(publisher,seq,node));
            CREATE TABLE IF NOT EXISTS responses(publisher TEXT,seq INTEGER,PRIMARY KEY(publisher,seq));
        """)
        self.offsets, self.partial = {}, {}

    def add(self, event):
        self.add_many([event])

    def add_many(self, events):
        with self.lock, self.conn:
            for raw in events:
                event = dict(raw)
                moment = event.get("time", time.time())
                if not isinstance(moment, (float, int)) or not math.isfinite(moment):
                    raise ValueError("事件时间无效")
                node, kind = str(event.get("node", "")), str(event.get("event", ""))
                publisher, seq = str(event.get("publisher") or ""), int(event.get("seq") if event.get("seq") is not None else -1)
                event.update(time=moment, node=node, event=kind, publisher=publisher, seq=seq)
                self.conn.execute("INSERT INTO events(time,node,event,type,publisher,seq,body) VALUES(?,?,?,?,?,?,?)",
                    (moment, node, kind, event.get("type", ""), publisher, seq, json.dumps(event, ensure_ascii=False)))
                if seq < 0 or not publisher:
                    continue
                if kind == "send":
                    self.conn.execute("INSERT OR IGNORE INTO submissions VALUES(?,?,?)", (publisher, seq, moment))
                if kind == "delivery" and event.get("ok", True):
                    self.conn.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?)", (publisher, seq, node, moment))
                if kind == "receive" and event.get("type") == "PUT_RESPONSE" and event.get("ok"):
                    self.conn.execute("INSERT OR IGNORE INTO responses VALUES(?,?)", (publisher, seq))

    def ingest(self, directory):
        batch, errors = [], []
        for path in Path(directory).glob("*.jsonl"):
            with path.open("rb") as stream:
                stream.seek(self.offsets.get(path.name, 0))
                data = stream.read(4*1024*1024)
                self.offsets[path.name] = stream.tell()
            data = self.partial.get(path.name, b"") + data
            lines = data.split(b"\n")
            self.partial[path.name] = lines.pop()
            for line in lines:
                if not line:
                    continue
                try:
                    batch.append(json.loads(line))
                except (ValueError, UnicodeDecodeError) as error:
                    errors.append(f"事件记录损坏：{path.name}：{error}")
        self.add_many(batch)
        return errors

    def query(self, node="", event="", q="", after=0, limit=100, before=None, tail=False):
        descending = tail or before is not None
        filters, values = (["idx<?"], [int(before)]) if before is not None else (["1=1"], []) if tail else (["idx>?"], [max(0, int(after))])
        if node:
            filters.append("node=?")
            values.append(node)
        if event:
            filters.append("event=?")
            values.append(event)
        if q:
            filters.append("body LIKE ? ESCAPE '\\'")
            values.append("%"+q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")+"%")
        where = " AND ".join(filters)
        with self.lock:
            rows = self.conn.execute(f"SELECT idx,body FROM events WHERE {where} ORDER BY idx {'DESC' if descending else 'ASC'} LIMIT ?",
                                     values+[min(500, max(1, int(limit)))]).fetchall()
            total = self.conn.execute(f"SELECT COUNT(*) FROM events WHERE {where}", values).fetchone()[0]
        if descending:
            rows.reverse()
        events = [dict(json.loads(body), index=index) for index, body in rows]
        return {"events": events, "total": total, "next_after": rows[-1][0] if rows else int(after), "has_more": total > len(rows)}

    def has_event(self, node, event, publisher=None, seq=None):
        filters, params = ["node=?", "event=?"], [node, event]
        if publisher is not None:
            filters.append("publisher=?")
            params.append(publisher)
        if seq is not None:
            filters.append("seq=?")
            params.append(seq)
        with self.lock:
            return self.conn.execute("SELECT 1 FROM events WHERE "+" AND ".join(filters)+" LIMIT 1", params).fetchone() is not None

    def summary(self, subscribers):
        with self.lock:
            c = self.conn
            submitted = c.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
            placeholders = ",".join("?" for _ in subscribers) or "''"
            received = c.execute(f"SELECT COUNT(*) FROM deliveries WHERE node IN ({placeholders})", subscribers).fetchone()[0]
            raw_deliveries = c.execute(f"SELECT COUNT(*) FROM events WHERE event='delivery' AND seq>=0 AND node IN ({placeholders})", subscribers).fetchone()[0]
            put_success = c.execute("SELECT COUNT(*) FROM responses JOIN submissions USING(publisher,seq)").fetchone()[0]
            per_node = {}
            for node, event, count in c.execute("SELECT node,event,COUNT(*) FROM events WHERE seq>=0 GROUP BY node,event"):
                per_node.setdefault(node, {})[event] = count
            for node, count in c.execute("SELECT node,COUNT(*) FROM deliveries GROUP BY node"):
                per_node.setdefault(node, {})["received_unique"] = count
            per_publisher = {p: {"submitted": n} for p, n in c.execute("SELECT publisher,COUNT(*) FROM submissions GROUP BY publisher")}
            for publisher, count in c.execute("SELECT publisher,COUNT(*) FROM deliveries GROUP BY publisher"):
                per_publisher.setdefault(publisher, {})["received_unique"] = count
            latency_sql = f"SELECT (d.time-s.time)*1000 AS latency FROM deliveries d JOIN submissions s USING(publisher,seq) WHERE d.node IN ({placeholders})"
            count = c.execute("SELECT COUNT(*) FROM ("+latency_sql+")", subscribers).fetchone()[0]
            latency = {key: None for key in ("p50", "p95", "p99", "max")}
            if count:
                for key, fraction in (("p50", .5), ("p95", .95), ("p99", .99), ("max", 1)):
                    offset = min(count-1, int((count-1)*fraction))
                    latency[key] = c.execute(latency_sql+" ORDER BY latency LIMIT 1 OFFSET ?", list(subscribers)+[offset]).fetchone()[0]
            gaps = c.execute("SELECT COUNT(*) FROM events WHERE event='observation_gap'").fetchone()[0]
            corrupt = c.execute("SELECT COUNT(*) FROM events WHERE event='delivery' AND json_extract(body,'$.content_ok')=0").fetchone()[0]
        expected = submitted*len(subscribers)
        return {"submitted": submitted, "put_success": put_success, "received_unique": received,
                "expected_deliveries": expected, "missing": max(0, expected-received),
                "duplicates": max(0, raw_deliveries-received), "latency_ms": latency,
                "per_node": per_node, "per_publisher": per_publisher, "observation_gaps": gaps, "corrupt_content": corrupt}

    def close(self):
        with self.lock:
            self.conn.commit()
            self.conn.close()
