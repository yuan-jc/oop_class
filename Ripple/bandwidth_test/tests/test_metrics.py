import unittest

try:
    from metrics import summarize, parse_bandwidth, payload, validate
except ImportError:
    summarize = parse_bandwidth = payload = validate = None


class MetricsTests(unittest.TestCase):
    def test_required_metrics_exist(self):
        self.assertIsNotNone(summarize, "尚未实现外部统计模块")

    def test_delivery_counts_each_subscriber_and_duplicates(self):
        self.assertIsNotNone(summarize)
        events = [dict(event="send", seq=i, time=10+i, id=0) for i in (0, 1)]
        events += [dict(event="receive", seq=0, time=10.1, id=1),
                   dict(event="receive", seq=0, time=10.2, id=1),
                   dict(event="receive", seq=1, time=11.2, id=2),
                   dict(event="receive", seq=-1, time=9, id=1)]
        result = summarize(events, 2, 64, 10, 11.1, 12)
        self.assertEqual(result["expected_deliveries"], 4)
        self.assertEqual(result["received_unique"], 2)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["missing_at_deadline"], 2)
        self.assertEqual(result["received_during_send"], 1)
        self.assertAlmostEqual(result["delivery_ratio"], 0.5)
        self.assertAlmostEqual(result["latency_ms"]["p50"], 150)

    def test_no_sends_is_not_perfect_delivery(self):
        self.assertIsNotNone(summarize)
        result = summarize([], 1, 64, 0, 1, 2)
        self.assertIsNone(result["delivery_ratio"])
        self.assertIsNone(result["latency_ms"]["p99"])

    def test_payload_size_includes_header(self):
        self.assertIsNotNone(payload)
        value = payload(123, 64, 5)
        self.assertEqual(len(value.encode("utf-8")), 64)
        self.assertTrue(value.startswith("RB1:000000000123:"))
        self.assertEqual(value, payload(123, 64, 5))
        with self.assertRaises(ValueError):
            payload(123, 4, 5)

    def test_bandwidth_units_and_rejections(self):
        self.assertIsNotNone(parse_bandwidth)
        self.assertEqual(parse_bandwidth("512kbit"), 512000)
        self.assertEqual(parse_bandwidth("1.5mbit"), 1500000)
        for value in ("0kbit", "1MB", "-3bit", "nan"):
            with self.assertRaises(ValueError):
                parse_bandwidth(value)

    def test_invalid_load_is_rejected(self):
        self.assertIsNotNone(validate)
        for size, rate, duration in ((4, 1, 1), (1048576, 1, 1), (64, 0, 1), (64, 1, float("nan"))):
            with self.assertRaises(ValueError):
                validate(size, rate, duration, 1, 3)

    def test_responses_after_deadline_do_not_change_snapshot(self):
        events = [dict(event="send", seq=0, time=10, id=0),
                  dict(event="put_response", seq=0, time=13, id=0, ok=True)]
        self.assertEqual(summarize(events, 1, 64, 10, 11, 12)["put_success"], 0)
