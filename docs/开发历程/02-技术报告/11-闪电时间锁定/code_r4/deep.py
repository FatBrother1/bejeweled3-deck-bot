#!/usr/bin/env python3
"""deep.py —— 离线深挖：找倒计时母本（三路并进，不碰游戏）。

已知：整秒镜像 0x109CBEC（A=15 B=8 C=1），四刻度全扫下全内存唯一。
目标：找出它背后的母本 —— 母本应满足
  · Board 对象内（Board=0xF404DC8，三份快照地址一致，故可精确对齐）
  · 或：以更细刻度（float 小数）递减，比例 (A-B)/(B-C) ≈ ΔAB/ΔBC = 675/776 = 0.870

三路：
  ① Board 相对扫描：Board±0x8000 内找 15/8/1 的所有表示（i4/f4），按偏移求交
  ② 比例扫描（尺度无关）：全内存找「三段严格递减且比例≈0.870」的槽
  ③ 邻域扩展：0x109CBEC±0x4000 内三段递减的槽
"""
import json
import numpy as np

DIR = "/home/deck/tb"
CHUNK = 512 * 1024
RATIO = 675.0 / 776.0          # 0.8698


def load(tag):
    meta = json.load(open("%s/%s.json" % (DIR, tag)))
    return meta, open("%s/%s.bin" % (DIR, tag), "rb")


def read_slot(f, regions, addr, n):
    for lo, pos, ln in regions:
        if ln > 0 and lo <= addr and addr + n <= lo + ln:
            f.seek(pos + (addr - lo))
            return f.read(n)
    return None


def region_iter(ma, mb, mc):
    for (la, pa, na), (lb, pb, nb), (lc, pc, nc) in zip(
            ma["regions"], mb["regions"], mc["regions"]):
        if min(na, nb, nc) <= 0 or la != lb or la != lc or na != nb or na != nc:
            continue
        yield la, pa, pb, pc, na


