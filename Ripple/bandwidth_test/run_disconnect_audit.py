"""冻结实验输入后重跑六种断联条件，记录事前假设及执行版本。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
CONDITIONS = ["subscriber_control", "subscriber_blackhole", "subscriber_reset",
              "cluster_control", "cluster_blackhole", "cluster_blackhole_reset"]
CONTRACT = {
    "scope": "每轮三条 256 字节更新；正式提交序号为 0、1、2；恢复窗口约 30 秒。",
    "interpretation": "可靠性目标由本研究设定，不冒充项目官方承诺；代码预测与可靠性目标分别评价。",
    "healthy_target": {
        "subscriber_control": "订阅者收到 3/3，载荷一致。",
        "subscriber_blackhole": "恢复后收到 3/3，载荷一致。",
        "subscriber_reset": "回调在观察窗口内恢复并补齐 3/3；无未处理异常。",
        "cluster_control": "两个服务器及订阅者均收到 3/3。",
        "cluster_blackhole": "目标未收到时，不应将其标为确认完成；恢复后补齐。",
        "cluster_blackhole_reset": "旧连接销毁后，重连并补发，目标最终收到 3/3。"},
    "source_based_prediction": {
        "subscriber_control": "全部送达。",
        "subscriber_blackhole": "原连接保留，全部延迟补达。",
        "subscriber_reset": "源端保存 3/3；订阅者 0/3；无成功 PUT 响应；出现空指针异常。",
        "cluster_control": "全部送达。",
        "cluster_blackhole": "故障期 ACK 包含目标但目标没有对应消息；最终可由原连接补达。",
        "cluster_blackhole_reset": "源端保存 3/3、PUT 成功 3/3；重连后目标仍缺三条；ACK 已包含目标。"},
    "rejection_rules": ["故障注入没有实际丢包或旧连接未消失则拒绝该轮。",
                        "进程异常退出、读库失败、正式发送量不足则拒绝该轮。",
                        "正常对照也缺失则不能据此归因于指定故障。",
                        "预测不符时如实报告，不将其改写为复现成功。"]}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = [HERE / name for name in ("run_disconnect_audit.py", "disconnect_probe.py", "runner.py",
               "capture.py", "metrics.py", "raw_tcp_reset.py", "verify_disconnect_probe.py", "java/Driver.java")]
    for path in sources:
        target = output / "code_snapshot" / path.relative_to(HERE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    hashes = {str(p.relative_to(BASE)): digest(p) for p in sources}
    for role in ("server", "client"):
        path = BASE / f"Ripple/ripple-{role}/target/ripple-{role}-publish.tar.gz"
        hashes[str(path.relative_to(BASE))] = digest(path)
    git = ["git", "-c", f"safe.directory={BASE / 'Ripple'}", "-C", str(BASE / "Ripple")]
    metadata = {"started_utc": datetime.now().astimezone().isoformat(), "input_sha256": hashes,
                "git_head": subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip(),
                "git_status": subprocess.check_output(git + ["status", "--porcelain"], text=True),
                "namespaces_before": subprocess.check_output(["ip", "netns", "list"], text=True)}
    (output / "expectations.json").write_text(json.dumps(CONTRACT, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "execution.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    command = [sys.executable, "-u", str(HERE / "disconnect_probe.py"), "--output", str(output / "runs")]
    print(json.dumps({"command": command, "conditions": CONDITIONS}, ensure_ascii=False), flush=True)
    result = subprocess.run(command)
    metadata.update(exit_code=result.returncode, ended_utc=datetime.now().astimezone().isoformat(),
                    inputs_unchanged=all(digest(BASE / name) == value for name, value in hashes.items()),
                    namespaces_after=subprocess.check_output(["ip", "netns", "list"], text=True))
    (output / "execution.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if not metadata["inputs_unchanged"]:
        raise RuntimeError("实验期间输入文件发生改变，拒绝当作冻结版本运行")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
