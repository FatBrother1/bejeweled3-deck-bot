#!/usr/bin/env python3
"""analyze.py —— 离线深挖三份快照，找倒计时母本（不碰游戏）。

已知：0x109CBEC 是整秒镜像（三方差分唯一命中），但钉不住（每帧被块拷贝覆写）。
目标：找出「按秒递减、且不只出现在渲染暂存槽」的槽 —— 即真正的母本。

三路并进：
  ① 多刻度全扫：1/10/100/1000 四种刻度 × int/float，放宽值域，看谁同时满足两段 Δ。
  ② 0x109CBEC 邻域结构剖析：把它前后 ±0x400 的所有"在变化"的槽列出来，
     看这个 UI 属性结构体的完整形状（谁和它一起变、变化幅度是否同源）。
  ③ 反向索引：所有「A→B 恰好降 ΔAB 且 B→C 恰好降 ΔBC」的槽，
     统计它们聚集在哪些地址区间 —— 母本通常与大量副本分处不同区。
"""
import json, sys
import numpy as np

DIR = "/home/deck/tb"
CHUNK = 512 * 1024
FOCUS = 0x109CBEC


def load(tag):
    meta = json.load(open("%s/%s.json" % (DIR, tag)))
    return meta, open("%s/%s.bin" % (DIR, tag), "rb")


def read_at(f, regions, addr, n):
    """从快照里读 addr 处 n 字节。"""
    for lo, pos, ln in regions:
        if ln > 0 and lo <= addr and addr + n <= lo + ln:
            f.seek(pos + (addr - lo))
            return f.read(n)
    return None


def main():
    ma, fa = load("A")
    mb, fb = load("B")
    mc, fc = load("C")
    dAB = mb["cs"] - ma["cs"]
    dBC = mc["cs"] - mb["cs"]
    print("ΔAB=%d cs (%.2fs)   ΔBC=%d cs (%.2fs)" % (dAB, dAB / 100.0, dBC, dBC / 100.0))

    # ---------- ① 多刻度全扫 ----------
    print("\n" + "=" * 70)
    print("① 多刻度全扫（要求 A≠B≠C 且两段落差同时匹配）")
    print("=" * 70)
    scales = [("秒", 1.0), ("十分秒", 10.0), ("厘秒", 100.0), ("毫秒", 1000.0)]
    tally = {}
    for name, sc in scales:
        tAB, tBC = dAB * sc / 100.0, dBC * sc / 100.0
        tol = max(1.0, sc * 0.03)
        hits_i, hits_f = [], []
        for (lo_a, pos_a, n_a), (lo_b, pos_b, n_b), (lo_c, pos_c, n_c) in \
                zip(ma["regions"], mb["regions"], mc["regions"]):
            if min(n_a, n_b, n_c) <= 0 or lo_a != lo_b or lo_a != lo_c or n_a != n_b or n_a != n_c:
                continue
            fa.seek(pos_a); fb.seek(pos_b); fc.seek(pos_c)
            off = 0
            while off < n_a:
                sz = min(CHUNK, n_a - off)
                da, db, dc = fa.read(sz), fb.read(sz), fc.read(sz)
                if len(da) != sz or len(db) != sz or len(dc) != sz:
                    break
                cnt = sz // 4
                ia = np.frombuffer(da[:cnt * 4], "<i4").astype(np.int64)
                ib = np.frombuffer(db[:cnt * 4], "<i4").astype(np.int64)
                ic = np.frombuffer(dc[:cnt * 4], "<i4").astype(np.int64)
                # int 视图
                m = ((np.abs((ia - ib) - tAB) <= tol) & (np.abs((ib - ic) - tBC) <= tol)
                     & (ia != ib) & (ib != ic) & (ia > 0) & (ia < 100 * max(1, sc)))
                if m.any():
                    for k in np.nonzero(m)[0]:
                        hits_i.append((lo_a + off + int(k) * 4, int(ia[k]), int(ib[k]), int(ic[k])))
                # float 视图
                fva = ia.astype(np.float64)
                fvb = ib.astype(np.float64)
                fvc = ic.astype(np.float64)
                m = ((np.abs((fva - fvb) - tAB) <= tol) & (np.abs((fvb - fvc) - tBC) <= tol)
                     & np.isfinite(fva) & (fva > 0) & (fva < 1e6))
                if m.any():
                    for k in np.nonzero(m)[0]:
                        hits_f.append((lo_a + off + int(k) * 4, fva[k], fvb[k], fvc[k]))
                off += sz
        tally[name] = (hits_i, hits_f)
        print("\n--- 刻度「%s」 tol=%.1f ---" % (name, tol))
        print("   int32  命中 %d" % len(hits_i))
        for a, v1, v2, v3 in sorted(hits_i, key=lambda t: -abs(t[1]))[:25]:
            print("      0x%-11X %14d → %14d → %14d" % (a, v1, v2, v3))
        print("   float32 命中 %d" % len(hits_f))
        for a, v1, v2, v3 in sorted(hits_f, key=lambda t: -abs(t[1]))[:25]:
            print("      0x%-11X %14.4f → %14.4f → %14.4f" % (a, v1, v2, v3))

    # ---------- ② 聚焦邻域 ----------
    print("\n" + "=" * 70)
    print("② 0x%X 邻域 ±0x600：所有在变化的 4 字节槽" % FOCUS)
    print("=" * 70)
    base = (FOCUS - 0x600) & ~3
    n = 0xC00
    da = read_at(fa, ma["regions"], base, n)
    db = read_at(fb, mb["regions"], base, n)
    dc = read_at(fc, mc["regions"], base, n)
    if da is None or db is None or dc is None:
        print("   邻域读取失败")
    else:
        ia = np.frombuffer(da, "<i4")
        ib = np.frombuffer(db, "<i4")
        ic = np.frombuffer(dc, "<i4")
        fa4 = np.frombuffer(da, "<f4")
        fb4 = np.frombuffer(db, "<f4")
        fc4 = np.frombuffer(dc, "<f4")
        for k in range(len(ia)):
            a = base + k * 4
            ch_i = not (ia[k] == ib[k] == ic[k])
            ch_f = not (fa4[k] == fb4[k] == fc4[k])
            if not (ch_i or ch_f):
                continue
            mark = "  ←★焦点" if a == FOCUS else ""
            print("  0x%-9X i4: %12d %12d %12d | f4: %11.4f %11.4f %11.4f%s"
                  % (a, ia[k], ib[k], ic[k], fa4[k], fb4[k], fc4[k], mark))

    # ---------- ③ 分布统计 ----------
    print("\n" + "=" * 70)
    print("③ 各刻度候选的地址区间分布（找母本聚集区）")
    print("=" * 70)
    for name, (hi_, hf_) in tally.items():
        buckets = {}
        for a, *_ in hi_:
            buckets[a >> 20] = buckets.get(a >> 20, 0) + 1
        if buckets:
            top = sorted(buckets.items(), key=lambda kv: -kv[1])[:8]
            print("   [%s] int 候选 %d，主要区间：%s"
                  % (name, len(hi_), "  ".join("0x%Xxxxx:%d" % (k, v) for k, v in top)))


if __name__ == "__main__":
    main()
