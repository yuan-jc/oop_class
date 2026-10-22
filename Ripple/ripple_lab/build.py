"""对工作区源码做独立构建；源码或适配器变化都会失效缓存。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "Ripple"


def source_files(root):
    return sorted(p for p in root.rglob("*") if p.is_file()
                  and not {".git", "target", ".idea"}.intersection(p.relative_to(root).parts))


def fingerprint(root):
    digest = hashlib.sha256()
    for path in source_files(root):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build(log_path, cancelled=lambda: False, source=SOURCE):
    source = Path(source)
    if not (source / "pom.xml").is_file():
        raise RuntimeError(f"找不到 Ripple 源码：{source}")
    source_hash = fingerprint(source)
    adapter_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted((HERE / "java").glob("*.java")))).hexdigest()
    cache_root = Path(os.environ.get("RIPPLE_LAB_CACHE", tempfile.gettempdir()+"/ripple-lab-build"))
    target = cache_root / source_hash[:20]
    target.mkdir(parents=True, exist_ok=True)
    metadata_path = target / "build.json"
    git = ["git", "-c", f"safe.directory={source}", "-c", "core.filemode=false", "-C", str(source)]
    def git_output(args):
        result = subprocess.run(git+args, text=True, capture_output=True)
        return result.stdout.strip() if result.returncode == 0 else "不可用"
    metadata = {"source_path": str(source), "source_hash": source_hash, "adapter_hash": adapter_hash,
                "commit": git_output(["rev-parse", "HEAD"]), "changes": git_output(["status", "--porcelain"]),
                "java": subprocess.run(["java", "-version"], text=True, capture_output=True).stderr.strip()}
    needed = [target / role / f"ripple-{role}.jar" for role in ("server", "client")]
    cache_ok = metadata_path.is_file() and all(path.is_file() for path in needed)
    if cache_ok:
        previous = json.loads(metadata_path.read_text())
        cache_ok = all(hashlib.sha256(path.read_bytes()).hexdigest() == previous.get(path.name) for path in needed)
    with Path(log_path).open("w", encoding="utf-8") as log:
        def execute(command, cwd=None):
            log.write("执行："+" ".join(map(str, command))+"\n")
            log.flush()
            process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while process.poll() is None:
                if cancelled():
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                    raise InterruptedError("构建已取消")
                time.sleep(.1)
            if process.returncode:
                raise RuntimeError("构建失败，请查看构建日志；没有回退旧发行包")
        if not cache_ok:
            workspace = target / "source"
            # 构建只写缓存，不改变工作区 target 或测试发行包。
            for path in source_files(source):
                destination = workspace / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            execute(["mvn", "-B", "-DskipTests", "package"], workspace)
            if fingerprint(source) != source_hash:
                raise RuntimeError("构建期间源码发生变化，请重新开始实验")
            for role in ("server", "client"):
                archive = workspace / f"ripple-{role}/target/ripple-{role}-publish.tar.gz"
                folder = target / role
                folder.mkdir(exist_ok=True)
                with tarfile.open(archive) as stream:
                    stream.extractall(folder, filter="data")
        else:
            log.write("源码摘要与构建产物一致，复用已验证缓存。\n")
        classes = target / ("adapter-"+adapter_hash[:16])
        classpath = ":".join([str(classes), str(target / "server/ripple-server.jar"),
                              str(target / "client/ripple-client.jar"), str(target / "server/lib/*"),
                              str(target / "client/lib/*")])
        if not (classes / "LabNode.class").is_file():
            classes.mkdir(exist_ok=True)
            execute(["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-cp", classpath,
                     "-d", str(classes)]+[str(p) for p in sorted((HERE / "java").glob("*.java"))])
            execute(["java", "-cp", classpath, "LabNode", "--self-test"])
        for path in needed:
            metadata[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        metadata.update(built_at=time.time(), reused_cache=cache_ok, classpath=classpath)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata
