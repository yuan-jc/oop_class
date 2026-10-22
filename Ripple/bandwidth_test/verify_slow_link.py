"""结束后统一复核低速链路结果、两端哈希与服务端/订阅端数据库正文。"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

import runner
from slow_link_suite import assess_events


def verify_database(path, sources, allow_recycling=False):
    seen, errors, duplicates, unexpected = set(), set(), [], []
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True) as conn:
        integrity = ";".join(row[0] for row in conn.execute("PRAGMA integrity_check"))
        for (value,) in conn.execute("SELECT new_value FROM message WHERE new_value IS NOT NULL"):
            try:
                seq = int(value[:12])
            except ValueError:
                unexpected.append("无法解析序号")
                continue
            if seq == -1:
                continue
            if seq not in sources:
                unexpected.append(seq)
                continue
            if seq in seen:
                duplicates.append(seq)
            seen.add(seq)
            data = value.encode("utf-8")
            if len(data) != sources[seq]["value_bytes"] or hashlib.sha256(data).hexdigest() != sources[seq]["sha256"]:
                errors.add(seq)
    missing = sorted(set(sources)-seen)
    retained_ok = integrity == "ok" and bool(seen) and not (errors or duplicates or unexpected)
    latest_present = bool(sources) and max(sources) in seen
    return dict(sqlite_integrity=integrity, expected=len(sources), present=len(seen),
        missing_sequences=missing, content_errors=sorted(errors), duplicate_sequences=duplicates,
        unexpected_sequences=unexpected,
        all_correct=retained_ok and not missing, retained_content_correct=retained_ok,
        latest_message_present=latest_present, history_recycling_allowed=allow_recycling,
        verification_passed=retained_ok and latest_present and (allow_recycling or not missing))


def verify_suite(root):
    runs = []
    identities, inputs = set(), {}
    config = json.loads((root/"suite-config.json").read_text())
    expected_runs = {(case,repeat) for case in config["cases"] for repeat in range(1,config["repeats"]+1)}
    for file in sorted(root.glob("*/repeat-*/slow-link-summary.json")):
        folder = file.parent
        saved = json.loads(file.read_text())
        config = json.loads((folder/"config.json").read_text())
        events = runner.read_events(folder, live=False)
        start = next(e["time"] for e in events if e["event"] == "load_start")
        recalculated, rows = assess_events(events, start, config["duration"], config["size"])
        sources = {e["seq"]:e for e in events if e["event"] == "payload_source" and e["seq"] >= 0}
        databases = {name:verify_database(folder/"databases"/(name+".db"),sources,allow_recycling=True)
            for name in ("server-1", "subscriber-1")}
        identities.add((config["git_commit"], json.dumps(config["jar_sha256"],sort_keys=True),
            tuple(config["wire_jvm_options"])))
        digest = {seq:event["sha256"] for seq,event in sources.items()}
        reference = inputs.setdefault(saved["repeat"],digest)
        fields_match = all(saved.get(key) == value for key,value in recalculated.items())
        load_complete = saved.get("load_complete", saved["submitted"] == saved["intended_messages"])
        capture_warnings = [w for w in saved["warnings"] if w.startswith("TCP 序列存在缺口：")]
        other_warnings = [w for w in saved["warnings"] if w not in capture_warnings]
        run_ok = (fields_match and reference == digest and load_complete
            and recalculated["all_content_correct"] and all(d["verification_passed"] for d in databases.values())
            and all(row["latency_s"] >= 0 for row in rows)
            and saved["runner_status"] in ("complete", "measurement_incomplete") and not other_warnings)
        runs.append(dict(case=saved["case"],repeat=saved["repeat"],
            statistics_recomputed=fields_match, same_inputs_as_other_cases=reference == digest,
            verified_received=sum(row["correct"] for row in rows),databases=databases,
            packet_capture_complete=not capture_warnings, capture_warnings=capture_warnings,
            other_warnings=other_warnings,passed=run_ok))
    actual_runs = {(run["case"],run["repeat"]) for run in runs}
    return dict(passed=bool(runs) and actual_runs == expected_runs and len(identities) == 1 and all(run["passed"] for run in runs),
        verification_scope="交付时间、全量事件哈希及仍保留的数据库正文；历史回收不等于传输丢失；抓包缺口单独报告",
        expected_runs=sorted(expected_runs),actual_runs=sorted(actual_runs),
        same_source_and_jars=len(identities) == 1,
        all_packet_captures_complete=bool(runs) and all(run["packet_capture_complete"] for run in runs),runs=runs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    args = parser.parse_args()
    result = verify_suite(args.directory.resolve())
    runner.write_json(args.directory/"unified-verification.json",result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
