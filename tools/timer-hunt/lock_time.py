#!/usr/bin/env python3
"""【测试工具】锁住闪电模式的倒计时，方便观察时间宝石机制。

    python3 lock_time.py find          # 找倒计时字段（连读看哪个在递减）
    python3 lock_time.py hold 300      # 锁住 300 秒（默认 600）
    python3 lock_time.py release       # 立刻停止锁定

## 这是测试工具，不是 bot 的功能

闪电模式一局只有 1 分钟，根本不够观察「时间宝石怎么加时间」。
本脚本把倒计时按住不动，好从容做实验。**测完就别用了。**

因此：
  · 不集成进 bot_v6.py，不进仓库，不写进 README
  · 只在本机 /home/deck 上跑
  · 用完请自行删除

## 它做什么

用 process_vm_writev 定时把倒计时字段写回锁定值（**不封顶、不改分数、不碰棋盘**）。
只改一个计时器，其余一切照旧。

## 关于写入

reader_mem.py 是只读的（只用 process_vm_readv），本脚本单独实现写入，
不改动 reader_mem 的任何行为。同 uid 即可写，不需要 root。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, "/home/deck")
from reader_mem import _Proc, _IOV, find_pid, GAPP_ADDR, OFF_BOARD   # noqa: E402

_libc = ctypes.CDLL("libc.so.6", use_errno=True)
_libc.process_vm_writev.restype = ctypes.c_ssize_t

# 候选偏移：实测 gApp+0x680 是那个每秒递减的秒数；其它几个一并试。
CANDIDATES = [0x680, 0x67C, 0x684, 0x688, 0x68C,
              0x4D0, 0x6E4, 0x6E8, 0x6EC, 0x6F0, 0x6F4, 0x6F8]
STATE = "/tmp/locktime.state"


_BUF = ctypes.create_string_buffer(4)      # 复用的本地缓冲


def write_i32(pid, addr, val):
    """往目标进程写一个 int32。返回写入字节数（4 表示成功）。

    ★ 写法必须和 reader_mem._Proc.raw 一致（那是验证过能用的读函数）：
      用 _IOV 对象 + ctypes.byref 传参，而不是 (_IOV*1)(...) 数组。
      我第一版用了数组写法，process_vm_writev 返回 0、errno 也是 0，
      查不出所以然 —— 照抄读函数的写法就对了。
    """
    _BUF.raw = int(val & 0xFFFFFFFF).to_bytes(4, "little")
    local = _IOV(ctypes.cast(_BUF, ctypes.c_void_p), 4)
    remote = _IOV(ctypes.c_void_p(addr), 4)
    n = _libc.process_vm_writev(ctypes.c_int(pid),
                                ctypes.byref(local), ctypes.c_ulong(1),
                                ctypes.byref(remote), ctypes.c_ulong(1),
                                ctypes.c_ulong(0))
    return n


def read_i32(pr, addr):
    try:
        return pr.i32(addr)
    except Exception:
        return None


def cmd_find():
    """连读 12 秒，找递减的字段。"""
    pid = find_pid()
    if pid is None:
        print("找不到游戏进程")
        return
    pr = _Proc(pid)
    g = pr.u32(GAPP_ADDR)
    print("  PID=%d  gApp=0x%X" % (pid, g))
    base = {}
    for off in CANDIDATES:
        v = read_i32(pr, g + off)
        if v is not None:
            base[off] = v
    print("  监视这些偏移，连读 12 秒…")
    dec = {off: [] for off in base}
    for k in range(12):
        time.sleep(1.0)
        for off in list(base):
            v = read_i32(pr, g + off)
            if v is None:
                continue
            if v < base[off]:
                dec[off].append((base[off], v))
                base[off] = v
    print()
    print("  ── 递减过的偏移 ──")
    for off, seq in dec.items():
        if seq:
            print("    gApp+0x%X: %s" % (off, seq[:8]))
    if not any(dec.values()):
        print("    （没有递减的 —— 可能不在对局中，或倒计时是浮点）")


def cmd_hold(secs=600):
    """锁住倒计时。"""
    pid = find_pid()
    if pid is None:
        print("找不到游戏进程")
        return
    pr = _Proc(pid)
    g = pr.u32(GAPP_ADDR)
    # 先挑一个当前值合理的偏移当锁定目标
    target = None
    for off in CANDIDATES:
        v = read_i32(pr, g + off)
        if v is not None and 10 <= v <= 120:
            target = (off, v)
            break
    if target is None:
        for off in CANDIDATES:
            v = read_i32(pr, g + off)
            if v is not None and v > 0:
                target = (off, v)
                break
    if target is None:
        print("  找不到合适的倒计时字段，先跑 find")
        return
    off, lock_val = target
    with open(STATE, "w") as f:
        f.write("%d %d" % (off, lock_val))
    print("  锁定 gApp+0x%X = %d，持续 %d 秒（Ctrl-C 停）" % (off, lock_val, secs))
    print("  现在去玩闪电模式，倒计时应该不再减少。")
    t0 = time.time()
    n_ok = 0
    try:
        while time.time() - t0 < secs:
            n = write_i32(pid, g + off, lock_val)
            if n == 4:
                n_ok += 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    print("  锁定结束（写了 %d 次）" % n_ok)
    try:
        os.remove(STATE)
    except Exception:
        pass


def cmd_release():
    try:
        os.remove(STATE)
    except Exception:
        pass
    print("  已清除锁定状态（若 hold 还在跑，请 Ctrl-C 结束它）")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "find"
    if a == "find":
        cmd_find()
    elif a == "hold":
        cmd_hold(int(sys.argv[2]) if len(sys.argv) > 2 else 600)
    elif a == "release":
        cmd_release()
    else:
        print(__doc__)
