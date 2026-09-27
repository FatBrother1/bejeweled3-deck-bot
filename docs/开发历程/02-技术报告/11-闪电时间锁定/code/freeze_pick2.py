#!/usr/bin/env python3
"""定向冻结甄别 v2 —— 修正 freeze_pick 的状态问题（没有活跃对局也硬测）。

流程：ensure_round（结算就点再玩一次）→ 等倒计时框真的开始跳
（2 秒窗帧间差 > 1，最多等 40 秒）→ 逐候选冻结。

判据：命中 = 冻结期帧间差 < 1.5（绝对值）且基线期 > 1。
候选顺序：Board+0x38(厘秒) 最优先 —— 上轮幸存者里它是唯一
「以 100/秒 速率穿过全部区间」的；值 6761 ↔ Board+0xC84 的 67 秒
floor 自洽（67.61s）。
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
BOX = (495, 15, 625, 85)
WBUF = ctypes.create_string_buffer(8)

CANDS = [
    (0xF3A1190, "ms"),    # Board+0x38   厘秒 ★头号
    (0xF3A1DDC, "s"),     # Board+0xC84  整秒
    (0xF3A1F90, "ms"),    # Board+0xE38
    (0xF3A1F94, "ms"),    # Board+0xE3C
    (0xF3A4200, "q"),     # Board+0x30A8
    (0x1E3F8D04, "f4b"),  # 对照组
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


def encode(kind, v):
    dt, _ = DT[kind]
    return np.array(v, dtype=dt).tobytes()


def grab(cap):
    for _ in range(12):
        a = cap.get(timeout=0.5)
        if a is not None:
            return a
    return None


def box(frame):
    return np.asarray(Image.fromarray(frame).crop(BOX), dtype=np.int16)


def diff(crops):
    if len(crops) < 2:
        return 99.0
    return float(np.mean([np.abs(crops[i] - crops[i + 1]).mean()
                          for i in range(len(crops) - 1)]))


def ensure_round(cap, vm):
    f = grab(cap)
    if f is None:
        return None
    import bot_v6
    if bot_v6.screen_is_gameover(f):
        vm.click(640, 738)
        print("    （结算 → 点『再玩一次』）", flush=True)
        time.sleep(3.0)
        f = grab(cap)
    return f


def wait_for_tick(cap, timeout=40.0):
    """等倒计时框开始跳（窗口帧间差 > 1）。"""
    t_end = time.perf_counter() + timeout
    while time.perf_counter() < t_end:
        crops = []
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 2.0:
            f = grab(cap)
            if f is not None:
                crops.append(box(f))
            time.sleep(0.25)
        d = diff(crops)
        if d > 1.0:
            return True, d
        f = grab(cap)
        if f is not None:
            import bot_v6
            if bot_v6.screen_is_gameover(f):
                vm = VM
                vm.click(640, 738)
                print("    （又结算 → 点『再玩一次』）", flush=True)
                time.sleep(3.0)
    return False, d


VM = None


def main():
    global VM
    pid = find_pid()
    g = None
    board = None
    raw = raw_read(pid, GAPP_ADDR, 4)
    if raw:
        g = int(np.frombuffer(raw, dtype="<u4")[0])
        rb = raw_read(pid, g + 0xBE8, 4)
        if rb:
            board = int(np.frombuffer(rb, dtype="<u4")[0])
    print("  PID=%d gApp=%s Board=%s" % (pid, hex(g) if g else "?",
                                         hex(board) if board else "?"))
    cap = Cap()
    from vmouse2 import VMouse2
    VM = VMouse2()

    f = ensure_round(cap, VM)
    ok, d = wait_for_tick(cap)
    if not ok:
        print("  ❌ 40 秒内倒计时框没动过（没有进行中的对局）—— 中止，不硬测。")
        cap.stop()
        VM.close()
        return
    print("  框在跳（差=%.2f），开始冻结测试\n" % d, flush=True)

    winner = None
    for addr, kind in CANDS:
        v0 = read_val(pid, addr, kind)
        if v0 is None:
            continue
        rel = ""
        if board and board <= addr < board + 0x4000:
            rel = "Board+0x%X" % (addr - board)
        # 基线 3.2s
        crops = []
        t_end = time.perf_counter() + 3.2
        while time.perf_counter() < t_end:
            fr = grab(cap)
            if fr is not None:
                crops.append(box(fr))
            time.sleep(0.3)
        d_tick = diff(crops)
        if d_tick <= 1.0:
            print("  0x%-11X [%s] %-14s 基线=%.2f —— 框停了（对局结束？）跳过"
                  % (addr, kind, rel, d_tick), flush=True)
            f2 = ensure_round(cap, VM)
            ok2, _ = wait_for_tick(cap, 25.0)
            if not ok2:
                break
            continue
        payload = encode(kind, v0)
        t_end = time.perf_counter() + 4.5
        nw = n_ok = 0
        lo_v = hi_v = v0
        crops = []
        while time.perf_counter() < t_end:
            nw += 1
            if raw_write(pid, addr, payload) == len(payload):
                n_ok += 1
            v = read_val(pid, addr, kind)
            if v is not None:
                lo_v, hi_v = min(lo_v, v), max(hi_v, v)
            fr = grab(cap)
            if fr is not None:
                crops.append(box(fr))
            time.sleep(0.15)
        d_frz = diff(crops)
        hit = d_tick > 1.0 and d_frz < 1.5
        stayed = (hi_v - lo_v) < 1e-3
        print("  0x%-11X [%s] %-14s 值=%-8.0f 基线=%6.2f 冻结=%6.2f "
              "写%d/%d 漂移=%.1f → %s%s"
              % (addr, kind, rel, v0, d_tick, d_frz, n_ok, nw, hi_v - lo_v,
                 "★命中" if hit else "否",
                 " (值被钉住)" if stayed else " (值仍在变)"), flush=True)
        if hit and winner is None:
            winner = (addr, kind, v0)
        time.sleep(1.0)

    cap.stop()
    VM.close()
    print()
    if winner:
        addr, kind, v0 = winner
        print("  ★★★ 倒计时字段 = 0x%X [%s] ★★★" % (addr, kind))
        print("  锁定：python3 tscan2.py hold 300 0x%X %s" % (addr, kind))
        with open("/home/deck/timer_winner.txt", "w") as fo:
            fo.write("0x%X %s\n" % (addr, kind))
    else:
        print("  ❌ 全否")


if __name__ == "__main__":
    main()
