"""按明确参数选择九组完整带宽证据，保留原运行目录与选择清单。"""
import argparse
import json
from pathlib import Path
import shutil
from optimization_suite import write_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("large", type=Path)
    parser.add_argument("small", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive-to", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    selected, sources = [], []
    for source, cases in ((args.large, {"bytes_random", "bytes_structured"}), (args.small, {"bytes_small"})):
        source = source.resolve()
        rows = json.loads((source/"results.json").read_text())
        for row in rows:
            if row["case"] not in cases:
                continue
            if not row["valid"] or row["missing"] or row["corrupt"]:
                raise ValueError("禁止选择未完成或异常结果")
            runtime = Path(row["directory"])
            config = json.loads((runtime/"config.json").read_text())
            if config["rate"] != 50 or config["duration"] != 2 or config["drain_timeout"] != 3:
                raise ValueError("所选工作负载参数不一致")
            target = output / row["case"] / row["version"] / runtime.name
            shutil.copytree(runtime, target)
            row.update(runtime_directory=str(runtime), directory=str(target), archive_relative_directory=str(target.relative_to(output)))
            selected.append(row)
        sources.append(dict(source=str(source), cases=sorted(cases)))
    if len(selected) != 9 or len({(r["case"], r["version"]) for r in selected}) != 9:
        raise ValueError("所选结果不满足三版本三场景")
    write_results(output, selected)
    shutil.copy2(args.large/"codec-ledger.json", output/"codec-ledger.json")
    (output/"selection.json").write_text(json.dumps(dict(sources=sources,
        reason="按用户收敛后的带宽占用范围，统一50条每秒且全量交付；排除300条每秒预备组及未完成性能组"),
        ensure_ascii=False, indent=2), encoding="utf-8")
    if args.archive_to:
        destination = args.archive_to.resolve()
        if destination.exists():
            raise ValueError("归档目标已存在，禁止覆盖")
        shutil.copytree(output, destination)
    print("九组证据已整理：", output)


if __name__ == "__main__":
    main()
