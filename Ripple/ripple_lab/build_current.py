"""可独立执行的当前源码构建检查。"""
import json
from pathlib import Path
import sys

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ripple_lab.build import build

if __name__ == "__main__":
    log = Path(__file__).parent / "build-check.log"
    print(json.dumps(build(log), ensure_ascii=False, indent=2))
