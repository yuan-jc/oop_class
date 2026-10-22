"""控制服务的真实 HTTP 边界测试，不启动网络实验。"""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
import io
import zipfile
import subprocess
import sys
import time

from ripple_lab.config import default_config
from ripple_lab.manager import Manager
from ripple_lab.server import create_server
from ripple_lab.proxy import start_proxy
from ripple_lab.manager import atomic_json


class FakeExperiment:
    def __init__(self, root, run_id, config, base_url):
        self.state = {"id": run_id, "name": config["name"], "config": config,
                      "status": "preparing", "nodes": [], "summary": {}}
    def start(self):
        self.state["status"] = "running"
    def snapshot(self):
        return copy.deepcopy(self.state)
    def stop(self):
        self.state["status"] = "cancelled"
    def stop_sending(self):
        self.state["stage"] = "waiting"


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = Manager(Path(self.temp.name), experiment_factory=FakeExperiment)
        self.server = create_server(self.manager, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.manager.close()
        self.temp.cleanup()
    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        values = {"Content-Type": "application/json"}
        values.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, values)
        response = conn.getresponse()
        status, data = response.status, response.read()
        conn.close()
        return status, data
    def test_defaults_and_static(self):
        status, body = self.request("GET", "/api/defaults")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["protocol"], "hashing")
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/%2e%2e/config.py")[0], 404)
    def test_environment_service_identity(self):
        status, body = self.request("GET", "/api/environment")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["service"], "ripple-lab")
    def test_real_experiment_directory_contract(self):
        from ripple_lab.experiment import Experiment
        instance = Experiment(Path(self.temp.name), "contract-check", default_config(), "http://127.0.0.1:8877")
        try:
            expected = Path(self.temp.name) / "runs" / "contract-check"
            self.assertEqual(instance.root, expected)
            self.assertTrue((expected / "state.json").is_file())
            self.assertTrue((expected / "events.sqlite").is_file())
            self.assertEqual(self.manager.get("contract-check")["id"], "contract-check")
        finally:
            instance.store.close()
    def test_reject_host_and_origin(self):
        self.assertEqual(self.request("GET", "/api/runs", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/runs", default_config(), {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/runs", default_config(), {"Origin": "null"})[0], 403)
    def test_single_active_and_stop(self):
        status, body = self.request("POST", "/api/runs", default_config())
        self.assertEqual(status, 201)
        run_id = json.loads(body)["id"]
        self.assertEqual(self.request("POST", "/api/runs", default_config())[0], 409)
        self.assertEqual(self.request("POST", f"/api/runs/{run_id}/stop-sending", {})[0], 200)
        self.assertEqual(self.request("POST", f"/api/runs/{run_id}/stop", {})[0], 200)
        self.assertEqual(self.request("POST", "/api/runs", default_config())[0], 201)
    def test_config_persistence_and_invalid_query(self):
        self.assertEqual(self.request("POST", "/api/configs", {"name": "测试", "config": default_config()})[0], 201)
        other = Manager(Path(self.temp.name), experiment_factory=FakeExperiment)
        self.assertEqual(other.configs()[0]["name"], "测试")
        other.close()
        self.assertEqual(self.request("POST", "/api/runs", {"nodes": []})[0], 400)
        self.assertEqual(self.request("GET", "/api/runs/../../events")[0], 404)
    def test_historical_download_and_logs(self):
        folder = self.manager.directory("old-run")
        folder.mkdir()
        atomic_json(folder / "state.json", {"id": "old-run", "status": "completed", "config": default_config()})
        (folder / "logs").mkdir()
        (folder / "logs" / "p1.log").write_text("实际节点日志", encoding="utf-8")
        status, body = self.request("GET", "/api/runs/old-run/download")
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertIn("state.json", archive.namelist())
            self.assertEqual(archive.read("logs/p1.log").decode(), "实际节点日志")
        self.assertEqual(self.request("GET", "/api/runs/old-run/logs?node=../../x")[0], 400)
        self.assertEqual(self.request("GET", "/api/runs/old-run/events?limit=0")[0], 400)
        self.assertEqual(self.request("GET", "/api/runs/old-run/events?tail=maybe")[0], 400)
    def test_events_cursor_contract(self):
        class Store:
            def query(store, **kwargs):
                return kwargs
        state = self.manager.create(default_config())
        self.manager.instances[state["id"]].store = Store()
        status, body = self.request("GET", f'/api/runs/{state["id"]}/events?before=99&tail=true&limit=20')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["before"], 99)
        self.assertTrue(json.loads(body)["tail"])
    def test_manager_close_waits_for_cleanup(self):
        state = self.manager.create(default_config())
        instance = self.manager.instances[state["id"]]
        stopped = threading.Event()
        cleaned = threading.Event()
        def cleanup():
            stopped.wait(2)
            cleaned.set()
        instance.thread = threading.Thread(target=cleanup)
        instance.thread.start()
        instance.stop = stopped.set
        self.manager.close()
        self.assertTrue(cleaned.is_set())
        self.assertFalse(instance.thread.is_alive())
    @unittest.skipIf(sys.platform == "win32", "POSIX 信号测试在 WSL 执行")
    def test_sigterm_stops_server(self):
        process = subprocess.Popen([sys.executable, "-m", "ripple_lab.server", "--port", "0",
                                    "--root", self.temp.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = process.stdout.readline()
            self.assertIn("http://127.0.0.1:", line)
            port = int(line.strip().rsplit(":", 1)[1])
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/defaults")
            conn.getresponse().read()
            conn.close()
            process.terminate()
            output, error = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, error)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    def test_proxy_rejects_foreign_host(self):
        proxy, thread = start_proxy("127.0.0.1", self.server.server_port)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
            conn.request("GET", "/", headers={"Host": "evil.example"})
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            conn.close()
        finally:
            proxy.shutdown()
            proxy.server_close()
    def test_proxy_get_post(self):
        proxy, thread = start_proxy("127.0.0.1", self.server.server_port)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
            conn.request("GET", "/api/defaults")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["protocol"], "hashing")
            conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
            conn.request("POST", "/api/configs", json.dumps({"name": "代理", "config": default_config()}), {"Content-Type": "application/json"})
            response = conn.getresponse()
            self.assertEqual(response.status, 201)
            response.read()
            conn.close()
        finally:
            proxy.shutdown()
            proxy.server_close()


if __name__ == "__main__":
    unittest.main()
