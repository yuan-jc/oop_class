"""优化对照结果必须同时保留缺失、字节和内容正确性。"""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from optimization_suite import flatten_result


class SuiteTests(unittest.TestCase):
    def test_incomplete_delivery_does_not_look_like_better_efficiency(self):
        summary = dict(status="complete", submitted=100, received_unique=20, expected_deliveries=100,
                       put_success=100, missing_at_deadline=80, corrupt_content=0,
                       delivery_ratio=.2, delivery_ratio_during_send=.1, latency_ms={"p50": 10, "p99": 20},
                       actual_submit_rate=100, total_send_and_drain_frame_bytes=30000,
                       measurement_warnings=[], captures={"traffic": {"downlink_send_and_drain": {"frame_bytes": 20000}}})
        result = flatten_result(summary, {}, "v1", "random_512", 1)
        self.assertEqual(result["missing"], 80)
        self.assertIsNone(result["complete_downlink_bytes_per_message"])
        self.assertEqual(result["downlink_bytes_per_delivered"], 1000)
        summary.update(received_unique=100, missing_at_deadline=0)
        result = flatten_result(summary, {}, "v1", "random_512", 1)
        self.assertEqual(result["complete_downlink_bytes_per_message"], 200)

    def test_measurement_warning_disqualifies_run(self):
        summary = dict(status="measurement_incomplete", submitted=10, expected_deliveries=10,
                       received_unique=10, missing_at_deadline=0, corrupt_content=0,
                       measurement_warnings=["抓包丢失"], captures={})
        result = flatten_result(summary, {}, "v2", "random_512", 1)
        self.assertFalse(result["valid"])
