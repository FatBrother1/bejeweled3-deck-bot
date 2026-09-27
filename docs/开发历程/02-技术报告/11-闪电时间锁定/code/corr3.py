#!/usr/bin/env python3
"""倒计时甄别终版：相关性（谁变画面跟着变）+ 冻结（钉住谁尖峰消失）。

裁剪框用右上角 (1010,10)-(1155,90)（修正之前的坐标错误）。
候选 = scan3 的 19 个下降者。
  相关阶段：事件 = 候选"显示秒"变化；看 ±0.35s 内是否出现 >中位+3 的尖峰。
  冻结阶段：对相关性 ≥0.5 的候选，反复写回原值 4.5s；
            命中 = 冻结期尖峰率 ≈ 0（基线约 1 尖峰/秒）。
"""
import ctypes
import sys
import time

import numpy as np

sys.path.insert(0, "/home/deck")
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR  # noqa: E402
from cap2 import Cap  # noqa: E402
from PIL import Image  # noqa: E402

_libc.process_vm_writev.restype = ctypes.c_ssize_t
BOX = (1010, 10, 1155, 90)
OBS = 18.0
DT_SAMP = 0.12
WBUF = ctypes.create_string_buffer(8)

CANDS = [
    (0xA057EA4, "f4"), (0x3F497E04, "f4"), (0x3F4983A4, "f4"),
    (0x3F49F95C, "f4"), (0xF48DE94, "f4"), (0x1D74A268, "f4"),
    (0xF6F6F00, "ms"),
    (0xF90C0C0, "f8"), (0xF90C0C8, "f8"), (0xF96A630, "f8"),
    (0xF973AE0, "f8"), (0xF97B718, "f8"), (0xF97B720, "f8"),
    (0x3F497D68, "f8"), (0x3F498308, "f8"),
    (0xA0571A0, "f4b"), (0xA0571E0, "f4b"), (0xA057200, "f4b"),
]
DT = {"s": ("<i4", 4), "ms": ("<i4", 4), "f4": ("<f4", 4),
      "f8": ("<f8", 8), "f4b": ("<f4", 4), "f8b": ("<f8", 8)}


def raw_read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    local = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(local), 1,
                               ctypes.byref(remote), 1, 0)
    return buf.raw[:n] if n == size else None


