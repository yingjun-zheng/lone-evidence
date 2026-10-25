"""连通性自检：验证签名 + 看清当前账号的真实返回结构。只花 1 次额度。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wsa import Quota, get_credentials, search

PROBE_QUERY = "沈阳今天天气"


def main() -> None:
    try:
        sid, skey = get_credentials()
    except RuntimeError as e:
        print("✗ " + str(e))
        sys.exit(1)

    print(f"SecretId: {sid[:8]}…{sid[-4:]}   SecretKey: {'已配置 ' + str(len(skey)) + ' 位' if skey else '缺失'}")

    r = search(PROBE_QUERY, mode=0, cnt=10, use_cache=False)
    if r.error:
        print(f"\n✗ 调用失败: {r.error}")
        if "AuthFailure" in r.error or "Unauthorized" in r.error:
            print("  → 签名或密钥不对。检查 SecretKey 是否属于同一个 SecretId。")
        if "ResourceNotFound" in r.error or "not activated" in r.error:
            print("  → 服务未开通。去 console.cloud.tencent.com/wsapi 开通元宝搜索。")
        if "LimitExceeded" in r.error or "频率" in r.error:
            print("  → 触发限频，等几秒重试。")
        sys.exit(2)

    print(f"\n✓ 调用成功   版本: {r.version}   返回 {len(r.pages)} 条   RequestId: {r.request_id}")
    q = Quota.load()
    print(f"额度台账: 已用 {q.used} / {q.limit}，剩余 {q.left}")

    print("\n--- 返回字段实况（第 1 条）---")
    if r.pages:
        p = r.pages[0]
        print(json.dumps(p.__dict__, ensure_ascii=False, indent=2)[:1200])
        print("\n--- 字段可用性 ---")
        print(f"  authority_level : {p.authority}  {'← 旗舰版才返回' if p.authority == 0 else ''}")
        print(f"  date            : {p.date or '（空）'}")
        print(f"  site / domain   : {p.site or '（空）'} / {p.domain}")
        print(f"  score           : {p.score}")

    print("\n--- 域名分布前 5 ---")
    from collections import Counter
    for d, c in Counter(x.domain for x in r.pages if x.domain).most_common(5):
        print(f"  {c:>2}  {d}")


if __name__ == "__main__":
    main()
