#!/usr/bin/env python3
"""fdump.py —— SIGSTOP 冻结法定位倒计时（真正意义上的暂停）。

思路：闪电局只有 60 秒且无法暂停，但我们可以用 SIGSTOP 把整个游戏进程
冻住 —— 冻结期间画面定格、内存静止，此时「画面显示的秒数」与「内存里的
值」严格同时刻。抓一张倒计时框 + 转储全内存中所有落在 [1,61] 的整数与
浮点，解冻；隔几秒再来一次。两次快照求交，倒计时主控必在其中。

  python3 fdump.py run [间隔秒]    # 冻结→抓框→转储→解冻，连做两次
  python3 fdump.py inter N1 N2     # 用两次转储 + 画面读数求交
  python3 fdump.py freeze|thaw     # 手动冻结 / 解冻
"""
import ctypes, os, re, signal, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid

CHUNK = 512 * 1024
W, H = 1280, 800


def rd(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    lo = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    r = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)
    if n == size:
        return buf.raw
    return buf.raw[:n] if n and n > 0 else None


def regions(pid):
    out = []
    for l in open("/proc/%d/maps" % pid):
        m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s*\S*\s*(.*)", l)
        if not m:
            continue
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        permission, path = m.group(3), m.group(4).strip()
        if "w" not in permission or hi <= lo or "/dev/" in path or "memfd" in path:
            continue
        out.append((lo, hi))
    return out


def crop(path):
    """抓右上倒计时框（整条顶栏，2 倍放大）。"""
    subprocess.run(
        ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
         "num-buffers=1", "!", "videoconvert", "!", "videocrop",
         "left=440", "right=%d" % (W - 1160), "top=5", "bottom=%d" % (H - 100),
         "!", "videoscale", "!", "video/x-raw,width=1440", "!",
         "pngenc", "!", "filesink", "location=" + path], capture_output=True)
    return path


def dump(pid, tag, lo=1, hi=61):
    """转储所有 i4∈[lo,hi] 与 f4∈(lo-0.5,hi) 的槽位。"""
    A, V, K = [], [], []
    nreg = 0
    for rlo, rhi in regions(pid):
        n = rhi - rlo
        off = 0
        while off < n:
            sz = min(CHUNK, n - off)
            d = rd(pid, rlo + off, sz)
            if d is None or len(d) != sz:
                off += sz
                continue
            cnt = len(d) // 4
            arr = np.frombuffer(d[:cnt * 4], "<i4")
            ii = np.nonzero((arr >= lo) & (arr <= hi))[0]
            if len(ii):
                A.append(rlo + off + ii.astype(np.uint64) * 4)
                V.append(arr[ii].astype(np.float64))
                K.append(np.zeros(len(ii), np.uint8))
            fa = arr.view("<f4")
            mf = np.isfinite(fa) & (fa > lo - 0.5) & (fa < hi)
            fi = np.nonzero(mf)[0]
            if len(fi):
                A.append(rlo + off + fi.astype(np.uint64) * 4)
                V.append(fa[fi].astype(np.float64))
                K.append(np.ones(len(fi), np.uint8))
            off += sz
        nreg += 1
    if not A:
        print("  没有命中")
        return None
    A = np.concatenate(A)
    V = np.concatenate(V)
    K = np.concatenate(K)
    path = "/home/deck/fdump_%s.npz" % tag
    np.savez(path, A=A, V=V, K=K)
    print("  [%s] 命中 %d 个（i4=%d f4=%d），%d 个区 → %s"
          % (tag, len(A), int((K == 0).sum()), int((K == 1).sum()), nreg, path))
    return path


def cycle(pid, tag):
    os.kill(pid, signal.SIGSTOP)
    t0 = time.time()
    try:
        time.sleep(0.25)
        p = crop("/tmp/tlock/f_%s.png" % tag)
        tf = time.time()
        dump(pid, tag)
        td = time.time()
    finally:
        os.kill(pid, signal.SIGCONT)
    print("  [%s] 冻结 %.2fs（抓帧到 %.2fs，转储到 %.2fs），已解冻"
          % (tag, time.time() - t0, tf - t0, td - t0))


def inter(n1, n2):
    a = np.load("/home/deck/fdump_1.npz")
    b = np.load("/home/deck/fdump_2.npz")
    d1 = {int(x): (float(v), int(k)) for x, v, k in zip(a["A"], a["V"], a["K"])}
    d2 = {int(x): (float(v), int(k)) for x, v, k in zip(b["A"], b["V"], b["K"])}
    d = n1 - n2
    print("画面 %d → %d，落差 %d；两次快照各 %d / %d 个槽" % (n1, n2, d, len(d1), len(d2)))
    hit = []
    for x, (v1, k1) in d1.items():
        if x not in d2:
            continue
        v2, k2 = d2[x]
        if (v1 - v2) < (d - 1.5) or (v1 - v2) > (d + 1.5):
            continue
        if k1 != k2:
            continue
        err = abs(v2 - n2)
        if err > 2.0:
            continue
        hit.append((err, x, k1, v1, v2))
    hit.sort()
    print("交集候选 %d 个：" % len(hit))
    for err, x, k, v1, v2 in hit[:80]:
        print("    0x%-10X [%s]  %10.3f → %10.3f   偏差 %.2f"
              % (x, "i4" if k == 0 else "f4", v1, v2, err))
    np.savez("/home/deck/fdump_hit.npz", A=np.array([h[1] for h in hit], dtype=np.uint64))
    return [h[1] for h in hit]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    if cmd == "freeze":
        os.kill(pid, signal.SIGSTOP)
        print("已冻结 PID=%d" % pid)
    elif cmd == "thaw":
        os.kill(pid, signal.SIGCONT)
        print("已解冻 PID=%d" % pid)
    elif cmd == "run":
        gap = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
        print("PID=%d 开始冻结法采样" % pid)
        cycle(pid, "1")
        print("  等 %.1fs 让时钟走…" % gap)
        time.sleep(gap)
        cycle(pid, "2")
        print("完成。请读 /tmp/tlock/f_1.png 与 f_2.png 上的秒数，再跑 inter")
    elif cmd == "inter":
        inter(int(sys.argv[2]), int(sys.argv[3]))


if __name__ == "__main__":
    main()
