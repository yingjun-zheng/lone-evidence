"""孤证引擎 —— 把一次「搜索」变成一次「对照实验」。

四步取证：
    ① 原始检索      Mode=2, Cnt=50        看清规模
    ② 同源聚类      标题指纹 + 域名        看清有几个声音
    ③ 剥离重搜      Site=exclude:top5域    去掉复读机后还剩谁
    ④ 权威对撞      Mode=1, Industry       有资格的人说了没有

所有参数都是 SearchPro 的自有字段，换一个搜索接口这套方法就不成立。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from wsa import Page, SearchResult, search

# ---------------------------------------------------------------- 文本指纹

_PUNCT = re.compile(r"[\s\u3000!-/:-@\[-`{-~·—…“”‘’《》〈〉【】、。，；：？！（）]+")
_SITE_TAIL = re.compile(r"[\s_\-|—]{1,3}[^_\-\|—]{2,12}(网|在线|首页|官网|频道|新闻|资讯)$")
_NOISE_PREFIX = re.compile(
    r"^(听说|据说|网上说|网上流传|朋友圈说|群里说|有人说|我看有人说|据传|传闻|求证[:：]?|真的吗[?？]?)\s*"
)


def clean_claim(text: str) -> str:
    t = (text or "").strip()
    t = _NOISE_PREFIX.sub("", t)
    return t.strip(" ?？。.!")


def fingerprint(title: str) -> str:
    """标题指纹：去站点尾巴、去标点、只留汉字数字字母。"""
    t = title or ""
    t = _SITE_TAIL.sub("", t)
    t = re.sub(r"[\-_|—]{1,3}[^\-_|—]{2,20}$", "", t)  # _新浪财经 / - 知乎
    t = _PUNCT.sub("", t)
    return t.lower()


def _shingles(s: str, n: int = 2) -> set[str]:
    if len(s) <= n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def similarity(a: str, b: str) -> float:
    fa, fb = fingerprint(a), fingerprint(b)
    if not fa or not fb:
        return 0.0
    if fa == fb:
        return 1.0
    sa, sb = _shingles(fa), _shingles(fb)
    # 包含关系（一个标题是另一个的前缀/子串）视为高度同源
    if fa in fb or fb in fa:
        return 0.92
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


# ---------------------------------------------------------------- 同源聚类

@dataclass
class Cluster:
    pages: list[Page] = field(default_factory=list)
    domains: set[str] = field(default_factory=set)

    @property
    def size(self) -> int:
        return len(self.pages)

    @property
    def head(self) -> Page:
        return max(self.pages, key=lambda p: (p.authority, p.score))

    @property
    def best_authority(self) -> int:
        return max((p.authority for p in self.pages), default=0)

    @property
    def dates(self) -> list[str]:
        return sorted({p.date[:10] for p in self.pages if p.date})

    def to_json(self) -> dict:
        h = self.head
        return {
            "size": self.size,
            "domains": sorted(self.domains),
            "count_sites": len(self.domains),
            "title": h.title,
            "url": h.url,
            "site": h.site,
            "date": h.date,
            "authority": self.best_authority,
            "dates": self.dates,
            "members": [
                {"title": p.title, "url": p.url, "site": p.site, "domain": p.domain, "date": p.date}
                for p in sorted(self.pages, key=lambda x: -x.authority)[:12]
            ],
        }


def cluster_pages(pages: list[Page], threshold: float = 0.55) -> list[Cluster]:
    """并查集：标题高度相似 或 同一域名多条同题，归为一簇。"""
    n = len(pages)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if similarity(pages[i].title, pages[j].title) >= threshold:
                union(i, j)

    groups: dict[int, list[Page]] = {}
    for i, p in enumerate(pages):
        groups.setdefault(find(i), []).append(p)

    out = []
    for group in groups.values():
        out.append(Cluster(pages=group, domains={p.domain for p in group if p.domain}))
    return sorted(out, key=lambda c: (-c.size, -c.best_authority))


# ---------------------------------------------------------------- 指标

def burst(pages: list[Page]) -> float:
    """时间聚集度：1 = 全部挤在同一天（疑似通稿），0 = 均匀铺开。"""
    days = Counter(p.date[:10] for p in pages if p.date)
    if not days:
        return 0.0
    if len(days) == 1:
        return 1.0
    total = sum(days.values())
    ent = -sum((c / total) * math.log2(c / total) for c in days.values())
    return round(1 - ent / math.log2(len(days)), 3)


def domain_spread(pages: list[Page]) -> dict:
    doms = Counter(p.domain for p in pages if p.domain)
    total = sum(doms.values()) or 1
    top = doms.most_common(8)
    return {
        "unique_domains": len(doms),
        "top": [{"domain": d, "count": c, "share": round(c / total, 3)} for d, c in top],
        "max_share": round(top[0][1] / total, 3) if top else 0.0,
    }


def is_auth_domain(domain: str) -> bool:
    """官方/学术域名。标准版拿不到 authority_level，只能用域名后缀做硬判断。"""
    d = (domain or "").lower()
    return d.endswith(".gov.cn") or d.endswith(".edu.cn") or d.endswith(".ac.cn")


# 立场启发式：只用于「提示」，不参与判定。
# 中文科普标题里，纯疑问句几乎都是求证/辟谣文；明确否定词则更硬。
NEG_WORDS = (
    "辟谣", "谣言", "不实", "假的", "误区", "真相", "别慌", "平反", "无依据",
    "误导", "求证", "解惑", "澄清", "并不是", "不是真的", "可放心", "放心喝",
    "无稽之谈", "答案来了", "科学解读", "打脸",
)
POS_WORDS = (
    "千万别", "不要再", "立即停用", "紧急提醒", "严重超标", "已致", "检出超标",
    "有毒", "中毒", "不能喝", "会致癌", "危害健康",
)
_Q = re.compile(r"[?？]|吗$|么$")


def stance(pages: list[Page]) -> dict:
    """粗判这批标题整体在「求证/否认」还是在「警示」。启发式，仅供参考。"""
    neg = quest = pos = neu = 0
    for p in pages:
        t = p.title or ""
        if any(w in t for w in NEG_WORDS):
            neg += 1
        elif any(w in t for w in POS_WORDS):
            pos += 1
        elif _Q.search(t):
            quest += 1
        else:
            neu += 1
    total = max(1, len(pages))
    deny = (neg + quest) / total
    warn = pos / total
    if deny >= 0.5:
        label, tone = "多数在求证或否认", "deny"
    elif warn >= 0.35:
        label, tone = "多数在警示", "warn"
    else:
        label, tone = "立场混杂", "mixed"
    return {
        "label": label,
        "tone": tone,
        "deny": neg, "quest": quest, "warn": pos, "neutral": neu,
        "deny_ratio": round(deny, 2),
        "note": "按标题句式粗判，非语义理解，请点开原文核对",
    }


def relevance(title: str, claim: str) -> float:
    """claim 的字符 bigram 有多少出现在标题里。用来剔除「政府网站里跑题的文章」。"""
    c = fingerprint(claim)
    t = fingerprint(title)
    if not c or not t:
        return 0.0
    grams = _shingles(c)
    if not grams:
        return 0.0
    return sum(1 for g in grams if g in t) / len(grams)


def confidence(indep: int, auth_strength: float, spread: float, burst_score: float) -> int:
    """0-100。独立信源是主干，权威是背书，传播结构做修正。"""
    s_indep = min(indep, 4) / 4 * 45
    s_auth = max(0.0, min(1.0, auth_strength)) * 27
    s_disp = spread * 18
    s_time = (1 - burst_score) * 10
    return int(round(max(0, min(100, s_indep + s_auth + s_disp + s_time))))


VERDICTS = {
    "查无此事": ("查无此事", "没有任何信源在说这件事，包括官方口径", "none"),
    "孤证": ("孤证", "只有一个独立声音，去掉复读机后无人跟进", "weak"),
    "多源一致否认": ("多源一致否认", "多个独立来源与官方口径都在否认这个说法", "deny"),
    "多源否认": ("多源否认", "多个独立来源在否认，但没有官方口径", "deny"),
    "多源一致警示": ("多源一致警示", "多个独立来源与官方口径都在提示该风险", "warn"),
    "多源警示": ("多源警示", "多个独立来源在提示风险，缺少官方口径", "warn"),
    "多源讨论": ("多源讨论", "多个独立来源在讨论，立场不一致，需自行判断", "mixed"),
}


def decide(indep: int, auth_hits: int, tone: str) -> str:
    if indep == 0 and auth_hits == 0:
        return "查无此事"
    if indep <= 1 and auth_hits == 0:
        return "孤证"
    if tone == "deny":
        return "多源一致否认" if auth_hits > 0 else "多源否认"
    if tone == "warn":
        return "多源一致警示" if auth_hits > 0 else "多源警示"
    return "多源讨论"


# ---------------------------------------------------------------- 主流程

@dataclass
class Report:
    claim: str
    query: str
    anchor: str = ""
    total: int = 0
    clusters_before: int = 0
    excluded_domains: list[str] = field(default_factory=list)
    exclude_cover: float = 0.0
    residual_hits: int = 0
    residual_clusters: int = 0
    residual_same: int = 0
    ablation_done: bool = False
    auth_hits: int = 0
    best_auth: int = 0
    auth_strength: float = 0.0
    off_domains: list[str] = field(default_factory=list)
    burst: float = 0.0
    spread: dict = field(default_factory=dict)
    confidence: int = 0
    verdict: str = ""
    verdict_desc: str = ""
    tone: str = ""
    clusters: list[dict] = field(default_factory=list)
    stance: dict = field(default_factory=dict)
    titles: list[str] = field(default_factory=list)
    residual_pages: list[dict] = field(default_factory=list)
    auth_pages: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    calls: int = 0
    errors: list[str] = field(default_factory=list)
    cache_hits: int = 0

    def to_json(self) -> dict:
        d = dict(self.__dict__)
        return d


def _page_brief(p: Page) -> dict:
    return {
        "title": p.title,
        "url": p.url,
        "site": p.site,
        "domain": p.domain,
        "date": p.date,
        "authority": p.authority,
        "score": round(p.score, 3),
        "passage": (p.passage or p.content or "")[:180],
    }


def investigate(claim: str, *, cnt: int = 50, top_exclude: int = 5, deep: bool = True, search_fn=None) -> Report:
    _search = search_fn or search
    q = clean_claim(claim)
    rep = Report(claim=claim, query=q)

    def note(name: str, detail: str, **kw) -> None:
        step = {"name": name, "detail": detail}
        step.update(kw)
        rep.steps.append(step)

    # ① 原始检索
    r1: SearchResult = _search(q, mode=2, cnt=cnt)
    rep.calls += 1
    if r1.from_cache:
        rep.cache_hits += 1
    if r1.error:
        rep.errors.append(f"原始检索失败: {r1.error}")
        return rep
    rep.total = len(r1.pages)
    note("原始检索", f"Query={q} Mode=2 Cnt={cnt}", hits=rep.total)

    # ② 同源聚类
    clusters = cluster_pages(r1.pages)
    rep.clusters_before = len(clusters)
    rep.spread = domain_spread(r1.pages)
    rep.burst = burst(r1.pages)
    rep.clusters = [c.to_json() for c in clusters[:12]]
    rep.stance = stance(r1.pages)
    # 全部标题原样带给前端，供云服务模型复核立场
    rep.titles = [p.title for p in r1.pages if p.title]
    note("同源聚类", f"{rep.total} 条 → {len(clusters)} 个说法 / {rep.spread['unique_domains']} 个域名",
         clusters=len(clusters), domains=rep.spread["unique_domains"])

    if rep.total == 0:
        rep.verdict, rep.verdict_desc, rep.tone = VERDICTS["查无此事"]
        return rep

    # ③ 剥离重搜：把最吵的那几个域名全部排除，看还剩谁说
    # 锚点不能用「最大簇」——最大簇往往是某个跑题的通稿，取与 claim 最相关的那个
    anchor = max(clusters, key=lambda c: relevance(c.head.title, q)).head.title if clusters else q
    rep.anchor = anchor
    if deep and rep.spread["top"]:
        excl = [d["domain"] for d in rep.spread["top"][:top_exclude] if d["domain"]]
        rep.excluded_domains = excl
        # 只排除真正占大头的那几个；若传播本身已分散，剥离没有意义
        cover = sum(d["share"] for d in rep.spread["top"][:top_exclude])
        rep.exclude_cover = round(cover, 3)
        if excl and cover >= 0.4:
            r2 = _search(q, mode=2, cnt=cnt, site="exclude:" + "|".join(excl))
            rep.calls += 1
            if r2.from_cache:
                rep.cache_hits += 1
            if r2.error:
                rep.errors.append(f"剥离重搜失败: {r2.error}")
            else:
                # 剥离后返回的就是「去掉复读机之后还在说这件事的人」，不需要去重
                fresh = r2.pages
                rep.residual_hits = len(fresh)
                rc = cluster_pages(fresh)
                # 搜索引擎已按相关性召回，剥离后的簇默认都在说这件事。
                # 中文标题改写幅度太大，用标题相似度二次筛选反而会漏杀，这里不做过滤。
                same = rc
                rep.residual_clusters = len(rc)
                rep.residual_same = len(same)
                rep.ablation_done = True
                rep.residual_pages = [_page_brief(p) for p in fresh[:20]]
                note("剥离重搜",
                     f"排除 {', '.join(excl)}（覆盖 {cover:.0%}）→ 剩 {len(fresh)} 条 / "
                     f"{len(rc)} 簇，其中同题 {len(same)} 簇",
                     excluded=excl, hits=len(fresh), clusters=len(rc), same=len(same))
        else:
            note("剥离重搜", f"最大 5 域仅覆盖 {cover:.0%}，传播本身已分散，跳过剥离", skipped=True)

    # ④ 官方口径：标准版没有 authority_level，改用 Industry=gov 做定向召回
    if deep:
        r3 = _search(q, mode=2, cnt=20, industry="gov")
        rep.calls += 1
        if r3.from_cache:
            rep.cache_hits += 1
        if r3.error:
            rep.errors.append(f"官方口径检索失败: {r3.error}")
        else:
            # 政府源里跑题的文章不算证据，按 claim 覆盖率过滤
            gov_pages = [p for p in r3.pages if relevance(p.title, q) >= 0.2 or relevance(p.title, anchor) >= 0.3]
            rep.auth_hits = len(gov_pages)
            rep.best_auth = max((p.authority for p in gov_pages), default=0)
            rep.auth_pages = [_page_brief(p) for p in gov_pages[:10]]
            note("官方口径", f"Industry=gov 召回 {len(r3.pages)} 条，同题 {len(gov_pages)} 条",
                 hits=len(gov_pages), recalled=len(r3.pages))

    # 原始结果里本来就落着的 gov / edu 域名，也计入官方背书
    off_domains = sorted({p.domain for p in r1.pages if is_auth_domain(p.domain)})
    rep.off_domains = off_domains
    if off_domains:
        note("官方域名", f"原始结果中另有 {len(off_domains)} 个政府/学术域名", domains=off_domains)

    # 判定：结构（几个人在说）× 立场（他们在说什么）
    # 剥离成功执行 → 用剥离后的同题簇数；剥离被跳过 → 退回原始簇数
    indep = rep.residual_same if rep.ablation_done else rep.clusters_before
    tone = (rep.stance or {}).get("tone", "mixed")
    key = decide(indep, rep.auth_hits, tone)
    rep.verdict, rep.verdict_desc, rep.tone = VERDICTS[key]
    # 旗舰版有 0-5 分：直接归一化；标准版只有「官方口径在不在」：按条数封顶 0.7
    if rep.best_auth > 0:
        strength = min(rep.best_auth, 5) / 5
    else:
        strength = min(rep.auth_hits, 3) / 3 * 0.7 + (0.15 if rep.off_domains else 0)
    rep.auth_strength = round(min(1.0, strength), 3)
    rep.confidence = confidence(indep, rep.auth_strength, 1 - rep.spread["max_share"], rep.burst)
    return rep
