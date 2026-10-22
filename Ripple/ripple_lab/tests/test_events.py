from pathlib import Path
import tempfile
import unittest
from ripple_lab.event_store import EventStore


class EventTests(unittest.TestCase):
    def test_counts_publishers_responses_and_unique_subscribers_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            store = EventStore(Path(folder) / "events.sqlite")
            for publisher in ("p1", "p2"):
                store.add({"time": 10, "node": publisher, "event": "send", "publisher": publisher, "seq": 0})
            store.add({"time": 10.1, "node": "p1", "event": "receive", "type": "PUT_RESPONSE", "publisher": "p1", "seq": 0, "ok": True})
            for publisher in ("p1", "p2"):
                store.add({"time": 11, "node": "c1", "event": "delivery", "publisher": publisher, "seq": 0, "ok": True})
            store.add({"time": 12, "node": "c1", "event": "delivery", "publisher": "p1", "seq": 0, "ok": True})
            stats = store.summary(["c1", "c2"])
            self.assertEqual(stats["submitted"], 2)
            self.assertEqual(stats["put_success"], 1)
            self.assertEqual(stats["received_unique"], 2)
            self.assertEqual(stats["expected_deliveries"], 4)
            self.assertEqual(stats["missing"], 2)
            self.assertEqual(stats["duplicates"], 1)
            self.assertEqual(stats["latency_ms"]["max"], 1000)
            page = store.query(node="c1", limit=2)
            self.assertEqual(len(page["events"]), 2)
            self.assertEqual(len(store.query(node="c1", after=page["next_after"])["events"]), 1)
            store.close()

    def test_ignores_warmup_and_receipt_is_not_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            store = EventStore(Path(folder) / "events.sqlite")
            store.add({"time": 1, "node": "p1", "event": "send", "publisher": "p1", "seq": -1})
            store.add({"time": 2, "node": "c1", "event": "receive", "publisher": "p1", "seq": 0})
            self.assertEqual(store.summary(["c1"])["received_unique"], 0)
            self.assertEqual(store.summary(["c1"])["submitted"], 0)
            store.close()


if __name__ == "__main__":
    unittest.main()