def raw_write(pid, addr, data):
    WBUF.raw = data
    local = _IOV(ctypes.cast(WBUF, ctypes.c_void_p), len(data))
    remote = _IOV(ctypes.c_void_p(addr), len(data))
    return _libc.process_vm_writev(pid, ctypes.byref(local), 1,
                                   ctypes.byref(remote), 1, 0)


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
    cap = Cap()
    vm = VMouse2()

    def live_or_restart():
        f = grab(cap)
        if f is not None and bot_v6.screen_is_gameover(f):
            vm.click(640, 738)
            print("    （结算 → 点『再玩一次』）", flush=True)
            time.sleep(4.0)
            f = grab(cap)
        return f

    # ── 相关阶段 ──
    print("  ═══ 相关阶段（%.0fs，右上角框）═══" % OBS, flush=True)
    live_or_restart()
    series = []
    prev_img = None
    prev_v = {a: None for a, _ in CANDS}
    t_end = time.perf_counter() + OBS
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
            vals[a] = v
            prev_v[a] = v if v is not None else prev_v[a]
        series.append((time.perf_counter(), d, dict(vals)))
        time.sleep(DT_SAMP)

    ds = np.array([s[1] if s[1] is not None else np.nan for s in series])
    ts = np.array([s[0] for s in series])
    valid = ~np.isnan(ds)
    floor = float(np.nanmedian(ds))
    thr = floor + 3.0
    spikes = valid & (ds > thr)
    print("  噪声中位=%.2f 阈值=%.2f 尖峰帧=%d"
          % (floor, thr, int(spikes.sum())))
    si = np.nonzero(spikes)[0]
    if len(si) >= 3:
        gaps = np.diff(ts[si])
        print("  尖峰间隔: %s" % ([round(x, 2) for x in np.diff(ts[si])[:10]]))

    print()
    print("  ── 相关性 ──")
    good = []
    for a, k in CANDS:
        ev_hit = ev_tot = 0
        seq = []
        for i in range(1, len(series)):
            t, d, vals = series[i]
            v = vals.get(a)
            pv = series[i - 1][2].get(a)
            if v is None or pv is None or d is None:
                continue
            disp = v if k in ("s", "f4", "f8") else np.floor(v / 100.0)
            pd = pv if k in ("s", "f4", "f8") else np.floor(pv / 100.0)
            if disp != pd:
                ev_tot += 1
                m = (ts > t - 0.35) & (ts < t + 0.35) & valid
                peak = float(np.nanmax(ds[m])) if m.any() else 0.0
                hit = peak > thr
                ev_hit += hit
                seq.append((round(disp, 1), round(peak, 1), int(hit)))
        corr = ev_hit / ev_tot if ev_tot else -1
        mark = " ★" if corr >= 0.5 else ""
        print("  0x%-11X [%s] 事件%2d 命中率 %.2f%s  %s"
              % (a, k, ev_tot, corr, mark, seq[:5]))
        if corr >= 0.5 and ev_tot >= 3:
            good.append((a, k, corr))

    # ── 冻结阶段 ──
    print()
    print("  ═══ 冻结阶段（%d 个，尖峰率判据）═══" % len(good), flush=True)
    winner = None
    for a, k, corr in good[:5]:
        v0 = read_val(pid, a, k)
        if v0 is None:
            continue
        f = live_or_restart()
        if f is None:
            continue
        # 基线尖峰率 4s
        imgs = []
        t_e = time.perf_counter() + 4.0
        while time.perf_counter() < t_e:
            fr = grab(cap)
            if fr is not None:
                imgs.append(np.asarray(Image.fromarray(fr).crop(BOX),
                                       dtype=np.int16))
            time.sleep(0.12)
        diffs = [float(np.abs(imgs[i] - imgs[i + 1]).mean())
                 for i in range(len(imgs) - 1)]
        base_spikes = sum(1 for x in diffs if x > floor + 3.0)
        # 冻结 4.5s
        dt_, _ = DT[kind]
        payload = np.array(v0, dtype=dt_).tobytes()
        t_e = time.perf_counter() + 4.5
        nw = n_ok = 0
        lo_v = hi_v = v0
        imgs = []
        while time.perf_counter() < t_e:
            nw += 1
            if raw_write(pid, a, payload) == len(payload):
                n_ok += 1
            v = read_val(pid, a, k)
            if v is not None:
                lo_v, hi_v = min(lo_v, v), max(hi_v, v)
            fr = grab(cap)
            if fr is not None:
                imgs.append(np.asarray(Image.fromarray(fr).crop(BOX),
                                       dtype=np.int16))
            time.sleep(0.12)
        diffs = [float(np.abs(imgs[i] - imgs[i + 1]).mean())
                 for i in range(len(imgs) - 1)]
        frz_spikes = sum(1 for x in diffs if x > floor + 3.0)
        stayed = (hi_v - lo_v) < 1e-3
        hit = base_spikes >= 2 and frz_spikes == 0
        print("  0x%-11X [%s] 相关%.2f 基线尖峰%d 冻结尖峰%d 写%d/%d "
              "漂移=%.2f → %s%s"
              % (a, k, corr, base_spikes, frz_spikes, n_ok, nw,
                 hi_v - lo_v, "★★★ 命中" if hit else "否",
                 " (值被钉住)" if stayed else " (值仍在变)"), flush=True)
        if hit and winner is None:
            winner = (a, k, v0)
        time.sleep(1.0)

    cap.stop()
    vm.close()
    print()
    if winner:
        a, k, v0 = winner
        print("  ★★★ 倒计时字段 = 0x%X [%s] ★★★" % (a, k))
        print("  锁定：python3 tscan2.py hold 300 0x%X %s" % (a, k))
        with open("/home/deck/timer_winner.txt", "w") as fo:
            fo.write("0x%X %s\n" % (a, k))
    else:
        print("  ❌ 无命中")


if __name__ == "__main__":
    main()
