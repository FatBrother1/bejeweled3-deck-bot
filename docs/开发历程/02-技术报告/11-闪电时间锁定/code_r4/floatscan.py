#!/usr/bin/env python3
"""floatscan.py —— 离线正确版浮点扫描（修正 analyze.py 的位解释 bug）。

analyze.py 里 `fva = ia.astype(np.float64)` 是把「整数 15」转成「浮点 15.0」，
而不是把 0x0000000F 这四个字节**重新解释**为 float。于是浮点轴实际从未被扫描。

本版用 .view("<f4") 正确重解释位模式，把 A/B/C 三份快照在
「秒 / 十分秒 / 厘秒」三种刻度下扫一遍，并强制 A≠B≠C。

用法：python3 floatscan.py
"""
import json
import numpy as np

DIR = "/home/deck/tb"
CHUNK = 512 * 1024


def load(tag):
    meta = json.load(open("%s/%s.json" % (DIR, tag)))
    return meta, open("%s/%s.bin" % (DIR, tag), "rb")


def main():
    ma, fa = load("A")
    mb, fb = load("B")
    mc, fc = load("C")
    dAB = mb["cs"] - ma["cs"]
    dBC = mc["cs"] - mb["cs"]
    print("ΔAB=%d cs (%.3fs)   ΔBC=%d cs (%.3fs)"
          % (dAB, dAB / 100.0, dBC, dBC / 100.0))

    for sname, sc in (("秒", 1.0), ("十分秒", 10.0), ("厘秒", 100.0)):
        tAB = dAB * sc / 100.0
        tBC = dBC * sc / 100.0
        tol = max(0.30, sc * 0.035)
        hits = []
        for (la, pa, na), (lb, pb, nb), (lc, pc, nc) in zip(
                ma["regions"], mb["regions"], mc["regions"]):
            if min(na, nb, nc) <= 0 or la != lb or la != lc or na != nb or na != nc:
                continue
            fa.seek(pa); fb.seek(pb); fc.seek(pc)
            off = 0
            while off < na:
                sz = min(CHUNK, na - off)
                da, db, dc = fa.read(sz), fb.read(sz), fc.read(sz)
                if len(da) != sz or len(db) != sz or len(dc) != sz:
                    break
                cnt = sz // 4
                A = np.frombuffer(da[:cnt * 4], "<f4").astype(np.float64)
                B = np.frombuffer(db[:cnt * 4], "<f4").astype(np.float64)
                C = np.frombuffer(dc[:cnt * 4], "<f4").astype(np.float64)
                fin = np.isfinite(A) & np.isfinite(B) & np.isfinite(C)
                m = (fin
                     & (np.abs((A - B) - tAB) <= tol)
                     & (np.abs((B - C) - tBC) <= tol)
                     & (A > 0) & (A < 1e5)
                     & (A != B) & (B != C))
                if m.any():
                    for k in np.nonzero(m)[0]:
                        hits.append((la + off + int(k) * 4, A[k], B[k], C[k]))
                off += sz
        print("\n=== 刻度「%s」 tol=%.2f：命中 %d ===" % (sname, tol, len(hits)))
        for a, v1, v2, v3 in sorted(hits, key=lambda t: -t[1])[:40]:
            frac = "  (整数值!)" if abs(v1 - round(v1)) < 1e-3 and abs(v2 - round(v2)) < 1e-3 else ""
            print("   0x%-11X %14.5f → %14.5f → %14.5f%s" % (a, v1, v2, v3, frac))
    fa.close(); fb.close(); fc.close()


if __name__ == "__main__":
    main()
