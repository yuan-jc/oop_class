"""把同一连接表修复保存到三个版本；使用临时Git索引，不切换工作树。"""
import os
from pathlib import Path
import subprocess
import tempfile

REPOSITORY = Path(__file__).resolve().parents[1] / "Ripple"
FILES = ("ripple-server/src/main/java/ripple/server/tcp/NettyServer.java",
         "ripple-server/src/test/java/ripple/server/tcp/NettyServerTest.java")


def command(*args, env=None):
    return subprocess.check_output(["git", "-c", "safe.directory="+str(REPOSITORY), "-C", str(REPOSITORY),
                                    *args], text=True, env=env).strip()


def main():
    tip = command("rev-parse", "HEAD")
    blobs = {path: command("rev-parse", tip+":"+path) for path in FILES}
    for mode, base in (("v0", "bandwidth-v0-original"), ("v1", "bandwidth-v1-compact")):
        with tempfile.TemporaryDirectory(prefix="ripple-git-index-") as folder:
            environment = dict(os.environ, GIT_INDEX_FILE=str(Path(folder)/"index"))
            parent = command("rev-parse", base)
            command("read-tree", parent, env=environment)
            for path, blob in blobs.items():
                command("update-index", "--add", "--cacheinfo", "100644,"+blob+","+path, env=environment)
            tree = command("write-tree", env=environment)
            commit = command("commit-tree", tree, "-p", parent, "-m", "fix: 应用共同连接表稳定性修复（"+mode+"）", env=environment)
            command("tag", "bandwidth-"+mode+"-stable", commit)
            command("branch", "experiment/bandwidth-"+mode+"-stable", commit)
            print(mode, commit)
    command("tag", "bandwidth-v2-stable", tip)
    for path in FILES:
        variants = {command("rev-parse", f"bandwidth-{mode}-stable:{path}") for mode in ("v0", "v1", "v2")}
        if len(variants) != 1:
            raise RuntimeError("共同修复不是逐字一致："+path)
    print("三个stable版本的共同修复与测试blob完全相同，原始标签保持不变")


if __name__ == "__main__":
    main()
