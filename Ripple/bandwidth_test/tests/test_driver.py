"""通过实际客户端依赖编译并执行 Java 载荷检查。"""
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


class DriverTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "需要 JDK")
    def test_payload_generation_and_full_content_check(self):
        here = Path(__file__).resolve().parents[1]
        archive = here.parent/"Ripple/ripple-client/target/ripple-client-publish.tar.gz"
        if not archive.is_file():
            self.skipTest("需要已构建客户端发行包")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with tarfile.open(archive) as source:
                source.extractall(root, filter="data")
            classpath = f"{root}:{root}/ripple-client.jar:{root}/lib/*"
            subprocess.run(["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-cp", classpath,
                            "-d", str(root), str(here/"java/Driver.java"),
                            str(here/"tests/DriverPayloadCheck.java")], check=True)
            result = subprocess.run(["java", "-cp", classpath, "DriverPayloadCheck", str(root)],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("全文校验通过", result.stdout)
