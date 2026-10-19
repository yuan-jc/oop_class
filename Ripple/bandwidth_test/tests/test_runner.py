import tempfile
import unittest
from pathlib import Path
from runner import read_events


class EventIntegrityTests(unittest.TestCase):
    def test_corruption_in_middle_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"events.jsonl").write_text('bad\n{"event":"send","seq":0,"id":0,"time":1}\n')
            with self.assertRaises(ValueError):
                read_events(root)

    def test_live_tail_is_allowed_but_final_tail_must_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"events.jsonl").write_text('{"event":')
            self.assertEqual(read_events(root), [])
            with self.assertRaises(ValueError):
                read_events(root, live=False)
