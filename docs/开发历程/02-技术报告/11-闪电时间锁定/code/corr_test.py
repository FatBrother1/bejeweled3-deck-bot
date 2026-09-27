#!/usr/bin/env python3
"""相关性甄别：谁变的时候画面跟着变，谁就是显示源（零写入、抗背景噪声）。

背景：倒计时框区域有持续动画（实测冻结差噪声底 ≈ 6.0），
冻结测试的信号被淹没。改用相关性：
  每 0.12s 采样一轮：读全部候选值 + 抓一帧，算框区帧间差序列。
  对每个候选取"显示秒数变化事件"（s: 值变化；cs: floor(v/100) 变化），
  看事件 ±0.35s 内是否出现 差值 > 中位数+4 的尖峰。
  真显示源 → 命中率 ≥ 0.8；副本/无关 → 随机水平。
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
OBS = 16.0
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
    t_end = time.perf_counter() + OBS
    series = []          # (t, diff, {addr: disp_val})
    prev_img = None
    prev_v = {a: None for a, _ in CANDS}
    n = 0
    while time.perf_counter() < t_end:
        f = grab(cap)
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
            # 显示秒数：s 直接用值；cs 类用 floor(v/100)
            vals[a] = v if k == "s" else np.floor(v / 100.0)
            prev_v[a] = v
        series.append((time.perf_counter(), d, dict(vals)))
        n += 1
        time.sleep(DT_SAMP)
    cap.stop()

    ds = np.array([s[1] if s[1] is not None else np.nan for s in series])
    ts = np.array([s[0] for s in series])
    valid = ~np.isnan(ds)
    floor = float(np.nanmedian(ds))
    p90 = float(np.nanpercentile(ds, 90))
    print("  采样 %d 帧  噪声中位=%.2f p90=%.2f" % (n, floor, p90))
    thr = floor + 4.0

    # 自检：尖峰（>thr）的时间间隔 —— ≈1.0s 说明裁剪框里有每秒翻转的数字
    spike_idx = np.nonzero(valid & (ds > thr))[0]
    print("  尖峰帧数 %d" % len(spike_idx))
    if len(spike_idx) >= 3:
        gaps = np.diff(ts[spike_idx])
        gaps = gaps[gaps > 0.5]          # 只看跨秒的大间隔
        if len(gaps):
            print("  尖峰间隔（>0.5s 的）: %s"
                  % [round(g, 2) for g in gaps[:12]])
        else:
            print("  （无 >0.5s 的间隔 —— 可能一直在连续变化）")
    else:
        print("  ⚠ 尖峰太少 —— 裁剪框里可能根本没有数字（或对局没在跑）")

    print()
    print("  ── 相关性（事件 ±0.35s 内出现 >%.1f 尖峰的比例）──" % thr)
    rows = []
    for a, k in CANDS:
        rel = ("Board+0x%X" % (a - board)) if board and board <= a < board + 0x4000 else ""
        ev_hit = ev_tot = 0
        detail = []
        for i, (t, d, vals) in enumerate(series):
            v = vals.get(a)
            pv = series[i - 1][2].get(a) if i else None
            if v is None or pv is None or d is None:
                continue
            if v != pv:                      # 显示秒数变化事件
                ev_tot += 1
                m = (ts > t - 0.35) & (ts < t + 0.35) & valid
                peak = float(np.nanmax(ds[m])) if m.any() else 0.0
                hit = peak > thr
                ev_hit += hit
                detail.append((round(v, 1), round(peak, 1), hit))
        corr = ev_hit / ev_tot if ev_tot else -1
        rows.append((corr, a, k, rel, ev_tot, detail))
    rows.sort(reverse=True)
    for corr, a, k, rel, ev_tot, detail in rows:
        if ev_tot == 0:
            print("  0x%-11X [%s] %-14s 无变化事件" % (a, k, rel))
            continue
        print("  0x%-11X [%s] %-14s 事件%2d 命中率 %.2f  %s"
              % (a, k, rel, ev_tot, corr,
                 detail[:6]))
    print()
    print("  （候选值本身也存了 —— 行首命中率最高的就是显示源）")


if __name__ == "__main__":
    main()
