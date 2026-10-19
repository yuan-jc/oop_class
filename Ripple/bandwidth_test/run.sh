#!/usr/bin/env bash
# 在工具目录之外也可以调用，路径始终以脚本所在目录为准。
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$script_dir/runner.py" "$@"
