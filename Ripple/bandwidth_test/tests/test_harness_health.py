"""确保观测动作不创建业务连接，并排除异常服务日志。"""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import runner


class HarnessHealthTests(unittest.TestCase):
    def test_service_readiness_uses_listening_table_without_tcp_connection(self):
        experiment = runner.Experiment.__new__(runner.Experiment)
        experiment.args = argparse.Namespace(servers=1, subscribers=0, wire_mode="legacy")
        experiment.root, experiment.database_root = Path("/unused"), Path("/database")
        experiment.server_ns, experiment.server_ip = "server", "10.0.0.1"
        experiment.nodes = "1:10.0.0.1:13001"
        experiment.spawn, experiment.driver = Mock(), Mock()
        experiment.check_alive = Mock()
        experiment.command = Mock(return_value=argparse.Namespace(stdout="LISTEN 0 128 [::ffff:10.0.0.1]:13001 [::]:*\n"))
        def wait(condition, description, *args):
            if description == "服务端 API 端口":
                self.assertTrue(condition())
        experiment.wait = wait
        with patch("runner.subprocess.run", return_value=argparse.Namespace(returncode=0)) as process, patch("runner.time.sleep"):
            experiment.start_services()
        commands = [call.args[0] for call in experiment.command.call_args_list + process.call_args_list]
        self.assertTrue(any("ss" in command for command in commands), "必须使用 ss 读取监听表")
        self.assertFalse(any("python3" in command for command in commands), "禁止短连接探测")

    def test_exception_scan_reports_each_server_and_accepts_normal_log(self):
        self.assertTrue(hasattr(runner, "server_log_warnings"), "需要服务日志异常扫描")
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            (logs/"server-1.log").write_text("normal startup\njava.lang.NullPointerException\n\tat ripple.Worker.run(Worker.java:20)\n")
            (logs/"server-2.log").write_text("normal startup\n")
            warnings = runner.server_log_warnings(logs)
            self.assertEqual(len(warnings), 1)
            self.assertIn("server-1.log", warnings[0])
            self.assertIn("NullPointerException", warnings[0])

    def test_deadline_snapshot_excludes_shutdown_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            path = logs/"server-1.log"
            path.write_text("normal\n")
            size = path.stat().st_size
            with path.open("a") as output:
                output.write("java.lang.NullPointerException\n")
            self.assertEqual(runner.server_log_warnings(logs, {path.name: size}), [])
            self.assertTrue(runner.server_log_warnings(logs))

    def test_live_check_stops_on_service_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            e = runner.Experiment.__new__(runner.Experiment)
            e.root, e.config, e.processes, e.captures = Path(directory), {}, [], []
            (e.root/"logs").mkdir()
            (e.root/"logs/server-1.log").write_text("java.lang.NullPointerException\n")
            with self.assertRaisesRegex(RuntimeError, "服务日志"):
                e.check_alive()
            self.assertEqual(e.config["server_log_scan_stage"], "live")

    def test_preflight_blocks_load_when_server_has_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            experiment = runner.Experiment.__new__(runner.Experiment)
            experiment.root, experiment.config = Path(directory), {}
            (experiment.root/"logs").mkdir()
            (experiment.root/"logs/server-1.log").write_text("java.lang.NullPointerException\n")
            experiment.args = argparse.Namespace(baseline_duration=1, duration=1)
            for name in ("artifacts", "topology", "capture", "start_services", "shape"):
                setattr(experiment, name, Mock())
            experiment.wait = Mock(side_effect=RuntimeError("发送已开始"))
            with patch("runner.time.sleep"), self.assertRaisesRegex(RuntimeError, "服务日志"):
                experiment.run()
            self.assertFalse((experiment.root/"start").exists())
            self.assertTrue(experiment.config["measurement_warnings"])

    def test_report_disqualifies_server_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            experiment = runner.Experiment.__new__(runner.Experiment)
            experiment.root = Path(directory)
            (experiment.root/"logs").mkdir()
            (experiment.root/"logs/server-1.log").write_text("java.lang.NullPointerException\n")
            for point in ("traffic", "cluster", "peers"):
                (experiment.root/"logs"/(point+".log")).write_text("0 packets dropped by kernel\n")
            experiment.args = argparse.Namespace(subscribers=1, size=128)
            experiment.server_ip = "10.0.0.1"
            experiment.config = dict(send_start=0, send_end=1, deadline=2,
                baseline_start=-1, baseline_end=0, planned_messages=1)
            (experiment.root/"events.jsonl").write_text("\n".join(json.dumps(event) for event in [
                dict(event="send", seq=0, id=0, time=.1, lag_ms=0),
                dict(event="put_response", seq=0, id=0, time=.2, ok=True),
                dict(event="receive", seq=0, id=1, time=.3)]) + "\n")
            def capture(path):
                return dict(flows=[], packets=[], decode_issues=[])
            with patch("runner.analyze_pcap", side_effect=capture):
                summary = experiment.report()
            self.assertEqual(summary["status"], "measurement_incomplete")
            self.assertTrue(any("NullPointerException" in warning for warning in summary["measurement_warnings"]))
