#!/usr/bin/env python3
"""tbdiff.py —— 离线三方差分（修复 tb.py diff 的「B 侧读实时内存」bug）。

bug 说明：tb.py 的 diff() 用 process_vm_readv 读「当前进程内存」当作 B 侧，
但三次快照拍完后进程已处于 C 状态，所以 A→B 比较实际是 A vs C，判据全错。

本脚本两侧都从磁盘快照读，纯离线，不碰游戏、零风险。

用法：
  python3 tbdiff.py A B C          # 三方交叉验证
  python3 tbdiff.py A B            # 两方
"""
import json, os, sys
import numpy as np

DIR = "/home/deck/tb"
CHUNK = 512 * 1024
MAXCAND = 300000


def load(tag):
    meta = json.load(open("%s/%s.json" % (DIR, tag)))
    return meta, open("%s/%s.bin" % (DIR, tag), "rb")


def pair(tagA, tagB, verbose=True):
    ma, fa = load(tagA)
    mb, fb = load(tagB)
    dcs = mb["cs"] - ma["cs"]
    if dcs <= 0:
        print("  ❌ %s→%s Δcs=%d ≤0，跳过" % (tagA, tagB, dcs))
        return None
    tsec = dcs / 100.0
    cand = []
    nreg = 0
    for (lo_a, pos_a, n_a), (lo_b, pos_b, n_b) in zip(ma["regions"], mb["regions"]):
        if n_a <= 0 or n_b <= 0 or lo_a != lo_b or n_a != n_b:
            continue
        fa.seek(pos_a)
        fb.seek(pos_b)
        off = 0
        while off < n_a:
            sz = min(CHUNK, n_a - off)
            da = fa.read(sz)
            db = fb.read(sz)
            if len(da) != sz or len(db) != sz:
                break
            cnt = sz // 4
            va = np.frombuffer(da[:cnt * 4], "<i4")
            vb = np.frombuffer(db[:cnt * 4], "<i4")
            # ---- float32 视图 ----
            # ★ 关键：必须「值真的变过」（va != vb），否则常量会以
            #   |0 - target| <= tol 命中全部槽（曾一次灌出 31 万条假阳性）。
            fva = va.view("<f4").astype(np.float32, copy=False)
            fvb = vb.view("<f4").astype(np.float32, copy=False)
            fin = np.isfinite(fva) & np.isfinite(fvb)
            dfa = fva.astype(np.float64) - fvb.astype(np.float64)
            for target, name, tol, hi in ((tsec, "f4_s", 0.30, 400.0),
                                          (dcs / 10.0, "f4_t", 3.0, 4000.0)):
                m = (fin & (np.abs(dfa - target) <= tol) & (fva > 0)
                     & (fva < hi) & (fva != fvb))
                if m.any():
                    for k in np.nonzero(m)[0]:
                        cand.append((lo_a + off + int(k) * 4, float(fva[k]),
                                     float(fvb[k]), name))
            # ---- int32 视图 ----
            ia = va.astype(np.int64)
            ib = vb.astype(np.int64)
            di = ia - ib
            for target, name, tol, hi in ((tsec, "i4_s", 1.5, 400),
                                          (dcs / 10.0, "i4_t", 1.5, 4000)):
                m = (np.abs(di - target) <= tol) & (ia > 0) & (ia < hi) & (di != 0)
                if m.any():
                    for k in np.nonzero(m)[0]:
                        cand.append((lo_a + off + int(k) * 4, float(ia[k]),
                                     float(ib[k]), name))
            if len(cand) > MAXCAND:
                print("  ⚠️ 候选超限截断")
                break
            off += sz
        nreg += 1
        if len(cand) > MAXCAND:
            break
    fa.close()
    fb.close()
    # 去重
    seen = {}
    for a, v1, v2, ax in cand:
        seen[(a, ax)] = (v1, v2)
    if verbose:
        print("  %s→%s：Δcs=%d (%.2fs)  区 %d  候选(去重) %d"
              % (tagA, tagB, dcs, tsec, nreg, len(seen)))
    return dcs, seen


def main():
    tags = sys.argv[1:]
    if len(tags) < 2:
        print(__doc__)
        return
    res = []
    for i in range(len(tags) - 1):
        r = pair(tags[i], tags[i + 1])
        if r:
            res.append((tags[i], tags[i + 1], r[0], r[1]))
    if len(res) < 2:
        if res:
            print("\n单组候选（前 80，按值降序）：")
            for (a, ax), (v1, v2) in sorted(res[0][3].items(),
                                            key=lambda kv: -abs(kv[1][0]))[:80]:
                print("   0x%-11X [%-6s] %12.4f → %12.4f" % (a, ax, v1, v2))
        return
    s1, s2 = res[0][3], res[1][3]
    both = set(s1) & set(s2)
    print("\n=== 交叉验证：组1 Δ=%d 候选%d；组2 Δ=%d 候选%d；交集 %d ==="
          % (res[0][2], len(s1), res[1][2], len(s2), len(both)))
    rows = []
    for a, ax in both:
        A, B = s1[(a, ax)]
        B2, C = s2[(a, ax)]
        rows.append((a, ax, A, B, B2, C))
    # 一致性检查：B 应该几乎相等
    rows.sort(key=lambda r: -abs(r[2]))
    for a, ax, A, B, B2, C in rows[:200]:
        flag = "" if abs(B - B2) < 1.5 else "  ⚠️B不一致"
        print("   ★ 0x%-11X [%-6s] A=%.3f B=%.3f(B'=%.3f) C=%.3f%s"
              % (a, ax, A, B, B2, C, flag))
    json.dump([{"addr": "0x%X" % a, "axis": ax, "A": A, "B": B, "C": C}
               for a, ax, A, B, B2, C in rows],
              open(DIR + "/hit_offline.json", "w"), indent=1)
    print("  已存 %s/hit_offline.json" % DIR)


if __name__ == "__main__":
    main()
