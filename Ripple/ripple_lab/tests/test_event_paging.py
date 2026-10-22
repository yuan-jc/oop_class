"""真实磁盘游标翻页回归。"""
import tempfile
import unittest
from pathlib import Path
from ripple_lab.event_store import EventStore


class PagingTests(unittest.TestCase):
    def test_tail_and_both_directions(self):
        with tempfile.TemporaryDirectory() as folder:
            store = EventStore(Path(folder)/"events.sqlite")
            store.add_many([dict(node="s1", event="receive", seq=i) for i in range(1000)])
            latest = store.query(tail=True, limit=100)
            self.assertEqual([e["index"] for e in latest["events"]], list(range(901, 1001)))
            previous = store.query(before=901, limit=100)
            self.assertEqual(previous["events"][0]["index"], 801)
            self.assertEqual(store.query(after=900, limit=100)["events"], latest["events"])
            self.assertTrue(latest["has_more"])
            store.close()
