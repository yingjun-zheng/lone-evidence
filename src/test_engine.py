"""离线自测：不花额度，用假数据跑完整取证流程。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import burst, cluster_pages, domain_spread, investigate, similarity
from wsa import Page, SearchResult


def mk(title: str, domain: str, date: str = "2026-10-20", auth: int = 0, path: str = "a") -> Page:
    return Page(
        title=title,
        url=f"https://{domain}/{path}{abs(hash(title)) % 99999}.html",
        date=date,
        site=domain,
        domain=domain,
        score=0.7,
        authority=auth,
    )


MIRROR_DOMS = ["health-a.com", "ys-b.cn", "mrtt-c.com", "jtyy-d.cn", "39e-e.cn", "sina-f.com"]
VARIANTS = [
    "隔夜水致癌？专家这样说_健康频道",
    "隔夜水致癌？专家这样说-养生网",
    "隔夜水致癌？专家这样说 | 每日头条",
    "隔夜水致癌？专家这样说——家庭医生在线",
    "隔夜水致癌？专家这样说_39健康网",
    "隔夜水致癌？专家这样说-新浪财经",
]
OTHERS = [
    mk("关于隔夜水的三个常见误解", "独立科普-g.org", "2019-03-11"),
    mk("隔夜菜与亚硝酸盐的真实关系", "sci-j.org", "2024-11-02"),
    mk("家里这 5 样东西别隔夜吃", "life-k.com", "2025-07-19"),
]
AUTH = [
    mk("食品安全谣言榜单发布", "gov-i.gov.cn", "2026-09-30", auth=5),
    mk("饮用水安全国标解读", "std-h.org.cn", "2021-06-01", auth=4),
]


def build_full() -> list[Page]:
    pages = []
    for d in MIRROR_DOMS:
        for v in VARIANTS:
            pages.append(mk(v, d, "2026-10-20"))
    return pages + OTHERS


def fake_search(q, *, mode=None, site=None, cnt=None, industry=None, freshness=None, deeplinks=None, **kw):
    if mode == 1:
        return SearchResult(query=q, pages=AUTH, version="flagship")
    pages = build_full()
    if site and site.startswith("exclude:"):
        excl = set(site.split(":", 1)[1].split("|"))
        pages = [p for p in pages if p.domain not in excl]
    return SearchResult(query=q, pages=pages[: cnt or 10], version="flagship")


def main() -> None:
    pages = build_full()
    clusters = cluster_pages(pages)
    spread = domain_spread(pages)
    print(f"[原始] 总 {len(pages)} 条 / {len(clusters)} 簇 / {spread['unique_domains']} 域名 "
          f"/ 最大占比 {spread['max_share']} / burst {burst(pages)}")
    print(f"[最大簇] {clusters[0].size} 条，跨 {len(clusters[0].domains)} 个域名")

    rep = investigate("隔夜水致癌是真的吗", search_fn=fake_search)
    print("\n=== 取证报告 ===")
    for s in rep.steps:
        print(f"  {s['name']}: {s['detail']}")
    print(f"  判定: {rep.verdict}（{rep.verdict_desc}）")
    print(f"  独立同题信源: {rep.residual_same}  权威命中: {rep.auth_hits}  最高权威度: {rep.best_auth}")
    print(f"  置信度: {rep.confidence}  调用: {rep.calls}")

    print("\n=== 空结果场景 ===")
    rep2 = investigate("某不存在的事", search_fn=lambda q, **kw: SearchResult(query=q, pages=[]))
    print(f"  判定: {rep2.verdict} / 置信度 {rep2.confidence} / 错误 {rep2.errors}")

    print("\n=== 相似度抽查 ===")
    for a, b in [
        ("隔夜水致癌？专家这样说_健康频道", "隔夜水致癌？专家这样说-养生网"),
        ("隔夜水致癌？专家这样说", "隔夜菜与亚硝酸盐的真实关系"),
        ("隔夜水致癌？专家这样说", "饮用水安全国标解读"),
    ]:
        print(f"  {similarity(a, b):.3f}  {a[:12]} vs {b[:12]}")


if __name__ == "__main__":
    main()
