#!/usr/bin/env python3
"""相关性甄别 v2 —— 带"确保有活跃对局"门控。

结算就点『再玩一次』；观察期内对局结束则点续局并继续累计事件。
判据同 v1：候选"显示秒数变化事件" ±0.35s 内出现 >中位+4 尖峰的比例。
"""
import ctypes
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR  # noqa: E402
from cap2 import Cap  # noqa: E402
from PIL import Image  # noqa: E402

BOX = (495, 15, 625, 85)
OBS = 22.0
DT_SAMP = 0.12

CANDS = [
    (0xF3A1190, "ms"),    # Board+0x38   cs
    (0xF3A1DDC, "s"),     # Board+0xC84  整秒
    (0xF3A1F90, "ms"),    # Board+0xE38
    (0xF3A1F94, "ms"),    # Board+0xE3C
    (0xF3A4200, "q"),     # Board+0x30A8
    (0x1E3F8D04, "f4b"),  # 对照
]
DT = {"s": ("<i4", 4), "ms": ("<i4", 4), "q": ("<i8", 8),
      "f4": ("<f4", 4), "f8": ("<f8", 8), "f4b": ("<f4", 4), "f8b": ("<f8", 8)}


def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1,
                               ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None


def read_val(pid, addr, kind):
    dt, step = DT[kind]
    raw = raw_read(pid, addr, step)
    if raw is None:
        return None
    return float(np.frombuffer(raw, dtype=dt)[0])


def grab(cap):
    for _ in range(12):
        a = cap.get(timeout=0.5)
        if a is not None:
            return a
    return None


def main():
    import bot_v6
    from vmouse2 import VMouse2
    pid = find_pid()
    g = board = None
    raw = raw_read(pid, GAPP_ADDR, 4)
    if raw:
        g = int(np.frombuffer(raw, dtype="<u4")[0])
        rb = raw_read(pid, g + 0xBE8, 4)
        if rb:
            board = int(np.frombuffer(rb, dtype="<u4")[0])
    print("  PID=%d Board=%s" % (pid, hex(board) if board else "?"))

    cap = Cap()
    vm = VMouse2()

    def live_or_restart():
        """结算就点续局。返回当前帧。"""
        f = grab(cap)
        if f is not None and bot_v6.screen_is_gameover(f):
            vm.click(640, 738)
            print("    （结算 → 点『再玩一次』）", flush=True)
            time.sleep(3.5)
            f = grab(cap)
        return f

    # ── 先确保对局活跃：等框区出现每秒尖峰 ──
    print("  等活跃对局（最多 45 秒）…", flush=True)
    t0 = time.perf_counter()
    prev_img = None
    live = False
    while time.perf_counter() - t0 < 45.0:
        f = live_or_restart()
        if f is None:
            time.sleep(0.3)
            continue
        img = np.asarray(Image.fromarray(f).crop(BOX), dtype=np.int16)
        if prev_img is not None:
            if float(np.abs(img - prev_img).mean()) > 3.0:
                live = True
                break
        prev_img = img
        time.sleep(0.2)
    if not live:
        print("  ❌ 45 秒内框区没有动过 —— 游戏不在对局里（也可能裁剪框坐标变了）。")
        cap.stop()
        vm.close()
        return

    # ── 观察循环 ──
    t_end = time.perf_counter() + OBS
    series = []
    prev_img = None
    prev_v = {a: None for a, _ in CANDS}
    n = 0
    while time.perf_counter() < t_end:
        f = live_or_restart()
        d = None
        if f is not None:
            img = np.asarray(Image.fromarray(f).crop(BOX), dtype=np.int16)
            if prev_img is not None and img.shape == prev_img.shape:
                d = float(np.abs(img - prev_img).mean())
            prev_img = img
        vals = {}
        for a, k in CANDS:
            v = read_val(pid, a, k)
            if v is None:
                vals[a] = prev_v[a]
                continue
            vals[a] = v if k == "s" else np.floor(v / 100.0)
            prev_v[a] = v
        series.append((time.perf_counter(), d, dict(vals)))
        n += 1
        time.sleep(DT_SAMP)
    cap.stop()
    vm.close()

    ds = np.array([s[1] if s[1] is not None else np.nan for s in series])
    ts = np.array([s[0] for s in series])
    valid = ~np.isnan(ds)
    floor = float(np.nanmedian(ds))
    thr = floor + 4.0
    spike_idx = np.nonzero(valid & (ds > thr))[0]
    print("  采样 %d  噪声中位=%.2f  尖峰帧=%d" % (n, floor, len(spike_idx)))
    if len(spike_idx) >= 3:
        gaps = np.diff(ts[spike_idx])
        gaps = gaps[gaps > 0.5]
        print("  尖峰间隔: %s" % ([round(x, 2) for x in gaps[:12]] or "无>0.5s间隔"))
    else:
        print("  ⚠ 尖峰太少")

    print()
    print("  ── 相关性 ──")
    rows = []
    for a, k in CANDS:
        rel = ("Board+0x%X" % (a - board)) if board and board <= a < board + 0x4000 else ""
        ev_hit = ev_tot = 0
        detail = []
        for i in range(1, len(series)):
            t, d, vals = series[i]
            v = vals.get(a)
            pv = series[i - 1][2].get(a)
            if v is None or pv is None or d is None:
                continue
            if v != pv:
                ev_tot += 1
                m = (ts > t - 0.35) & (ts < t + 0.35) & valid
                peak = float(np.nanmax(ds[m])) if m.any() else 0.0
                hit = peak > thr
                ev_hit += hit
                detail.append((round(v, 1), round(peak, 1), int(hit)))
        corr = ev_hit / ev_tot if ev_tot else -1
        rows.append((corr, a, k, rel, ev_tot, detail))
    rows.sort(reverse=True)
    for corr, a, k, rel, ev_tot, detail in rows:
        if ev_tot == 0:
            print("  0x%-11X [%s] %-14s 无变化事件" % (a, k, rel))
            continue
        print("  0x%-11X [%s] %-14s 事件%2d 命中率 %.2f  %s"
              % (a, k, rel, ev_tot, corr, detail[:6]))


if __name__ == "__main__":
    main()
