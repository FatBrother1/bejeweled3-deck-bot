#!/usr/bin/env python3
"""闪电模式倒计时定位 v3 —— 在 v2 基础上修三个洞。

v2 实测教训（2026-09-25）：
  漏斗 973→140→17→10→9→1 有效，但真计时器死于换局：
  round 重开时倒计时从 ~0 跳回 60000，率判据把它杀了。
v3 修正：
  1. 跳变合法化：每区间通过 = 严格率(±{1,10,100,1000}/s)
     或 向上跳变 ≤ +20s(时间宝石) 或 换局重开(该区间点过『再玩一次』且 cur≥55s)。
     每个候选记录历史（严格通过次数），最后按严格数排序。
  2. 表示类别扩充：i4秒 / i4毫秒·厘秒 / i64 / f4·f8 秒制 / f4·f8 毫秒制。
  3. 冻结甄别不变（写回原值=对非计时器无操作；框像素停变=命中），
     候选按「严格通过数」排序取前 8。
用法：
  python3 tscan2.py            # 发现 + 冻结甄别（约 3 分钟）
  python3 tscan2.py scan       # 只发现
  python3 tscan2.py hold 300 0xADDR f4    # 锁定（发现之后）
"""
import ctypes
import json
import os
import re
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR  # noqa: E402
from cap2 import Cap  # noqa: E402
from PIL import Image  # noqa: E402

_libc.process_vm_writev.restype = ctypes.c_ssize_t

CHUNK = 16 * 1024 * 1024
BOX = (495, 15, 625, 85)
OUT = "/home/deck/tcap"
INTERVAL = 8.0
NSAMPLE = 12
MAX_FREEZE = 8

RATE_TOL = {1.0: 0.25, 10.0: 2.5, 100.0: 25.0, 1000.0: 250.0}
# 类别: (dtype, 步长, 值下限, 值上限, 换局重开下限)
# 秒制重开=55；毫秒制重开=55000
CLASSES = (
    ("s",   "<i4", 4, 1, 61, 55.0),
    ("ms",  "<i4", 4, 100, 61000, 55000.0),
    ("q",   "<i8", 8, 1, 61000, 55000.0),
    ("f4",  "<f4", 4, 1.0, 65.0, 55.0),
    ("f8",  "<f8", 8, 1.0, 65.0, 55.0),
    ("f4b", "<f4", 4, 500.0, 65000.0, 55000.0),
    ("f8b", "<f8", 8, 500.0, 65000.0, 55000.0),
)
MS_LIKE = {"ms", "q", "f4b", "f8b"}     # 值按毫秒尺度解释的类

WBUF = ctypes.create_string_buffer(8)


def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1,
                               ctypes.byref(remote), 1, 0)
    if n != size:
        return None
    return buf.raw[:size]


def raw_write(pid, addr, data):
    WBUF.raw = data
    local = _IOV(ctypes.cast(WBUF, ctypes.c_void_p), len(data))
    remote = _IOV(ctypes.c_void_p(addr), len(data))
    return _libc.process_vm_writev(pid, ctypes.byref(local), 1,
                                   ctypes.byref(remote), 1, 0)


def encode(kind, v):
    for name, dt, step, _, _, _ in CLASSES:
        if kind == name:
            return np.array(v, dtype=dt).tobytes()
    raise ValueError(kind)


def read_val(pid, addr, kind):
    for name, dt, step, _, _, _ in CLASSES:
        if kind == name:
            raw = raw_read(pid, addr, step)
            if raw is None:
                return None
            return float(np.frombuffer(raw, dtype=dt)[0])
    raise ValueError(kind)


def rw_regions(pid):
    out = []
    with open("/proc/%d/maps" % pid) as f:
        for line in f:
            m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+(\S+)?", line)
            if not m:
                continue
            lo, hi, perm = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
            path = m.group(4) or ""
            if "w" not in perm or hi - lo <= 0:
                continue
            if "/dev/" in path or ".pak" in path or ".so" in path:
                continue
            out.append((lo, hi))
    return out


