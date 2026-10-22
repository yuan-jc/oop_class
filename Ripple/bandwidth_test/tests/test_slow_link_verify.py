"""验证归档数据库的正文，而不是只相信接收事件中的成功标记。"""
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from verify_slow_link import verify_database


class DatabaseVerificationTests(unittest.TestCase):
    def test_recycled_history_does_not_mean_transport_loss(self):
        latest = "000000000001" + "7890"
        sources = {0: dict(sha256="older", value_bytes=16),
                   1: dict(sha256=hashlib.sha256(latest.encode()).hexdigest(), value_bytes=16)}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"messages.db"
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE message(new_value TEXT)")
                conn.execute("INSERT INTO message VALUES (?)", (latest,))
            result = verify_database(path, sources, allow_recycling=True)
            self.assertFalse(result["all_correct"])
            self.assertTrue(result["retained_content_correct"])
            self.assertTrue(result["latest_message_present"])
            self.assertTrue(result["verification_passed"])

    def test_detects_changed_database_content_and_missing_message(self):
        original = "000000000000" + "1234567890" * 2
        sources = {0: dict(sha256=hashlib.sha256(original.encode()).hexdigest(), value_bytes=len(original)),
                   1: dict(sha256="missing", value_bytes=len(original))}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"messages.db"
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE message(new_value TEXT)")
                conn.execute("INSERT INTO message VALUES (?)", (original[:-1]+"9",))
            result = verify_database(path, sources)
            self.assertEqual(result["sqlite_integrity"], "ok")
            self.assertEqual(result["content_errors"], [0])
            self.assertEqual(result["missing_sequences"], [1])
            self.assertFalse(result["all_correct"])


if __name__ == "__main__":
    unittest.main()
