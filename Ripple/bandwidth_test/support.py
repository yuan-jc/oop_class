"""实验变体、身份与完整性辅助逻辑。"""
import hashlib
import json
from pathlib import Path
import re
import subprocess


def wire_options(mode):
    return ["-Dripple.wire.compact=" + str(mode != "legacy").lower(),
            "-Dripple.wire.compression=" + str(mode == "adaptive").lower()]


def drain_complete(result, fixed, now, deadline):
    delivered = (result["submitted"] and result["missing_at_deadline"] == 0
                 and result["put_success"] == result["submitted"])
    return now >= deadline or (not fixed and bool(delivered))


def content_integrity(events, deadline):
    mismatches = [event for event in events
                  if event["event"] == "content_mismatch" and event["seq"] != -1
                  and event["time"] <= deadline]
    return {"corrupt_content": len(mismatches),
            "corrupt_content_unique": len({(event["id"], event["seq"]) for event in mismatches})}


def server_log_warnings(logs, limits=None):
    warnings = []
    exception = re.compile(r"\b[\w.$]*(?:Exception|Error)\b|^\s+at\s+[\w.$]+\([^)]*\)")
    for path in sorted(Path(logs).glob("server-*.log")):
        # 逐行扫描、每个服务只取第一条证据，异常风暴时也保持固定内存。
        remaining = path.stat().st_size if limits is None else limits.get(path.name, 0)
        with path.open("rb") as source:
            number = 0
            while remaining > 0:
                raw = source.readline(remaining)
                if not raw:
                    break
                remaining -= len(raw)
                number += 1
                line = raw.decode("utf-8", errors="replace")
                if exception.search(line):
                    warnings.append(f"服务日志异常 {path.name}:{number}: {line.strip()[:300]}")
                    break
    return warnings


def git_commit(root):
    root = Path(root).resolve()
    repository = next((path for path in (root, *root.parents) if (path/".git").exists()), root)
    result = subprocess.run(["git", "-c", "safe.directory=" + str(repository),
                             "-c", "core.filemode=false", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dependency_identity(assets):
    return {role: {path.name: file_sha256(path)
                   for path in sorted((Path(assets)/role/"lib").glob("*.jar"))}
            for role in ("server", "client")}


def code_identity(root):
    root = Path(root).resolve()
    recorded = root/"build-identity.json"
    if recorded.is_file():
        identity = json.loads(recorded.read_text(encoding="utf-8"))
        selected = {"source_root": str(root), "git_commit": identity["git_commit"],
                    "source_sha256": identity["source_sha256"]}
        if "archive_sha256" in identity:
            selected["archive_sha256"] = identity["archive_sha256"]
        return selected
    digest = hashlib.sha256()
    # 排除构建输出；路径与内容共同参与摘要，防止同内容不同源码布局被混淆。
    paths = sorted(path for path in root.rglob("*") if path.is_file()
                   and path.suffix in (".java", ".xml", ".properties")
                   and not {"target", ".git"}.intersection(path.relative_to(root).parts))
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(file_sha256(path)))
    return {"source_root": str(root), "git_commit": git_commit(root),
            "source_sha256": digest.hexdigest(), "source_files": len(paths)}
