"""检查低速链路统计的边界与内容判定，避免把缺失误报为正确。"""
import unittest
from slow_link_suite import assess_events, SlowExperiment
from types import SimpleNamespace


def event(kind, seq, timestamp, digest="same", ok=True):
    return dict(event=kind, seq=seq, time=timestamp, id=0 if kind in ("send", "payload_source") else 1,
                sha256=digest, value_bytes=2048, ok=ok)


class SlowLinkTests(unittest.TestCase):
    def test_all_groups_use_same_token_bucket_rate(self):
        for delay, loss in [(0, 0), (2000, 0), (0, 50)]:
            instance = SlowExperiment.__new__(SlowExperiment)
            instance.args = SimpleNamespace(bandwidth="8192bit", queue_bytes=1048576,
                delay_ms=delay, loss_percent=loss, seed=42)
            instance.config = {}
            instance.server_ns = "isolated-test"
            commands = []
            instance.command = lambda argv, ns: commands.append(argv)
            instance.tc_stats = lambda stage: None
            instance.shape()
            self.assertIn("tbf", commands[0])
            self.assertEqual(commands[0][commands[0].index("rate")+1], "8192bit")
            self.assertEqual(commands[0][commands[0].index("burst")+1], "1600")
            self.assertEqual(len(commands), 1 if not delay and not loss else 2)

    def inputs(self):
        return [event("send", 0, 100), event("payload_source", 0, 100),
                event("send", 1, 159), event("payload_source", 1, 159)]

    def test_exact_sixty_second_boundary_and_last_first_arrival(self):
        events = self.inputs() + [event("receive", 0, 160), event("payload_received", 0, 160),
            event("receive", 1, 162), event("payload_received", 1, 162),
            event("receive", 1, 170), event("payload_received", 1, 170)]
        result, rows = assess_events(events, 100, 60, 2048)
        self.assertEqual(result["received_at_send_end"], 1)
        self.assertEqual(result["remaining_at_send_end"], 1)
        self.assertEqual(result["last_first_arrival_s"], 62)
        self.assertEqual(result["all_arrived_after_stop_s"], 2)
        self.assertTrue(result["all_content_correct"])
        self.assertEqual(len(rows), 2)

    def test_missing_is_not_declared_fully_correct(self):
        events = self.inputs() + [event("receive", 0, 110), event("payload_received", 0, 110)]
        result, _ = assess_events(events, 100, 60, 2048)
        self.assertEqual(result["missing_final"], 1)
        self.assertIsNone(result["all_arrived_after_stop_s"])
        self.assertFalse(result["all_content_correct"])

    def test_hash_mismatch_is_a_content_error(self):
        events = self.inputs() + [event("receive", 0, 110), event("payload_received", 0, 110),
            event("receive", 1, 162), event("payload_received", 1, 162, digest="wrong", ok=False)]
        result, rows = assess_events(events, 100, 60, 2048)
        self.assertEqual(result["missing_final"], 0)
        self.assertEqual(result["content_error_messages"], 1)
        self.assertEqual(result["correct_messages"], 1)
        self.assertFalse(result["all_content_correct"])
        self.assertFalse(rows[1]["correct"])


if __name__ == "__main__":
    unittest.main()
