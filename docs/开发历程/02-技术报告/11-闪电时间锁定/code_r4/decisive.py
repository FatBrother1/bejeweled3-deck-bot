#!/usr/bin/env python3
"""decisive.py —— 决定性实验：判定 0x109CBEC 是「母本」还是「镜像」。

原理：
  · 若是母本：暂停态写入 300（=5:00），恢复运行后画面应显示 5:00 左右并继续从 300 递减。
  · 若是镜像：每帧被真实母本覆写，恢复后画面立刻回到真实剩余秒数（≈写入前的值）。

流程：确保暂停 → 记录写前值 → 写 300 → 恢复运行 → 立刻抓帧 → 再暂停 → 回读
"""
import sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid
import tb

ADDR = 0x109CBEC
NEW = 300


def rv(pid, addr):
    d = tb.rd(pid, addr, 4)
    return int(np.frombuffer(d, "<i4")[0]) if d and len(d) == 4 else None


def main():
    pid = find_pid()
    if pid is None:
        print("❌ 游戏没在跑")
        return
    b, cs, s = tb.clock(pid)
    print("Board=%s cs=%s s=%s" % (hex(b) if b else None, cs, s))

    if not tb.ensure_paused(pid):
        print("❌ 无法暂停")
        return

    v0 = rv(pid, ADDR)
    print("写前 0x%X = %s" % (ADDR, v0))
    tb.shot("/home/deck/tb/dec_before.png")
    tb.wv(pid, ADDR, "<i4", NEW)
    time.sleep(0.3)
    v1 = rv(pid, ADDR)
    print("写入 %d 后（仍暂停）回读 = %s" % (NEW, v1))

    print("→ 恢复运行")
    tb.ensure_running(pid)
    time.sleep(0.7)
    tb.shot("/home/deck/tb/dec_after1.png")
    v2 = rv(pid, ADDR)
    print("恢复 0.7s 后 0x%X = %s" % (ADDR, v2))
    time.sleep(1.6)
    tb.shot("/home/deck/tb/dec_after2.png")
    v3 = rv(pid, ADDR)
    print("恢复 2.3s 后 0x%X = %s" % (ADDR, v3))

    print("\n判定：")
    if v2 is not None and abs(v2 - NEW) < 5:
        print("  ★★ 0x%X 是母本（写入被保持）—— 可以锁时间！" % ADDR)
    elif v0 is not None and v2 is not None and abs(v2 - v0) < 6:
        print("  ✗ 0x%X 是镜像（0.7s 内被游戏覆写回 %s）" % (ADDR, v2))
    else:
        print("  ? 结果不明确：写前=%s 写后=%s 恢复后=%s" % (v0, v1, v2))
    print("帧：/home/deck/tb/dec_before.png, dec_after1.png, dec_after2.png")


if __name__ == "__main__":
    main()
