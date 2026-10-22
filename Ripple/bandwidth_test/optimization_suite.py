"""从Git标签导出不可变源码并执行真实弱网对照，不切换用户工作树。"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tarfile
import tempfile
import time
from support import wire_options

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent / "Ripple"
VERSIONS = {"v0": ("bandwidth-v0-stable", "legacy"),
            "v1": ("bandwidth-v1-stable", "compact"),
            "v2": ("bandwidth-v2-stable", "adaptive")}
CASES = {"random_512": (1024, 100, "random", "512kbit"),
         "random_256": (1024, 100, "random", "256kbit"),
         "structured_512": (1024, 100, "structured", "512kbit"),
         "structured_256": (1024, 100, "structured", "256kbit"),
         "small_512": (32, 500, "random", "512kbit"),
         "bytes_random": (1024, 50, "random", "512kbit"),
         "bytes_structured": (1024, 50, "structured", "512kbit"),
         "bytes_small": (32, 50, "random", "512kbit")}


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            result.update(block)
    return result.hexdigest()


def git(*args, cwd=REPOSITORY):
    return subprocess.check_output(["git", "-c", "safe.directory="+str(cwd), "-c", "core.filemode=false",
                                    "-C", str(cwd), *args], text=True).strip()


def build_version(mode, output):
    reference, _ = VERSIONS[mode]
    commit = git("rev-parse", reference+"^{commit}")
    cache = Path(tempfile.gettempdir()) / "ripple-wire-versions" / commit[:16]
    cache.mkdir(parents=True, exist_ok=True)
    marker = cache / "build-identity.json"
    needed = {role: cache / f"ripple-{role}/target/ripple-{role}-publish.tar.gz" for role in ("server", "client")}
    if marker.exists() and all(p.exists() for p in needed.values()):
        metadata = json.loads(marker.read_text())
        if all(sha256(p) == metadata.get("archive_sha256", {}).get(role) for role, p in needed.items()):
            return cache
    archive_path = cache / "export.tar"
    with archive_path.open("wb") as stream:
        subprocess.run(["git", "-c", "safe.directory="+str(REPOSITORY), "-C", str(REPOSITORY),
                        "archive", "--format=tar", commit], stdout=stream, check=True)
    with tarfile.open(archive_path) as archive:
        archive.extractall(cache, filter="data")
    source_digest = hashlib.sha256()
    with tarfile.open(archive_path) as archive:
        for item in sorted(archive.getmembers(), key=lambda m: m.name):
            if item.isfile():
                source_digest.update(item.name.encode())
                source_digest.update(archive.extractfile(item).read())
    log = Path(output) / (mode+"-build.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        subprocess.run(["mvn", "-B", "package", "-DskipTests"], cwd=cache,
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    identity = dict(git_commit=commit, git_reference=reference, source_sha256=source_digest.hexdigest(),
                    archive_sha256={role: sha256(path) for role, path in needed.items()}, built_at=time.time())
    marker.write_text(json.dumps(identity, indent=2))
    return cache


def flatten_result(summary, config, mode, case, repeat):
    submitted = summary.get("submitted", 0)
    received = summary.get("received_unique", 0)
    downlink = summary.get("captures", {}).get("traffic", {}).get("downlink_send_and_drain", {}).get("frame_bytes", 0)
    expected = summary.get("expected_deliveries", submitted)
    valid = (summary.get("status") == "complete" and not summary.get("measurement_warnings")
             and summary.get("corrupt_content", 0) == 0 and submitted > 0)
    latency = summary.get("latency_ms", {})
    return dict(version=mode, case=case, repeat=repeat, valid=valid,
                commit=config.get("git_commit"), source_sha256=config.get("source_sha256"),
                tool_commit=config.get("tool_git_commit"), submitted=submitted,
                received=received, expected=expected, missing=summary.get("missing_at_deadline"),
                put_success=summary.get("put_success"), corrupt=summary.get("corrupt_content", 0),
                actual_rate=summary.get("actual_submit_rate"), p50_ms=latency.get("p50"), p99_ms=latency.get("p99"),
                delivery_ratio=summary.get("delivery_ratio"), during_ratio=summary.get("delivery_ratio_during_send"),
                downlink_bytes=downlink,
                downlink_bytes_per_delivered=downlink/received if received else None,
                complete_downlink_bytes_per_message=downlink/received if valid and received == expected and received else None,
                total_frame_bytes=summary.get("total_send_and_drain_frame_bytes"),
                warnings="；".join(summary.get("measurement_warnings", [])))


def execute_job(job, builds, args):
    mode, case, repeat = job
    size, rate, payload, bandwidth = CASES[case]
    parent = args.output / f"{case}/{mode}/repeat-{repeat}"
    parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(HERE / "runner.py"), "--ripple-root", str(builds[mode]),
        "--output", str(parent), "--size", str(size), "--rate", str(rate), "--servers", "3",
        "--subscribers", "1", "--duration", str(args.duration), "--drain-timeout", str(args.wait),
        "--baseline-duration", "1", "--seed", str(42+repeat), "--wire-mode", VERSIONS[mode][1],
        "--payload", payload, "--fixed-drain", "--staged-start", "--bandwidth", bandwidth]
    manifest = parent / "invocation.json"
    manifest.write_text(json.dumps(dict(command=command, started_at=time.time()), ensure_ascii=False, indent=2))
    with (parent / "execution.log").open("w") as stream:
        process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
    summaries = list(parent.glob("*/summary.json"))
    if process.returncode != 0 or len(summaries) != 1:
        raise RuntimeError(f"实验失败：{parent}，退出码 {process.returncode}，查看execution.log")
    summary_path = summaries[0]
    summary = json.loads(summary_path.read_text())
    config = json.loads(summary_path.with_name("config.json").read_text())
    row = flatten_result(summary, config, mode, case, repeat)
    row["directory"] = str(summary_path.parent)
    row["server_jar_sha256"] = config.get("jar_sha256", {}).get("server")
    row["client_jar_sha256"] = config.get("jar_sha256", {}).get("client")
    with summary_path.with_name("timeseries.csv").open() as stream:
        row["pending_peak"] = max((int(item["pending"]) for item in csv.DictReader(stream)), default=0)
    stats_path = summary_path.with_name("tc-stats.json")
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    queues = [q for q in stats.get("at_deadline", {}).get("qdisc", []) if q.get("kind") == "bfifo"]
    row["qdisc_backlog_at_deadline"] = sum(q.get("backlog", 0) for q in queues)
    row["qdisc_drops"] = sum(q.get("drops", 0) for q in queues)
    if not row["valid"]:
        raise RuntimeError(f"观测无效或内容不符：{summary_path}，{row['warnings']}")
    return row


def write_results(output, rows):
    ordered = sorted(rows, key=lambda r: (r["case"], r["repeat"], r["version"]))
    (output / "results.json").write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    if ordered:
        with (output / "results.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(ordered[0]))
            writer.writeheader()
            writer.writerows(ordered)


def codec_ledger(builds, output):
    rows = []
    for mode, build in builds.items():
        folder = output / "codec" / mode
        folder.mkdir(parents=True, exist_ok=True)
        with tarfile.open(build / "ripple-client/target/ripple-client-publish.tar.gz") as archive:
            archive.extractall(folder, filter="data")
        classes = folder / "classes"
        classes.mkdir(exist_ok=True)
        classpath = f"{classes}:{folder}/ripple-client.jar:{folder}/lib/*"
        subprocess.run(["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-cp", classpath,
                        "-d", str(classes), str(HERE / "java/Driver.java"), str(HERE / "java/CodecLedger.java")], check=True)
        raw = subprocess.check_output(["java", *wire_options(VERSIONS[mode][1]), "-cp", classpath, "CodecLedger"], text=True)
        rows.extend(dict(json.loads(line), version=mode, commit=json.loads((build / "build-identity.json").read_text())["git_commit"])
                    for line in raw.splitlines() if line.startswith("{"))
    (output / "codec-ledger.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/var/tmp") / ("ripple-wire-results-"+time.strftime("%Y%m%d-%H%M%S")))
    parser.add_argument("--archive-to", type=Path, help="所有实验结束后再复制归档；避免挂载盘并发读写事件")
    parser.add_argument("--versions", nargs="+", choices=VERSIONS, default=list(VERSIONS))
    parser.add_argument("--cases", nargs="+", choices=CASES, default=[case for case in CASES if not case.startswith("bytes_")])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--wait", type=float, default=10)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--ledger-only", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or args.duration <= 0 or args.wait < 0:
        parser.error("重复数和时长应为正，等待时长不可为负")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    builds = {}
    for mode in args.versions:
        print("构建", mode, VERSIONS[mode][0], flush=True)
        builds[mode] = build_version(mode, args.output)
        print("构建就绪", mode, builds[mode], flush=True)
    if args.build_only:
        return
    codec_ledger(builds, args.output)
    if args.ledger_only:
        return
    jobs = [(mode, case, repeat) for repeat in range(1, args.repeats+1)
            for case in args.cases for mode in args.versions]
    (args.output / "suite.json").write_text(json.dumps(dict(
        versions=VERSIONS, jobs=jobs, workers=args.workers, duration=args.duration, wait=args.wait,
        tool_commit=git("rev-parse", "HEAD", cwd=HERE.parent), started_at=time.time()), indent=2))
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_jobs = {executor.submit(execute_job, job, builds, args): job for job in jobs}
        for future in as_completed(future_jobs):
            job = future_jobs[future]
            try:
                row = future.result()
                rows.append(row)
                write_results(args.output, rows)
                print(f"完成 {len(rows)}/{len(jobs)} {job}：提交{row['submitted']}，处理{row['received']}，P99={row['p99_ms']:.2f} ms", flush=True)
            except Exception as error:
                failures.append(dict(job=job, error=str(error)))
                (args.output / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2))
                print("失败", job, str(error), flush=True)
    if failures:
        raise SystemExit(f"{len(failures)}组实验失败；已保留成功和失败证据")
    if args.archive_to:
        destination = args.archive_to.resolve()
        if destination == args.output or destination.is_relative_to(args.output):
            raise ValueError("归档目录不能等于运行目录或位于其中")
        shutil.copytree(args.output, destination, dirs_exist_ok=True)
        print("已归档：", destination, flush=True)


if __name__ == "__main__":
    main()
