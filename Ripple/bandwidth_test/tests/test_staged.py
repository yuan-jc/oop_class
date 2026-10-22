import argparse
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

import runner


class StagedTests(unittest.TestCase):
    def test_staged_order_opens_all_listeners_before_cluster_and_clients(self):
        with tempfile.TemporaryDirectory() as directory:
            e = runner.Experiment.__new__(runner.Experiment)
            e.root = Path(directory)
            e.args = argparse.Namespace(servers=2, subscribers=0, wire_mode="compact", staged_start=True)
            e.database_root, e.server_ns, e.server_ip = Path("/database"), "server", "10.0.0.1"
            e.server_classpath, e.nodes = "server-cp", "nodes"
            e.spawn, e.driver = Mock(), Mock()
            phases = []
            def wait(condition, description, *args):
                phases.append(description)
                if description == "全部服务监听":
                    self.assertEqual(e.spawn.call_count, 2)
                    self.assertFalse((e.root/"cluster.start").exists())
                if description == "全部集群初始化":
                    self.assertTrue((e.root/"cluster.start").exists())
                    self.assertFalse(e.driver.called)
            e.wait = wait
            with patch("runner.time.sleep") as sleep:
                e.start_services()
            self.assertIn("全部服务监听", phases)
            self.assertIn("全部集群初始化", phases)
            sleep.assert_not_called()
            for call in e.spawn.call_args_list:
                self.assertIn("ServerDriver", call.args[0])
            self.assertTrue(runner.argument_parser().parse_args(["--staged-start"]).staged_start)

    @unittest.skipUnless(shutil.which("javac"), "需要 JDK")
    def test_server_fixture_compiles_against_real_server(self):
        here = Path(__file__).resolve().parents[1]
        archive = here.parent/"Ripple/ripple-server/target/ripple-server-publish.tar.gz"
        if not archive.is_file():
            self.skipTest("需要服务端发行包")
        self.assertTrue((here/"java/ServerDriver.java").is_file(), "需要分阶段服务夹具")
        with tempfile.TemporaryDirectory() as directory:
            with tarfile.open(archive) as source:
                source.extractall(directory, filter="data")
            subprocess.run(["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8",
                "-cp", f"{directory}/ripple-server.jar:{directory}/lib/*", "-d", directory,
                str(here/"java/ServerDriver.java"), str(here/"tests/ServerDriverHealthCheck.java")], check=True)
            subprocess.run(["java", "-cp", f"{directory}:{directory}/ripple-server.jar:{directory}/lib/*",
                            "ServerDriverHealthCheck"], check=True)
