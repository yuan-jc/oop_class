"""单服务端低速链路三组实验：限速、额外延时、随机丢包及全文核验。"""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import shutil
import signal
import sys
import time
import traceback

import runner
import optimization_suite


CASES = {"base": "仅限速", "delay": "限速加传播延时", "loss": "限速加随机丢包"}


def assess_events(events, start, duration, size):
    """以指定停发时刻为边界，按每个序号的首次业务接收统计。"""
    sends = {e["seq"]: e for e in events if e["event"] == "send" and e["seq"] >= 0}
    sources = {e["seq"]: e for e in events if e["event"] == "payload_source" and e["seq"] in sends}
    receives, content, duplicates = {}, {}, 0
    for e in sorted(events, key=lambda row: row["time"]):
        if e["seq"] not in sends or e["id"] != 1:
            continue
        if e["event"] == "receive":
            if e["seq"] in receives:
                duplicates += 1
            else:
                receives[e["seq"]] = e
        if e["event"] == "payload_received":
            content.setdefault(e["seq"], []).append(e)
    rows = []
    for seq, sent in sorted(sends.items()):
        source, received, checked = sources.get(seq), receives.get(seq), content.get(seq, [])
        correct = bool(source and received and checked and source.get("value_bytes") == size
            and all(e.get("ok") and e.get("value_bytes") == size
                    and e.get("sha256") == source.get("sha256") for e in checked))
        rows.append(dict(seq=seq, send_s=sent["time"]-start,
            first_receive_s=received["time"]-start if received else None,
            latency_s=received["time"]-sent["time"] if received else None,
            arrived_by_send_end=bool(received and received["time"] <= start+duration),
            source_sha256=source.get("sha256") if source else None,
            received_sha256=checked[0].get("sha256") if checked else None,
            source_bytes=source.get("value_bytes") if source else None,
            received_bytes=checked[0].get("value_bytes") if checked else None,
            received=bool(received), correct=correct))
    missing = len(sends)-len(receives)
    last = max((e["time"]-start for e in receives.values()), default=None)
    correct_count = sum(row["correct"] for row in rows)
    errors = sum(bool(content.get(row["seq"])) and not row["correct"] for row in rows)
    at_end = sum(row["arrived_by_send_end"] for row in rows)
    return dict(submitted=len(sends), received_at_send_end=at_end,
        remaining_at_send_end=len(sends)-at_end, received_final=len(receives), missing_final=missing,
        last_first_arrival_s=last,
        all_arrived_after_stop_s=max(0, last-duration) if last is not None and not missing else None,
        correct_messages=correct_count, content_error_messages=errors, duplicates=duplicates,
        unverified_received=len(receives)-correct_count-errors,
        all_content_correct=bool(sends) and correct_count == len(sends) and errors == 0), rows


