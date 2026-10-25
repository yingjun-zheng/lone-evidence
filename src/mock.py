"""离线演示数据：网络或密钥不可用时，仍能完整演示取证流程。"""
from __future__ import annotations

from engine import investigate
from wsa import Page, SearchResult

MIRROR = ["health-a.com", "ys-b.cn", "mrtt-c.com", "jtyy-d.cn", "39e-e.cn", "sina-f.com"]
TEMPLATES = [
    "隔夜水致癌？专家这样说_健康频道",
    "隔夜水致癌？专家这样说-养生网",
    "隔夜水致癌？专家这样说 | 每日头条",
    "隔夜水致癌？专家这样说——家庭医生在线",
    "隔夜水致癌？专家这样说_39健康网",
    "隔夜水致癌？专家这样说-新浪财经",
]
SIDE = [
    ("关于隔夜水的三个常见误解", "kepu-g.org", "2019-03-11", 0),
    ("隔夜菜与亚硝酸盐的真实关系", "sci-j.org", "2024-11-02", 2),
    ("家里这几样东西别隔夜吃", "life-k.com", "2025-07-19", 0),
]
AUTH = [
    ("食品安全谣言榜单发布", "gov-i.gov.cn", "2026-09-30", 5),
    ("生活饮用水卫生标准解读", "std-h.org.cn", "2021-06-01", 4),
    ("亚硝酸盐膳食暴露风险评估", "acad-j.org.cn", "2023-08-14", 5),
]


def _mk(title: str, domain: str, date: str, auth: int = 0) -> Page:
    return Page(
        title=title,
        url=f"https://{domain}/p/{abs(hash(title)) % 99999}.html",
        date=date,
        site=domain,
        domain=domain,
        score=0.72,
        authority=auth,
    )


def _mirror_pages() -> list[Page]:
    out = []
    for d in MIRROR:
        for t in TEMPLATES:
            out.append(_mk(t, d, "2026-10-20"))
    return out


def fake_search_for(claim: str, kind: str = "mirror"):
    mirror = _mirror_pages()
    side = [_mk(t, d, dt, a) for t, d, dt, a in SIDE]
    auth = [_mk(t, d, dt, a) for t, d, dt, a in AUTH]

    def _fake(q, *, mode=None, site=None, cnt=None, industry=None, freshness=None, deeplinks=None, **kw):
        if mode == 1:
            return SearchResult(query=q, pages=auth if kind != "none" else [], version="flagship")
        if kind == "none":
            return SearchResult(query=q, pages=[], version="standard")
        pages = mirror + side if kind == "mirror" else side + auth
        if site and site.startswith("exclude:"):
            excl = set(site.split(":", 1)[1].split("|"))
            pages = [p for p in pages if p.domain not in excl]
        return SearchResult(query=q, pages=pages[: cnt or 10], version="flagship")

    return _fake


SCENARIOS = {
    "mirror": ("隔夜水致癌是真的吗", "mirror"),
    "solid": ("每日咖啡因摄入的安全上限是多少", "solid"),
    "none": ("2026年家用核磁共振仪已经上市了吗", "none"),
}


def scenario(name: str) -> dict:
    claim, kind = SCENARIOS.get(name, SCENARIOS["mirror"])
    return investigate(claim, search_fn=fake_search_for(claim, kind)).to_json()
