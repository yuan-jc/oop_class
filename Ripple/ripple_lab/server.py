"""实验控制台的本机 HTTP 服务与命令行入口。"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import tempfile
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import zipfile

from .config import default_config
from .manager import ConflictError, Manager, TERMINAL
from .proxy import local_request

WEB = Path(__file__).resolve().parent / "web"
STATIC = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
          **{"/" + name: (name, "text/javascript" if name.endswith(".js") else "text/css")
             for name in ("app.js", "model.js", "editor.js", "monitor.js", "styles.css")}}


def environment():
    tools = {name: shutil.which(name) is not None for name in ("java", "javac", "mvn", "ip", "tc", "tcpdump", "ethtool")}
    linux = platform.system() == "Linux"
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    ready = linux and root and all(tools.values())
    return {"service": "ripple-lab", "ready": ready, "platform": platform.system(), "root": root, "tools": tools,
            "message": "环境就绪，可以启动真实网络实验。" if ready else "环境尚未就绪：需要 Linux/WSL、root 权限及完整 Java/Maven/网络工具。"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise ValueError("请求必须指定唯一的内容长度")
        size = int(self.headers["Content-Length"])
        if not 0 < size <= 1024 * 1024:
            raise ValueError("JSON 请求需在1字节至1MB之间")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请求必须使用 application/json")
        self.connection.settimeout(15)
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("请求内容不完整")
        return json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("不接受非有限数字")))

    def dispatch(self, post):
        if not local_request(self):
            self.json_response({"error": "仅接受本地同源请求"}, 403)
            return
        try:
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc:
                raise KeyError("路径不存在")
            path = unquote(parsed.path)
            query = parse_qs(parsed.query, keep_blank_values=True)
            if any(len(values) != 1 for values in query.values()):
                raise ValueError("查询参数不能重复")
            q = {key: values[0] for key, values in query.items()}
            manager = self.server.manager
            body = self.read_body() if post else None
            if not post and path in STATIC:
                filename, mime = STATIC[path]
                data = (WEB / filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/defaults" and not post:
                result = default_config()
            elif path == "/api/environment" and not post:
                result = environment()
            elif path == "/api/configs":
                result = manager.save_config(body) if post else {"configs": manager.configs()}
            elif path == "/api/runs":
                result = manager.create(body) if post else {"runs": manager.runs()}
            else:
                parts = path.strip("/").split("/")
                if len(parts) not in (3, 4) or parts[:2] != ["api", "runs"]:
                    raise KeyError("路径不存在")
                run_id = parts[2]
                action = parts[3] if len(parts) == 4 else ""
                if post and action in {"stop", "stop-sending"}:
                    result = manager.action(run_id, action.replace("-", "_"))
                elif not post and action == "":
                    result = manager.get(run_id)
                elif not post and action == "events":
                    after, limit = int(q.get("after", "0")), int(q.get("limit", "100"))
                    before = int(q["before"]) if q.get("before") else None
                    if after < 0 or not 1 <= limit <= 500 or (before is not None and before < 0):
                        raise ValueError("事件分页参数超出范围")
                    if q.get("tail", "false") not in {"true", "false", "1", "0"}:
                        raise ValueError("tail 参数应为布尔值")
                    result = manager.events(run_id, node=q.get("node", ""), event=q.get("event", ""),
                                            q=q.get("q", ""), after=after, limit=limit,
                                            before=before, tail=q.get("tail") in {"true", "1"})
                elif not post and action == "logs":
                    result = manager.logs(run_id, q.get("node", ""))
                elif not post and action == "download":
                    self.download(run_id)
                    return
                else:
                    raise KeyError("路径不存在")
            self.json_response(result, 201 if post and path in {"/api/runs", "/api/configs"} else 200)
        except ConflictError as error:
            self.json_response({"error": str(error)}, 409)
        except KeyError as error:
            self.json_response({"error": str(error)}, 404)
        except (ValueError, TypeError, UnicodeError) as error:
            self.json_response({"error": str(error)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            self.json_response({"error": "控制服务错误：" + str(error)}, 500)

    def download(self, run_id):
        manager = self.server.manager
        state = manager.get(run_id)
        if state.get("status") not in TERMINAL:
            raise ConflictError("请等待实验归档结束后下载")
        folder = manager.directory(run_id)
        with tempfile.TemporaryFile() as output:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for path in sorted(folder.rglob("*")):
                    if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(folder.resolve()):
                        archive.write(path, path.relative_to(folder).as_posix())
                if not (folder / "state.json").exists():
                    archive.writestr("state.json", json.dumps(state, ensure_ascii=False))
            length = output.tell()
            output.seek(0)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Disposition", f'attachment; filename="{run_id}.zip"')
            self.end_headers()
            shutil.copyfileobj(output, self.wfile, length=65536)


def create_server(manager, port=8877):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.manager = manager
    manager.base_url = f"http://127.0.0.1:{server.server_port}"
    return server


def main():
    parser = argparse.ArgumentParser(description="Ripple 本地实验控制台")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent / "data")
    args = parser.parse_args()
    manager = Manager(args.root)
    server = create_server(manager, args.port)
    print("Ripple 实验台已启动：" + manager.base_url, flush=True)
    stopping = threading.Event()
    def request_shutdown(signum, frame):
        if not stopping.is_set():
            stopping.set()
            # shutdown 必须从 serve_forever 之外的线程调用。
            threading.Thread(target=server.shutdown, name="控制服务停止", daemon=True).start()
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        manager.close()
        server.server_close()


if __name__ == "__main__":
    main()