def scan_once(pid, regs):
    """一遍扫描收集全部类别。返回 {kind: (addrs u64, vals f8)}。"""
    acc = {c[0]: ([], []) for c in CLASSES}
    for lo, hi in regs:
        off0 = 0
        while off0 < hi - lo:
            size = min(CHUNK, hi - lo - off0)
            size -= size % 8
            if size <= 0:
                break
            raw = raw_read(pid, lo + off0, size)
            if raw is None:
                off0 += size
                continue
            base = lo + off0
            for kind, dt, step, vlo, vhi, _ in CLASSES:
                n = len(raw) // step
                arr = np.frombuffer(raw[:n * step], dtype=dt)
                mask = (arr >= vlo) & (arr <= vhi)
                idx = np.nonzero(mask)[0]
                if len(idx):
                    acc[kind][0].append(base + idx.astype(np.uint64) * step)
                    acc[kind][1].append(arr[idx].astype(np.float64))
            off0 += size
    out = {}
    for kind, (aa, vv) in acc.items():
        if aa:
            out[kind] = (np.concatenate(aa), np.concatenate(vv))
    return out


def join_decayed(prev, cur, dt):
    """S0→S1 首次求交：严格率过滤。"""
    surv = {}
    for kind, _, _, _, _, _ in CLASSES:
        if kind not in prev or kind not in cur:
            continue
        pa, pv = prev[kind]
        ca, cv = cur[kind]
        order = np.argsort(ca)
        ca, cv = ca[order], cv[order]
        lo = np.searchsorted(ca, pa)
        hi = np.searchsorted(ca, pa, side="right")
        hit = np.nonzero(hi > lo)[0]
        if not len(hit):
            continue
        rate = (pv[hit] - cv[lo[hit]]) / dt
        r = np.abs(rate)
        good = np.zeros(len(hit), dtype=bool)
        for k, tol in RATE_TOL.items():
            good |= np.abs(r - k) < tol
        if good.any():
            surv[kind] = (pa[hit][good], cv[lo[hit]][good])
    return surv


def grab(cap):
    for _ in range(12):
        a = cap.get(timeout=0.5)
        if a is not None:
            return a
    return None


def ensure_round(cap, m, bot_v6):
    a = grab(cap)
    if a is None:
        return a, False
    if bot_v6 is not None and bot_v6.screen_is_gameover(a):
        if m is not None:
            m.click(640, 738)
            print("    （结算 → 已点『再玩一次』）", flush=True)
            time.sleep(3.0)
            a = grab(cap)
            return a, True
        return a, False
    return a, False


def recheck_candidates(pid, cands, dt, restart):
    """候选制回读。cands: {addr: [kind, last_val, n_strict, n_lenient, hist]}
    返回新一代 cands。"""
    out = {}
    for addr, (kind, last, ns, nl, hist) in cands.items():
        v = read_val(pid, addr, kind)
        if v is None:
            continue
        rate = (last - v) / dt
        r = abs(rate)
        strict = any(abs(r - k) < tol for k, tol in RATE_TOL.items())
        lo_up = 20.0 if kind in ("s", "f4", "f8") else 20000.0
        jump = (v - last) > 0 and (v - last) <= lo_up
        re_hi = [c[5] for c in CLASSES if c[0] == kind][0]
        reborn = restart and v >= re_hi
        if strict or jump or reborn:
            h = dict(hist)
            h[-1] = round(v, 3)
            out[addr] = (kind, v,
                         ns + (1 if strict else 0),
                         nl + (0 if strict else 1),
                         h)
    return out


