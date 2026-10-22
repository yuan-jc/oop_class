"""通过真实 HTTP 启动 JVM/tc；执行：python3 -m ripple_lab.tests.integration。"""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
import zipfile
import io


def request(path, body=None):
    raw = json.dumps(body).encode() if body is not None else None
    with urlopen(Request("http://127.0.0.1:8877"+path, data=raw,
                         headers={"Content-Type": "application/json"}), timeout=30) as response:
        return json.load(response)


def execute(name, config):
    config.update(name=name, open_node_pages=False, baseline_seconds=.2)
    state = request("/api/runs", config)
    run_id = state["id"]
    print(name, run_id, flush=True)
    deadline = time.monotonic()+180
    checked_proxy = False
    while state["status"] not in ("completed", "failed", "cancelled"):
        if state["nodes"] and not checked_proxy:
            with urlopen(state["nodes"][0]["original_url"], timeout=10) as response:
                assert response.status == 200
                assert b"html" in response.read().lower()
            checked_proxy = True
        if time.monotonic() > deadline:
            request(f"/api/runs/{run_id}/stop", {})
            raise TimeoutError(name)
        time.sleep(.5)
        state = request("/api/runs/"+run_id)
    assert state["status"] == "completed", state.get("error")
    assert state["summary"]["observation_gaps"] == 0, state["warnings"]
    with urlopen("http://127.0.0.1:8877/api/runs/"+run_id+"/download", timeout=30) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
        assert "state.json" in archive.namelist()
        assert any(n.endswith(".pcap") for n in archive.namelist())
    event = request(f"/api/runs/{run_id}/events?tail=1&limit=5")
    assert len(event["events"]) == 5
    print(json.dumps(dict(id=run_id, summary=state["summary"], warnings=state["warnings"]), ensure_ascii=False), flush=True)
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="ripple_lab/integration-results.json")
    args = parser.parse_args()
    results = []
    default = request("/api/defaults")
    default["nodes"][1].update(duration=2, rate=5, size=1024)
    default["wait_seconds"] = 3
    baseline = execute("验证-正常链路", default)
    assert baseline["summary"]["submitted"] == baseline["summary"]["received_unique"] == 10
    results.append(baseline)
    default["links"] = [dict(source="s1", target="c1", bandwidth_kbit=64, delay_ms=0,
        loss_percent=100, queue_bytes=8192)]
    outage = execute("验证-持续100%丢包", default)
    assert outage["summary"]["submitted"] == 10
    assert outage["summary"]["received_unique"] == 0
    results.append(outage)
    default["nodes"][1].update(duration=3)
    default["wait_seconds"] = 7
    default["links"][0].update(loss_percent=0, fault_start=0, fault_duration=2)
    recovery = execute("验证-100%丢包后恢复", default)
    assert recovery["summary"]["submitted"] == recovery["summary"]["received_unique"] == 15
    results.append(recovery)
    multi = request("/api/defaults")
    multi["nodes"].insert(1, dict(id="s2", role="server", label="服务端2"))
    multi["nodes"][2].update(duration=2, rate=3)
    multi["nodes"].append(dict(id="p2", role="publisher", label="发布者2", server="s2", size=2048, rate=4, duration=2, seed=7))
    multi["nodes"].append(dict(id="c2", role="subscriber", label="订阅者2", server="s2"))
    multi["wait_seconds"] = 4
    several = execute("验证-双服务双发布双订阅", multi)
    assert several["summary"]["submitted"] == 14
    assert several["summary"]["received_unique"] == 28
    results.append(several)
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("四组真实实验及原版网页/ZIP接口验证通过", flush=True)


if __name__ == "__main__":
    main()
