"""核对中断前后输入一致，将已完成的两段实验交给独立审计。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

BASE = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True, type=Path)
    options = parser.parse_args()
    suite = options.suite.resolve()
    execution = json.loads((suite / "execution.json").read_text())
    first = json.loads((suite / "runs/manifest.json").read_text())["runs"]
    second = json.loads((suite / "recovery_runs/manifest.json").read_text())["runs"]
    assert {r["condition"] for r in first} == {"subscriber_control", "subscriber_blackhole", "subscriber_reset", "cluster_control"}
    assert {r["condition"] for r in second} == {"cluster_blackhole", "cluster_blackhole_reset"}
    hashes = execution["input_sha256"]
    assert all(hashlib.sha256((BASE / name).read_bytes()).hexdigest() == value for name, value in hashes.items())
    roots = [Path(r["directory"]) for r in first+second]
    assert all((root / "databases").is_dir() and not (root / "probe-failure.json").exists() for root in roots)
    namespaces = subprocess.check_output(["ip", "netns", "list"], text=True)
    assert not namespaces.strip(), "还有实验网络命名空间未清理"
    subprocess.run([sys.executable, str(BASE / "bandwidth_test/audit_disconnect_evidence.py"),
                    "--runs", *map(str, roots), "--output", str(suite / "audit")], check=True)
    validation = {"validated_at": datetime.now().astimezone().isoformat(),
                  "original_execution_completed": "exit_code" in execution,
                  "interruption": "原始六场景运行在 WSL 会话中断后停止；只保留其完整结束的前四场景。",
                  "completed_segments": {"runs": [r["condition"] for r in first],
                                         "recovery_runs": [r["condition"] for r in second]},
                  "all_original_inputs_unchanged": True, "valid_completed_runs": len(roots),
                  "namespaces_after": namespaces, "independent_raw_audit_exit_code": 0}
    (suite / "recovery-validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    tool_dir = suite / "audit/audit_code"
    tool_dir.mkdir(exist_ok=True)
    tool_hashes = {}
    for name in ("audit_disconnect_evidence.py", "build_disconnect_dossier.py", "finalize_disconnect_audit.py"):
        source = BASE / "bandwidth_test" / name
        shutil.copy2(source, tool_dir / name)
        tool_hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    (tool_dir / "sha256.json").write_text(json.dumps(tool_hashes, indent=2), encoding="utf-8")
    subprocess.run([sys.executable, str(BASE / "bandwidth_test/build_disconnect_dossier.py"),
                    "--suite", str(suite)], check=True)


if __name__ == "__main__":
    main()