def freeze_test(pid, ranked, cap, m, bot_v6):
    print("  冻结测试前 %d 个候选（每个约 8 秒；写回原值=对非计时器无操作）"
          % min(len(ranked), MAX_FREEZE), flush=True)
    winner = None
    for addr, kind, ns, tag in ranked[:MAX_FREEZE]:
        v0 = read_val(pid, addr, kind)
        if v0 is None:
            continue
        a, _ = ensure_round(cap, m, bot_v6)
        if a is None:
            print("    0x%-11X 抓不到帧，跳过" % addr, flush=True)
            continue
        crops = []
        t_end = time.perf_counter() + 3.0
        while time.perf_counter() < t_end:
            f = grab(cap)
            if f is not None:
                crops.append(np.asarray(Image.fromarray(f).crop(BOX),
                                        dtype=np.int16))
            time.sleep(0.35)
        if len(crops) < 4:
            continue
        d_tick = float(np.mean([np.abs(crops[i] - crops[i + 1]).mean()
                                for i in range(len(crops) - 1)]))
        payload = encode(kind, v0)
        t_end = time.perf_counter() + 4.5
        nw = 0
        crops = []
        while time.perf_counter() < t_end:
            if raw_write(pid, addr, payload) == len(payload):
                nw += 1
            f = grab(cap)
            if f is not None:
                crops.append(np.asarray(Image.fromarray(f).crop(BOX),
                                        dtype=np.int16))
            time.sleep(0.15)
        d_frz = (float(np.mean([np.abs(crops[i] - crops[i + 1]).mean()
                                for i in range(len(crops) - 1)]))
                 if len(crops) > 1 else 99.0)
        hit = d_tick > 1.0 and d_frz < max(0.4, 0.25 * d_tick)
        print("    0x%-11X [%s] 严格%d  %-14s 基线=%6.2f 冻结=%6.2f 写%3d → %s"
              % (addr, kind, ns, tag, d_tick, d_frz, nw,
                 "★命中" if hit else "否"), flush=True)
        if hit and winner is None:
            winner = (addr, kind, v0)
        time.sleep(1.0)
    return winner


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode == "hold":
        secs = int(sys.argv[2])
        addr = int(sys.argv[3], 16)
        kind = sys.argv[4]
        pid = find_pid()
        v0 = read_val(pid, addr, kind)
        payload = encode(kind, v0)
        print("  锁定 0x%X [%s] = %.3f，%d 秒（Ctrl-C 停）" % (addr, kind, v0, secs))
        t0 = time.time()
        n = 0
        try:
            while time.time() - t0 < secs:
                if raw_write(pid, addr, payload) == len(payload):
                    n += 1
                time.sleep(0.15)
        except KeyboardInterrupt:
            pass
        print("  结束（写 %d 次）" % n)
        return

    only_scan = mode == "scan"
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    g = None
    raw = raw_read(pid, GAPP_ADDR, 4)
    if raw:
        g = int(np.frombuffer(raw, dtype="<u4")[0])
    regs = rw_regions(pid)
    print("  PID=%d gApp=%s 可写段 %d / %.0f MB"
          % (pid, hex(g) if g else "?", len(regs),
             sum(h - l for l, h in regs) / 1e6), flush=True)

    cap = Cap()
    m = None
    try:
        import bot_v6
    except Exception:
        bot_v6 = None
    try:
        from vmouse2 import VMouse2
        m = VMouse2()
    except Exception:
        m = None

    print("  ═══ S0 / S1 全扫 ═══", flush=True)
    ensure_round(cap, m, bot_v6)
    t0 = time.perf_counter()
    S0 = scan_once(pid, regs)
    print("  S0: " + ", ".join("%s=%d" % (k, len(v[0])) for k, v in S0.items())
          + " (%.1fs)" % (time.perf_counter() - t0), flush=True)
    if not S0:
        cap.stop()
        return
    time.sleep(INTERVAL)
    ensure_round(cap, m, bot_v6)
    t1 = time.perf_counter()
    S1 = scan_once(pid, regs)
    dt = t1 - t0
    print("  S1: " + ", ".join("%s=%d" % (k, len(v[0])) for k, v in S1.items())
          + " (%.1fs, dt=%.2f)" % (time.perf_counter() - t1, dt), flush=True)

    joined = join_decayed(S0, S1, dt)
    del S0, S1
    cands = {}
    for kind, (aa, vv) in joined.items():
        for i in range(len(aa)):
            cands[int(aa[i])] = (kind, float(vv[i]), 1, 0,
                                 {-1: round(float(vv[i]), 3)})
    n0 = len(cands)
    print("  首轮交+率过滤存活: %d" % n0, flush=True)
    if n0 == 0:
        print("  ❌ 零存活")
        cap.stop()
        return

    print("  ═══ 区间回读（每 %ds，%d 个）═══" % (int(INTERVAL), NSAMPLE - 2), flush=True)
    hist_f = open(os.path.join(OUT, "cands_history.jsonl"), "w")
    t1 = time.perf_counter()
    for k in range(NSAMPLE - 2):
        time.sleep(INTERVAL)
        tk = time.perf_counter()
        a, restart = ensure_round(cap, m, bot_v6)
        if a is not None:
            Image.fromarray(a).crop(BOX).save("%s/box_%02d.png" % (OUT, k))
        cands = recheck_candidates(pid, cands, tk - t1, restart)
        t1 = tk
        if not cands:
            print("    区间 %d: 存活 0 ❌" % (k + 2), flush=True)
            break
        # 记录历史
        rec = [{"addr": "0x%X" % a, "kind": c[0], "v": round(c[1], 3),
                "strict": c[2]} for a, c in sorted(cands.items())]
        hist_f.write(json.dumps({"interval": k + 2, "restart": restart,
                                 "n": len(rec), "cands": rec}) + "\n")
        hist_f.flush()
        print("    区间 %d: 存活 %d%s" % (k + 2, len(cands),
                                          "（换局）" if restart else ""),
              flush=True)
    hist_f.close()

    if not cands:
        cap.stop()
        if m is not None:
            m.close()
        return

    print()
    print("  ═══ 幸存者（按严格通过数排序）═══", flush=True)
    ranked = sorted(cands.items(),
                    key=lambda kv: (-kv[1][2], kv[1][0]))
    rows = []
    for addr, (kind, v, ns, nl, hist) in ranked:
        tag = ""
        if g and g <= addr < g + 0x20000:
            tag = "gApp+0x%X" % (addr - g)
        elif 0x400000 <= addr < 0x940000:
            tag = "主模块数据段"
        rows.append((addr, kind, ns, tag))
        print("    0x%-11X [%s] 严格%2d 宽松%2d 值=%-12.3f %s"
              % (addr, kind, ns, nl, v, tag), flush=True)
    with open("/home/deck/timer_found.txt", "w") as f:
        for addr, (kind, v, ns, nl, hist) in sorted(cands.items()):
            f.write("0x%X %s strict=%d lenient=%d last=%.4f hist=%s\n"
                    % (addr, kind, ns, nl, v, json.dumps(hist)))
    print("  历史已存 /home/deck/timer_found.txt + tcap/cands_history.jsonl",
          flush=True)

    winner = None
    if not only_scan:
        print()
        print("  ═══ 冻结甄别 ═══", flush=True)
        winner = freeze_test(pid, rows, cap, m, bot_v6)
        if winner:
            addr, kind, v0 = winner
            print()
            print("  ★★★ 倒计时字段 = 0x%X [%s] ★★★" % (addr, kind), flush=True)
            print("  锁定：python3 tscan2.py hold 300 0x%X %s" % (addr, kind))
            with open("/home/deck/timer_winner.txt", "w") as f:
                f.write("0x%X %s\n" % (addr, kind))
        else:
            print("  ❌ 冻结无命中 —— 幸存者与画面都对不上，"
                  "历史已存档可离线分析。")

    cap.stop()
    if m is not None:
        m.close()


if __name__ == "__main__":
    main()
