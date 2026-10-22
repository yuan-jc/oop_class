import argparse
import hashlib
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import Mock, patch

import runner
from metrics import summarize


class VariantTests(unittest.TestCase):
    def test_cli_defaults_and_modes(self):
        self.assertTrue(hasattr(runner, "argument_parser"), "需要可复用参数解析器")
        parser = runner.argument_parser()
        defaults = parser.parse_args([])
        self.assertEqual((defaults.wire_mode, defaults.payload, defaults.fixed_drain),
                         ("legacy", "random", False))
        args = parser.parse_args(["--wire-mode", "adaptive", "--payload", "structured", "--fixed-drain"])
        self.assertEqual((args.wire_mode, args.payload, args.fixed_drain), ("adaptive", "structured", True))

    def test_all_processes_share_wire_flags(self):
        self.assertTrue(hasattr(runner, "wire_options"), "需要统一 JVM 选项")
        self.assertEqual(runner.wire_options("legacy"),
                         ["-Dripple.wire.compact=false", "-Dripple.wire.compression=false"])
        self.assertEqual(runner.wire_options("compact"),
                         ["-Dripple.wire.compact=true", "-Dripple.wire.compression=false"])
        self.assertEqual(runner.wire_options("adaptive"),
                         ["-Dripple.wire.compact=true", "-Dripple.wire.compression=true"])

    def test_server_publisher_and_subscriber_command_wiring(self):
        experiment = runner.Experiment.__new__(runner.Experiment)
        experiment.args = argparse.Namespace(wire_mode="adaptive", servers=1, subscribers=1,
            size=128, rate=10, duration=1, seed=42, payload="structured")
        experiment.root = Path("/unused")
        experiment.database_root = Path("/database")
        experiment.server_ns, experiment.client_ns = "server", "client"
        experiment.server_ip, experiment.client_ip = "10.0.0.1", "10.0.0.2"
        experiment.nodes, experiment.app, experiment.classpath = "1:10.0.0.1:13001", "app", "classes"
        experiment.spawn, experiment.wait = Mock(), Mock()
        experiment.check_alive = Mock()
        with patch("runner.time.sleep"):
            experiment.start_services()
        self.assertEqual(experiment.spawn.call_count, 3)
        for call in experiment.spawn.call_args_list:
            command = call.args[0]
            self.assertIn("-Dripple.wire.compact=true", command)
            self.assertIn("-Dripple.wire.compression=true", command)
            if "Driver" in command:
                self.assertEqual(command[-1], "structured")

    def test_fixed_drain_does_not_finish_on_delivery(self):
        self.assertTrue(hasattr(runner, "drain_complete"), "需要可验证排空条件")
        result = {"submitted": 1, "missing_at_deadline": 0, "put_success": 1}
        self.assertTrue(runner.drain_complete(result, False, 1, 2))
        self.assertFalse(runner.drain_complete(result, True, 1, 2))
        self.assertTrue(runner.drain_complete(result, True, 2, 2))

    def test_content_mismatch_does_not_change_business_counts(self):
        self.assertTrue(hasattr(runner, "content_integrity"), "需要独立内容完整性统计")
        events = [dict(event=kind, seq=0, id=identifier, time=1, ok=True)
                  for kind, identifier in [("send", 0), ("put_response", 0), ("receive", 1),
                                           ("content_mismatch", 1)]]
        result = summarize(events, 1, 32, 0, 2, 3)
        self.assertEqual((result["received_unique"], result["put_success"]), (1, 1))
        self.assertEqual(runner.content_integrity(events, 3)["corrupt_content"], 1)
        events += [dict(event="content_mismatch", seq=-2, id=1, time=2)]
        self.assertEqual(runner.content_integrity(events, 3)["corrupt_content"], 2)

    def test_source_identity_tracks_content_and_ignores_build_outputs(self):
        self.assertTrue(hasattr(runner, "code_identity"), "需要源码与构建产物身份")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"pom.xml").write_text("a")
            (root/"target").mkdir()
            (root/"target"/"ignored.java").write_text("output")
            original = runner.code_identity(root)
            (root/"target"/"ignored.java").write_text("changed")
            self.assertEqual(original["source_sha256"], runner.code_identity(root)["source_sha256"])
            (root/"pom.xml").write_text("b")
            self.assertNotEqual(original["source_sha256"], runner.code_identity(root)["source_sha256"])
            self.assertEqual(original["source_root"], str(root.resolve()))

    def test_build_identity_is_used_for_exported_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"build-identity.json").write_text(json.dumps(
                {"git_commit": "source-commit", "source_sha256": "recorded-source",
                 "archive_sha256": {"server": "server-archive", "client": "client-archive"}}))
            self.assertEqual(runner.code_identity(root)["git_commit"], "source-commit")
            self.assertEqual(runner.code_identity(root)["source_sha256"], "recorded-source")
            self.assertEqual(runner.code_identity(root)["archive_sha256"]["server"], "server-archive")

    def test_common_dependency_jar_identity(self):
        self.assertTrue(hasattr(runner, "dependency_identity"), "需要依赖 JAR 身份")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for role in ("server", "client"):
                lib = root/role/"lib"
                lib.mkdir(parents=True)
                (lib/"ripple-common-1.0.jar").write_bytes(b"common")
                (lib/"other.jar").write_bytes(b"other")
            identity = runner.dependency_identity(root)
            self.assertEqual(identity["server"]["ripple-common-1.0.jar"], hashlib.sha256(b"common").hexdigest())
            self.assertEqual(identity["client"]["ripple-common-1.0.jar"], identity["server"]["ripple-common-1.0.jar"])

    def test_tool_commit_is_resolved_from_nested_directory(self):
        repository = Path(__file__).resolve().parents[2]
        if not (repository/".git").exists():
            self.skipTest("当前副本没有 Git 身份")
        self.assertRegex(runner.git_commit(repository/"bandwidth_test"), r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
