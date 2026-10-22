"""仅监听回环地址，将独立本地端口转发至指定节点原始网页。"""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import urlsplit

HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailer", "transfer-encoding", "upgrade", "content-length", "host"}


def local_request(handler):
    expected = {f"127.0.0.1:{handler.server.server_port}", f"localhost:{handler.server.server_port}"}
    hosts = handler.headers.get_all("Host", [])
    if len(hosts) != 1 or hosts[0].lower() not in expected:
        return False
    origin = handler.headers.get("Origin")
    if origin and origin not in {"http://" + host for host in expected}:
        return False
    return handler.headers.get("Sec-Fetch-Site") != "cross-site"


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def do_HEAD(self):
        self.forward()

    def forward(self):
        if not local_request(self):
            self.send_error(403, explain="只允许本地同源请求")
            return
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or not self.path.startswith("/"):
            self.send_error(400)
            return
        connection = None
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("不接受分块上传")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 4 * 1024 * 1024:
                raise ValueError("请求内容过大")
            self.connection.settimeout(15)
            body = self.rfile.read(length) if length else None
            if body is not None and len(body) != length:
                raise ValueError("请求不完整")
            target = self.server.target
            connection = http.client.HTTPConnection(target[0], target[1], timeout=15)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS | {"origin", "referer"}}
            connection.request(self.command, self.path, body, headers)
            response = connection.getresponse()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS:
                    if key.lower() == "location":
                        destination = urlsplit(value)
                        if destination.hostname == target[0]:
                            value = destination.path + ("?" + destination.query if destination.query else "")
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if self.command != "HEAD":
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except ValueError:
            self.send_error(400)
        except (OSError, http.client.HTTPException):
            self.close_connection = True
            try:
                self.send_error(502, explain="节点网页暂不可用")
            except OSError:
                pass
        finally:
            if connection:
                connection.close()


def start_proxy(ip, port):
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    server.daemon_threads = True
    server.target = (ip, int(port))
    thread = threading.Thread(target=server.serve_forever, name="节点网页代理", daemon=True)
    thread.start()
    return server, thread
