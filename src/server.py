"""孤证 · 本地服务。零依赖，python server.py 即可。

    GET /               前端
    GET /api/check?q=   取证
    GET /api/quota      额度
    GET /api/demo&id=   演示数据（断网兜底）
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from engine import investigate  # noqa: E402
from wsa import Quota, SearchResult, get_credentials  # noqa: E402
import mock  # noqa: E402

WEB = ROOT / "web"
PORT = int(os.environ.get("PORT", "7788"))
HOST = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
MOCK_ONLY = False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            f = WEB / "index.html"
            if not f.exists():
                return self._send(404, b"index.html missing", "text/plain")
            return self._send(200, f.read_bytes(), "text/html; charset=utf-8")

        if u.path == "/api/quota":
            q = Quota.load()
            return self._json({"used": q.used, "limit": q.limit, "left": q.left})

        if u.path == "/api/demo":
            did = (qs.get("id") or ["mirror"])[0]
            data = mock.scenario(did)
            return self._json(data)

        if u.path == "/api/check":
            claim = (qs.get("q") or [""])[0].strip()
            if not claim:
                return self._json({"error": "缺少 q 参数"}, 400)
            use_mock = (qs.get("mock") or ["0"])[0] == "1" or MOCK_ONLY
            try:
                if use_mock:
                    import mock as m
                    rep = investigate(claim, search_fn=m.fake_search_for(claim))
                    d = rep.to_json()
                    d["_mock"] = True
                    return self._json(d)
                rep = investigate(claim)
                return self._json(rep.to_json())
            except RuntimeError as e:
                return self._json({"error": str(e)}, 500)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        return self._send(404, b"not found", "text/plain")

    def log_message(self, fmt: str, *args) -> None:  # 静音
        pass


def main() -> None:
    global MOCK_ONLY
    ok = True
    try:
        sid, _ = get_credentials()
        print(f"凭证已配置（SecretId {sid[:8]}…）")
    except RuntimeError:
        ok = False
        MOCK_ONLY = True
        print("⚠ 未配置 SecretKey —— 已自动切到离线演示数据")

    print(f"\n  孤证 · 开庭中  →  http://{HOST}:{PORT}\n", flush=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n散庭。")


if __name__ == "__main__":
    main()
