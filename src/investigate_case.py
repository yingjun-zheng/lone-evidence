"""深度调查取证：把每一步的中间数据完整落盘，供报告引用与复核。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import burst, cluster_pages, domain_spread, is_auth_domain, relevance, stance
from wsa import Quota, search

CLAIM = sys.argv[1] if len(sys.argv) > 1 else "隔夜水致癌"
OUT = Path(__file__).resolve().parent.parent / "docs" / "_investigation_data.json"


def brief(p) -> dict:
    return {
        "title": p.title, "url": p.url, "site": p.site, "domain": p.domain,
        "date": p.date, "score": round(p.score, 4),
        "passage": (p.passage or "")[:120],
    }


def main() -> None:
    data: dict = {"claim": CLAIM}

    # R1 原始检索
    r1 = search(CLAIM, mode=2, cnt=50)
    pages = r1.pages
    data["R1"] = {
        "params": {"Query": CLAIM, "Mode": 2, "Cnt": 50},
        "total": len(pages),
        "version": r1.version,
        "pages": [brief(p) for p in pages],
    }

    # 域名与时间结构
    spread = domain_spread(pages)
    data["domains"] = {
        "unique": spread["unique_domains"],
        "top": spread["top"],
        "max_share": spread["max_share"],
    }
    years = Counter((p.date or "")[:4] for p in pages if p.date)
    months = Counter((p.date or "")[:7] for p in pages if p.date)
    data["time"] = {
        "years": dict(sorted(years.items())),
        "months": dict(sorted(months.items())),
        "burst": burst(pages),
        "undated": sum(1 for p in pages if not p.date),
    }

    # R2 聚类
    clusters = cluster_pages(pages)
    data["R2"] = {
        "clusters": len(clusters),
        "size_dist": dict(sorted(Counter(c.size for c in clusters).items(), reverse=True)),
        "detail": [
            {
                "size": c.size, "sites": len(c.domains),
                "title": c.head.title, "domain": c.head.domain,
                "dates": c.dates[:6],
                "members": [{"t": m.title, "d": m.domain, "dt": (m.date or "")[:10]} for m in c.pages[:8]],
            }
            for c in clusters[:14]
        ],
    }

    # R3 剥离重搜
    top_doms = [d["domain"] for d in spread["top"][:5] if d["domain"]]
    cover = sum(d["share"] for d in spread["top"][:5])
    abl: dict = {"excluded": top_doms, "cover": round(cover, 3), "executed": cover >= 0.4}
    if cover >= 0.4:
        r2 = search(CLAIM, mode=2, cnt=50, site="exclude:" + "|".join(top_doms))
        rc = cluster_pages(r2.pages)
        abl.update({
            "hits": len(r2.pages), "clusters": len(rc),
            "domains": len({p.domain for p in r2.pages if p.domain}),
            "sample": [brief(p) for p in r2.pages[:20]],
        })
    data["R3"] = abl

    # R4 官方口径
    r3 = search(CLAIM, mode=2, cnt=20, industry="gov")
    gov = [p for p in r3.pages if relevance(p.title, CLAIM) >= 0.2]
    gov_doms = Counter(p.domain for p in r3.pages if p.domain)
    data["R4"] = {
        "params": {"Query": CLAIM, "Industry": "gov", "Cnt": 20},
        "recalled": len(r3.pages),
        "relevant": len(gov),
        "domains": dict(gov_doms.most_common(10)),
        "pages": [brief(p) for p in r3.pages],
    }

    # 原始结果里的官方域名
    off = sorted({p.domain for p in pages if is_auth_domain(p.domain)})
    data["official_in_r1"] = off

    # 立场
    data["stance"] = stance(pages)

    data["quota"] = {"used": Quota.load().used}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    print(f"已写入 {OUT}")
    print(f"R1 {len(pages)} 条 / 域名 {spread['unique_domains']} / 簇 {len(clusters)}")
    print(f"年份: {dict(sorted(years.items()))}")
    print(f"R3 执行={abl['executed']} 覆盖={abl['cover']}")
    print(f"R4 召回 {len(r3.pages)} 相关 {len(gov)}")
    print(f"立场: {data['stance']['label']} 否定{data['stance']['deny']} 疑问{data['stance']['quest']} 警示{data['stance']['warn']} 中性{data['stance']['neutral']}")


if __name__ == "__main__":
    main()