class SlowExperiment(runner.Experiment):
    def __init__(self, args, root):
        super().__init__(args, root)
        self.last_progress = 0
        self.config.update(payload_description="2048字节默认值：前12位十进制序号，其余为随机数字；无额外测试头",
            deadline_definition="load_start加duration；独立于控制进程轮询时间",
            loss_scope="服务端bench0下行的网络包，非业务消息比例",
            delay_scope="下行附加传播延时，不包含排队与序列化",
            correctness="发送端与接收端UTF-8字节数和SHA-256匹配，接收端另做确定性全文比较")

    def shape(self):
        rate = str(runner.parse_bandwidth(self.args.bandwidth))+"bit"
        self.command(["tc", "qdisc", "add", "dev", "bench0", "root", "handle", "1:",
            "tbf", "rate", rate, "burst", "1600", "limit", str(self.args.queue_bytes)], self.server_ns)
        self.config.update(bandwidth_bps=runner.parse_bandwidth(self.args.bandwidth),
            shaper="TBF", burst_bytes=1600, burst_note="令牌桶允许最多1600B初始突发；长期速率1024B/s默认值")
        if self.args.delay_ms or self.args.loss_percent:
            arguments = ["tc", "qdisc", "replace", "dev", "bench0", "parent", "1:1",
                "handle", "10:", "netem", "limit", str(max(1000, self.args.queue_bytes//1500))]
            if self.args.delay_ms:
                arguments += ["delay", str(self.args.delay_ms)+"ms"]
            if self.args.loss_percent:
                arguments += ["loss", "random", str(self.args.loss_percent)+"%", "seed", str(self.args.seed)]
            self.command(arguments, self.server_ns)
        self.tc_stats("configured")

    def wait(self, condition, description, timeout=30):
        result = super().wait(condition, description, timeout)
        if description == "发送结束":
            self.tc_stats("send_end")
            events = runner.read_events(self.root)
            start = next(e["time"] for e in events if e["event"] == "load_start")
            checkpoint, _ = assess_events(events, start, self.args.duration, self.args.size)
            runner.write_json(self.root/"send-end-checkpoint.json", checkpoint)
            print("停发检查点："+json.dumps(checkpoint, ensure_ascii=False), flush=True)
        return result

    def check_alive(self):
        super().check_alive()
        if time.monotonic()-self.last_progress >= 15:
            self.last_progress = time.monotonic()
            events = runner.read_events(self.root)
            starts = [e["time"] for e in events if e["event"] == "load_start"]
            if starts:
                result, _ = assess_events(events, starts[0], self.args.duration, self.args.size)
                print("进度："+json.dumps(dict(elapsed_s=round(time.time()-starts[0], 1),
                    submitted=result["submitted"], received=result["received_final"],
                    correct=result["correct_messages"]), ensure_ascii=False), flush=True)


def execute_case(args, case, repeat, build):
    root = args.output/case/f"repeat-{repeat}"
    (root/"logs").mkdir(parents=True, exist_ok=False)
    run_args = runner.argument_parser().parse_args(["--ripple-root", str(build), "--output", str(root),
        "--servers", "1", "--subscribers", "1", "--size", str(args.size), "--rate", str(args.rate),
        "--duration", str(args.duration), "--drain-timeout", str(args.max_wait), "--baseline-duration", "1",
        "--seed", str(args.seed+repeat-1), "--bandwidth", str(args.bandwidth_bytes*8)+"bit",
        "--wire-mode", "legacy", "--staged-start"])
    run_args.payload = "digits"
    run_args.delay_ms = args.delay_seconds*1000 if case == "delay" else 0
    run_args.loss_percent = args.loss_percent if case == "loss" else 0
    experiment = SlowExperiment(run_args, root)
    runner.write_json(root/"config.json", experiment.config)
    try:
        summary = experiment.run()
    finally:
        experiment.cleanup()
    events = runner.read_events(root, live=False)
    start = next(e["time"] for e in events if e["event"] == "load_start")
    result, rows = assess_events(events, start, args.duration, args.size)
    result.update(case=case, repeat=repeat, description=CASES[case],
        configured_bandwidth_bytes_s=args.bandwidth_bytes, payload_bytes=args.size,
        intended_messages=math.ceil(args.rate*args.duration), duration_s=args.duration,
        delay_ms=run_args.delay_ms, loss_percent=run_args.loss_percent,
        wait_observed_s=summary["drain_duration_s"], runner_status=summary["status"],
        warnings=summary.get("measurement_warnings", []), git_commit=experiment.config.get("git_commit"),
        directory=str(root), recorded_server_delay_ms=run_args.delay_ms,
        wait_limit_s=args.max_wait)
    result["load_complete"] = result["submitted"] == result["intended_messages"]
    runner.write_json(root/"slow-link-summary.json", result)
    runner.write_csv(root/"per-message-integrity.csv", rows, list(rows[0]) if rows else ["seq"])
    return result


def write_outputs(output, results):
    runner.write_json(output/"results.json", results)
    if results:
        runner.write_csv(output/"results.csv", results, list(results[0]))
    lines = ["# 单服务端低速链路实测", "", "每组同一原版代码、同一输入；正文是数字字符串，无压缩。",
        "", "|组别|提交|停发时到达|停发时未到达|最后首次到达（起发后s）|收齐（停发后s）|最终缺失|正确条数|内容错误|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    number = lambda value: "未收齐" if value is None else f"{value:.3f}"
    for row in results:
        lines.append(f"|{row['case']} #{row['repeat']}|{row['submitted']}|{row['received_at_send_end']}|"
            f"{row['remaining_at_send_end']}|{number(row['last_first_arrival_s'])}|"
            f"{number(row['all_arrived_after_stop_s'])}|{row['missing_final']}|{row['correct_messages']}|"
            f"{row['content_error_messages']}|")
    lines += ["", "停发时刻按起发时间＋设定持续时间计算；到达按订阅端业务处理器返回计时。",
        "默认正文输入2048 B/s，出口配置1024 B/s，正文之外仍有协议头、回复与重传；自定义参数以各组config为准。",
        "TBF允许1600 B初始突发，长期速率受限；延时/丢包由其子netem队列实现。",
        "额外2秒延时不是最终端到端延迟；50%丢包作用于网络包。",
        "最后首次到达是各序号首次到达的最大值，重复收件不延后该值。",
        "仅在全部消息收齐、长度与哈希匹配、接收端全文一致时，才认定全量内容正确。",
        "使用原版线格式稳定基线，关闭压缩与紧凑编码；原始config、抓包、tc统计、逐条CSV与数据库保留在各组目录。"]
    (output/"README.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path('/var/tmp')/('ripple-slow-link-'+time.strftime('%Y%m%d-%H%M%S')))
    parser.add_argument("--archive-to", type=Path)
    parser.add_argument("--ripple-root", type=Path, help="指定已有发行包根目录；默认独立构建原版标签")
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    for name, kind, default in [("size", int, 2048), ("rate", float, 1), ("duration", float, 60),
        ("bandwidth-bytes", int, 1024), ("delay-seconds", float, 2), ("loss-percent", float, 50),
        ("max-wait", float, 1800), ("seed", int, 42), ("repeats", int, 1)]:
        parser.add_argument("--"+name, type=kind, default=default)
    parser.add_argument("--source-ref", default="bandwidth-v0-stable", help="默认原版线格式共同连接修复基线")
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error("请在WSL/Linux中以root运行，测试使用独立网络命名空间")
    if any(not math.isfinite(v) or v <= 0 for v in [args.rate,args.duration,args.max_wait,args.bandwidth_bytes,args.repeats]) or args.size < 12:
        parser.error("频率、时长、带宽、重复数须为正，正文至少12字节")
    if not 0 <= args.loss_percent <= 100 or not math.isfinite(args.delay_seconds) or args.delay_seconds < 0:
        parser.error("丢包率须为0到100，额外延时须为有限非负数")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    runner.write_json(args.output/"suite-config.json", {k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()})
    if args.ripple_root:
        build = args.ripple_root.resolve()
    else:
        optimization_suite.VERSIONS["v0"] = (args.source_ref, "legacy")
        build = optimization_suite.build_version("v0", args.output)
    results = []
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        for repeat in range(1,args.repeats+1):
            for case in args.cases:
                print(f"开始 {case} 第{repeat}轮：{args.output}", flush=True)
                result = execute_case(args, case, repeat, build)
                results.append(result)
                write_outputs(args.output, results)
                print("完成："+json.dumps(result, ensure_ascii=False), flush=True)
    except BaseException:
        (args.output/"failure.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
    finally:
        if args.archive_to:
            shutil.copytree(args.output,args.archive_to/args.output.name,dirs_exist_ok=True)
    return 0 if all(r["all_content_correct"] and r["load_complete"] and not r["warnings"] for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