def main():
    ma, fa = load("A"); mb, fb = load("B"); mc, fc = load("C")
    board = ma["board"]
    print("ΔAB=%d cs  ΔBC=%d cs   Board=0x%X" % (mb["cs"] - ma["cs"], mc["cs"] - mb["cs"], board or 0))

    # ---------- ① Board 相对扫描 ----------
    print("\n" + "=" * 72)
    print("① Board±0x8000 内，A=15 / B=8 / C=1 的所有表示（按相对偏移求交）")
    print("=" * 72)
    if board:
        lo_b = (board - 0x8000) & ~3
        n_b = 0x10000
        da = read_slot(fa, ma["regions"], lo_b, n_b)
        db = read_slot(fb, mb["regions"], lo_b, n_b)
        dc = read_slot(fc, mc["regions"], lo_b, n_b)
        if da and db and dc:
            ia = np.frombuffer(da, "<i4"); ib = np.frombuffer(db, "<i4"); ic = np.frombuffer(dc, "<i4")
            fva = np.frombuffer(da, "<f4"); fvb = np.frombuffer(db, "<f4"); fvc = np.frombuffer(dc, "<f4")
            print("-- int32 精确匹配 15/8/1 --")
            for k in np.nonzero((ia == 15) & (ib == 8) & (ic == 1))[0]:
                print("   ★ Board+0x%X  (0x%X)  = 15 → 8 → 1"
                      % (lo_b + k * 4 - board, lo_b + k * 4))
            print("-- float32 精确匹配 15.0/8.0/1.0 --")
            for k in np.nonzero((fva == 15.0) & (fvb == 8.0) & (fvc == 1.0))[0]:
                print("   ★ Board+0x%X  (0x%X)  = 15.0 → 8.0 → 1.0"
                      % (lo_b + k * 4 - board, lo_b + k * 4))
            # 放宽：只需要单调递减且落在合理区间
            print("-- int32 递减且 A∈[10,25] B∈[5,12] C∈[0,4] --")
            m = (ia >= 10) & (ia <= 25) & (ib >= 5) & (ib <= 12) & (ic >= 0) & (ic <= 4) \
                & (ia > ib) & (ib > ic)
            for k in np.nonzero(m)[0]:
                print("      Board+0x%X  %d → %d → %d" % (lo_b + k * 4 - board, ia[k], ib[k], ic[k]))
            print("-- float32 递减且同区间 --")
            m = np.isfinite(fva) & np.isfinite(fvb) & np.isfinite(fvc) \
                & (fva >= 10) & (fva <= 25) & (fvb >= 5) & (fvb <= 12) & (fvc >= 0) & (fvc <= 4) \
                & (fva > fvb) & (fvb > fvc)
            for k in np.nonzero(m)[0]:
                print("      Board+0x%X  %.3f → %.3f → %.3f" % (lo_b + k * 4 - board, fva[k], fvb[k], fvc[k]))
        else:
            print("   Board 区读取失败")

    # ---------- ② 比例扫描 ----------
    print("\n" + "=" * 72)
    print("② 尺度无关比例扫描：三段严格递减 且 (A-B)/(B-C) ≈ %.3f" % RATIO)
    print("=" * 72)
    res_i, res_f = [], []
    for la, pa, pb, pc, na in region_iter(ma, mb, mc):
        fa.seek(pa); fb.seek(pb); fc.seek(pc)
        off = 0
        while off < na:
            sz = min(CHUNK, na - off)
            da, db, dc = fa.read(sz), fb.read(sz), fc.read(sz)
            if len(da) != sz or len(db) != sz or len(dc) != sz:
                break
            cnt = sz // 4
            A = np.frombuffer(da[:cnt * 4], "<i4").astype(np.int64)
            B = np.frombuffer(db[:cnt * 4], "<i4").astype(np.int64)
            C = np.frombuffer(dc[:cnt * 4], "<i4").astype(np.int64)
            d1 = (A - B).astype(np.float64)
            d2 = (B - C).astype(np.float64)
            m = (d1 > 0) & (d2 > 0) & (np.abs(A) < 10 ** 9) & (np.abs(B) < 10 ** 9)
            m &= (np.abs(d1 / np.where(d2 == 0, 1, d2) - RATIO) < 0.25)
            if m.any():
                for k in np.nonzero(m)[0]:
                    res_i.append((la + off + int(k) * 4, int(A[k]), int(B[k]), int(C[k])))
            FA = np.frombuffer(da[:cnt * 4], "<f4").astype(np.float64)
            FB = np.frombuffer(db[:cnt * 4], "<f4").astype(np.float64)
            FC = np.frombuffer(dc[:cnt * 4], "<f4").astype(np.float64)
            e1 = FA - FB
            e2 = FB - FC
            m = (np.isfinite(FA) & np.isfinite(FB) & np.isfinite(FC)
                 & (e1 > 0) & (e2 > 0) & (FA > 0) & (FA < 1e7))
            m &= (np.abs(e1 / np.where(e2 == 0, 1, e2) - RATIO) < 0.25)
            if m.any():
                for k in np.nonzero(m)[0]:
                    res_f.append((la + off + int(k) * 4, float(FA[k]), float(FB[k]), float(FC[k])))
            off += sz
    print("int32 命中 %d" % len(res_i))
    for a, v1, v2, v3 in sorted(res_i, key=lambda t: -abs(t[1]))[:50]:
        r = (v1 - v2) / (v2 - v3) if v2 != v3 else 0
        print("   0x%-11X %14d → %14d → %14d   比例=%.3f" % (a, v1, v2, v3, r))
    print("float32 命中 %d" % len(res_f))
    for a, v1, v2, v3 in sorted(res_f, key=lambda t: -abs(t[1]))[:50]:
        r = (v1 - v2) / (v2 - v3) if v2 != v3 else 0
        print("   0x%-11X %14.5f → %14.5f → %14.5f   比例=%.3f" % (a, v1, v2, v3, r))
    json.dump({"ratio": RATIO, "int": res_i[:2000], "float": res_f[:2000]},
              open(DIR + "/deep.json", "w"))
    print("\n已存 %s/deep.json" % DIR)


if __name__ == "__main__":
    main()
