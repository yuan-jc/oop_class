"""手动集成验收：确认限速已经生效并开始发消息后，再发送 Ctrl+C 信号。"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

root = Path(__file__).resolve().parents[1]
output = root/"results"/("interrupt-check-"+uuid.uuid4().hex[:6])
before = subprocess.check_output(["ip", "netns", "list"], text=True)
process = subprocess.Popen([sys.executable, str(root/"runner.py"), "--output", str(output),
                            "--servers", "1", "--duration", "60", "--rate", "10",
                            "--bandwidth", "64kbit", "--baseline-duration", "1"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
try:
    deadline = time.monotonic()+100
    run = None
    while time.monotonic() < deadline:
        candidates = list(output.glob("*"))
        if candidates:
            run = candidates[0]
            if (run/"start").exists() and (run/"tc-stats.json").exists():
                break
        if process.poll() is not None:
            raise RuntimeError(process.communicate()[0])
        time.sleep(.1)
    else:
        raise RuntimeError("等待限速负载开始超时")
    time.sleep(1)
    process.send_signal(signal.SIGINT)
    log, _ = process.communicate(timeout=30)
    print(log)
    assert process.returncode == 130, process.returncode
    assert json.loads((run/"summary.json").read_text())["status"] == "interrupted"
    after = subprocess.check_output(["ip", "netns", "list"], text=True)
    assert before == after, "网络命名空间未完整清理"
    config = json.loads((run/"config.json").read_text())
    assert not Path(config["database_runtime_directory"]).exists(), "临时数据库未清理"
    assert (run/"databases").is_dir(), "数据库没有归档"
    stats = json.loads((run/"tc-stats.json").read_text())
    assert stats["configured"]["class"][0]["rate"] == 8000, "64kbit 整形未生效"
    print("限速负载中断验收通过：退出码130、数据库归档、临时目录及网络空间已清理。")
finally:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
