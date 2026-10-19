import struct
import tempfile
import unittest
from pathlib import Path

try:
    from capture import analyze_pcap
except ImportError:
    analyze_pcap = None


def packet(seq, data, timestamp):
    ethernet = b"\0" * 12 + b"\x08\x00"
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 40+len(data), 0, 0, 64, 6, 0,
                     b"\x0a\x00\x00\x01", b"\x0a\x00\x00\x02")
    tcp = struct.pack("!HHIIBBHHH", 3001, 5001, seq, 0, 0x50, 0x18, 1024, 0, 0)
    raw = ethernet + ip + tcp + data
    return struct.pack("<IIII", int(timestamp), int(timestamp % 1 * 1e6), len(raw), len(raw)) + raw


class CaptureTests(unittest.TestCase):
    def test_split_coalesced_retransmission_and_byte_units(self):
        self.assertIsNotNone(analyze_pcap, "尚未实现 PCAP 分析模块")
        frame = struct.pack("!I", 3) + b"\x04ab"
        blob = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 262144, 1)
        blob += packet(100, frame[:3], 10)
        blob += packet(103, frame[3:]+frame, 10.1)
        blob += packet(100, frame[:3], 10.2)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "test.pcap"
            path.write_bytes(blob)
            result = analyze_pcap(path)
        self.assertEqual(result["packet_count"], 3)
        self.assertEqual(result["tcp_payload_bytes"], 17)
        self.assertEqual(result["unique_tcp_payload_bytes"], 14)
        self.assertEqual(result["retransmitted_payload_bytes"], 3)
        self.assertEqual(result["frame_bytes"], 3*54+17)
        self.assertEqual(result["message_counts"], {"SYNC_REQUEST": 2})
        self.assertEqual(result["decode_issues"], [])

    def test_truncated_capture_does_not_silently_pass(self):
        self.assertIsNotNone(analyze_pcap)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bad.pcap"
            path.write_bytes(b"bad")
            with self.assertRaises(ValueError):
                analyze_pcap(path)

    def test_deadline_can_cut_an_inflight_frame_without_packet_loss(self):
        frame = struct.pack("!I", 100) + b"\x04ab"
        blob = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 262144, 1)
        blob += packet(100, frame, 10)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "tail.pcap"
            path.write_bytes(blob)
            result = analyze_pcap(path)
        self.assertEqual(result["decode_issues"], [])
        self.assertEqual(len(result["unfinished_frames"]), 1)
        self.assertEqual(result["tcp_payload_bytes"], 7)

    def test_overlapping_out_of_order_payload_uses_first_observation_window(self):
        blob = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 262144, 1)
        blob += packet(105, b"abcde", 10)
        blob += packet(100, b"12345abcde", 11)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "overlap.pcap"
            path.write_bytes(blob)
            result = analyze_pcap(path)
        self.assertEqual([p["unique_tcp_payload_bytes"] for p in result["packets"]], [5, 5])

    def test_sequence_wrap_does_not_merge_distinct_logical_ranges(self):
        blob = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 262144, 1)
        for index, seq in enumerate((100, 2**31-100, 2**32-200, 100)):
            blob += packet(seq, b"0123456789", 10+index)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "wrap.pcap"
            path.write_bytes(blob)
            result = analyze_pcap(path)
        self.assertEqual(result["unique_tcp_payload_bytes"], 40)
