"""独立复核断联实验：重建原始载荷、核对数据库及故障注入证据。"""
import hashlib
import json
from pathlib import Path
import re
import sys


def payload(seq, size=256, seed=42):
    # 复现 java.util.Random 的 48 位状态及 nextInt(36)，不依赖接收端内容。
    state = ((seed + seq) ^ 0x5DEECE66D) & ((1 << 48) - 1)
    value = f"RB1:{seq:012d}:"
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    while len(value) < size:
        state = (state * 0x5DEECE66D + 11) & ((1 << 48) - 1)
        bits = state >> 17
        index = bits % len(chars)
        if bits - index + len(chars) - 1 < (1 << 31):
            value += chars[index]
    return value


def main(root):
    manifest = json.loads((root / "manifest.json").read_text())
    rows = []
    for run in manifest["runs"]:
        directory = Path(run["directory"])
        config = json.loads((directory / "config.json").read_text())
        summary = json.loads((directory / "summary.json").read_text())
        assert run["submitted_sequences"] == [0, 1, 2], run["condition"]
        # RST 后服务端可能在通知订阅者时异常，不能把 PUT 成功响应当作前置条件。
        assert summary["submitted"] == 3
        assert run["snapshot_read_errors"] == 0
        assert not run["payload_mismatches"]
        assert run["sql_error_count"] == 0
        for seq, digest in run["observed_payload_sha256"].items():
            expected = hashlib.sha256(payload(int(seq), config["size"], config["seed"]).encode()).hexdigest()
            assert expected == digest, (run["condition"], seq, "载荷不匹配")
        for name, data in run["final_databases"].items():
            assert data["integrity"] == "ok", name
        faults = run["fault_events"]
        if "reset" in run["condition"]:
            resets = [e for e in faults if e["kind"] == "socket_reset"]
            assert resets and all(e.get("original_connections_removed") for e in resets), "未确认原连接已经断开"
        start = next((e["time"] for e in faults if e["kind"] == "blackhole_start"), None)
        end = next((e["time"] for e in faults if e["kind"] == "blackhole_end"), None)
        if start:
            stats = next(e["output"] for e in faults if e["kind"] == "qdisc_before_restore")
            assert any(int(n) > 0 for n in re.findall(r"dropped (\d+)", stats)), "未证实实际丢包"
        premature_during_fault = [sample for sample in run["premature_ack_samples"]
                                  if start and start <= sample["time"] < end]
        missing = run["database_missing_sequences"]
        row = {"condition": run["condition"], "put_success": len(run["successful_put_responses"]),
               "received_events": summary["received_unique"], "database_missing": missing,
               "payload_exact_match": True,
               "premature_ack_sequences_during_fault": sorted({s["seq"] for s in premature_during_fault}),
               "blackhole_seconds": round(end-start, 3) if start else None,
               "observation_after_restore_seconds": round(config["deadline"]-end, 3) if end else None,
               "measurement_status": summary["status"],
               "measurement_warnings": summary["measurement_warnings"]}
        if run["condition"].endswith("control"):
            assert all(not values for values in missing.values()), "正常对照组也出现缺失"
            assert summary["received_unique"] == 3
        rows.append(row)
    result = {"verified_runs": len(rows), "checks": "提交量、原始载荷、数据库完整性、注入实际丢包、正常对照组", "runs": rows}
    (root / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
