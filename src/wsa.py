"""元宝搜索 SearchPro 客户端 —— 零第三方依赖，TC3-HMAC-SHA256 签名。

凭证只从环境变量 / .env 读取，绝不硬编码。
    WSA_SECRET_ID   / TENCENTCLOUD_SECRET_ID
    WSA_SECRET_KEY  / TENCENTCLOUD_SECRET_KEY
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HOST = "wsa.tencentcloudapi.com"
SERVICE = "wsa"
VERSION = "2025-05-08"
ACTION = "SearchPro"
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
LEDGER = ROOT / "data" / "quota.json"


# ---------------------------------------------------------------- 凭证

def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def get_credentials() -> tuple[str, str]:
    _load_dotenv()
    sid = os.environ.get("WSA_SECRET_ID") or os.environ.get("TENCENTCLOUD_SECRET_ID", "")
    skey = os.environ.get("WSA_SECRET_KEY") or os.environ.get("TENCENTCLOUD_SECRET_KEY", "")
    if not sid or not skey:
        raise RuntimeError(
            "缺少凭证。请在 .env 里写入：\n"
            "  WSA_SECRET_ID=AKID...\n"
            "  WSA_SECRET_KEY=<腾讯云 API 密钥的 SecretKey>\n"
            "SecretKey 只在创建密钥时显示一次，找回请到 console.cloud.tencent.com/cam/capi 新建。"
        )
    return sid, skey


# ---------------------------------------------------------------- 签名

def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build_headers(secret_id: str, secret_key: str, payload: dict, ts: int | None = None) -> tuple[dict, str]:
    ts = ts or int(time.time())
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    ctype = "application/json; charset=utf-8"

    canonical_headers = f"content-type:{ctype}\nhost:{HOST}\nx-tc-action:{ACTION.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    canonical_request = "\n".join(
        ["POST", "/", "", canonical_headers, signed_headers, _sha256(body)]
    )
    scope = f"{date}/{SERVICE}/tc3_request"
    string_to_sign = "\n".join(
        ["TC3-HMAC-SHA256", str(ts), scope, _sha256(canonical_request)]
    )
    k_signing = _hmac(_hmac(_hmac(("TC3" + secret_key).encode("utf-8"), date), SERVICE), "tc3_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "Authorization": (
            f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
        "Content-Type": ctype,
        "Host": HOST,
        "X-TC-Action": ACTION,
        "X-TC-Version": VERSION,
        "X-TC-Timestamp": str(ts),
    }
    return headers, body


# ---------------------------------------------------------------- 额度台账

@dataclass
class Quota:
    used: int = 0
    limit: int = 6000

    @classmethod
    def load(cls) -> "Quota":
        if LEDGER.exists():
            try:
                d = json.loads(LEDGER.read_text(encoding="utf-8"))
                return cls(used=int(d.get("used", 0)), limit=int(d.get("limit", 6000)))
            except Exception:
                pass
        return cls()

    def spend(self, n: int = 1) -> None:
        self.used += n
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps({"used": self.used, "limit": self.limit}, indent=2), encoding="utf-8")

    @property
    def left(self) -> int:
        return max(0, self.limit - self.used)


# ---------------------------------------------------------------- 结果模型

@dataclass
class Page:
    title: str = ""
    url: str = ""
    date: str = ""
    passage: str = ""
    content: str = ""
    site: str = ""
    domain: str = ""
    score: float = 0.0
    authority: int = 0
    pics: list = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: str | dict) -> "Page":
        d = json.loads(raw) if isinstance(raw, str) else raw
        url = d.get("url", "") or ""
        dom = ""
        if "://" in url:
            dom = url.split("://", 1)[1].split("/", 1)[0].lower()
            if dom.startswith("www."):
                dom = dom[4:]
        return cls(
            title=d.get("title", "") or "",
            url=url,
            date=d.get("date", "") or "",
            passage=d.get("passage", "") or "",
            content=d.get("content", "") or "",
            site=d.get("site", "") or "",
            domain=dom,
            score=float(d.get("score", 0) or 0),
            authority=int(d.get("authority_level", 0) or 0),
            pics=d.get("pics", []) or [],
        )


@dataclass
class SearchResult:
    query: str
    pages: list[Page]
    version: str = ""
    request_id: str = ""
    from_cache: bool = False
    error: str = ""

    def to_json(self) -> dict:
        return {
            "query": self.query,
            "version": self.version,
            "request_id": self.request_id,
            "from_cache": self.from_cache,
            "error": self.error,
            "pages": [p.__dict__ for p in self.pages],
        }


# ---------------------------------------------------------------- 检索

def _cache_key(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def search(
    query: str,
    *,
    mode: int | None = None,
    site: str | None = None,
    cnt: int | None = None,
    industry: str | None = None,
    freshness: str | None = None,
    deeplinks: bool | None = None,
    use_cache: bool = True,
    timeout: int = 30,
) -> SearchResult:
    """一次 SearchPro 调用。相同参数命中本地缓存，不消耗额度。"""
    payload: dict = {"Query": query}
    if mode is not None:
        payload["Mode"] = mode
    if site is not None:
        payload["Site"] = site
    if cnt is not None:
        payload["Cnt"] = cnt
    if industry is not None:
        payload["Industry"] = industry
    if freshness is not None:
        payload["Freshness"] = freshness
    if deeplinks is not None:
        payload["Deeplinks"] = deeplinks

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ck = CACHE_DIR / f"{_cache_key(payload)}.json"
    if use_cache and ck.exists():
        try:
            d = json.loads(ck.read_text(encoding="utf-8"))
            return SearchResult(
                query=query,
                pages=[Page.from_raw(p) for p in d.get("pages", [])],
                version=d.get("version", ""),
                request_id=d.get("request_id", ""),
                from_cache=True,
            )
        except Exception:
            pass

    sid, skey = get_credentials()
    headers, body = build_headers(sid, skey, payload)

    last_err = ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"https://{HOST}", data=body.encode("utf-8"), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
            time.sleep(1.2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(1.2 * (attempt + 1))
    else:
        return SearchResult(query=query, pages=[], error=last_err)

    resp = data.get("Response", {})
    if "Error" in resp:
        err = resp["Error"]
        return SearchResult(query=query, pages=[], error=f"{err.get('Code')}: {err.get('Message')}")

    pages = [Page.from_raw(p) for p in resp.get("Pages", [])]
    out = SearchResult(
        query=query, pages=pages, version=resp.get("Version", ""), request_id=resp.get("RequestId", "")
    )

    Quota.load().spend(1)
    ck.write_text(json.dumps(out.to_json(), ensure_ascii=False), encoding="utf-8")
    return out
