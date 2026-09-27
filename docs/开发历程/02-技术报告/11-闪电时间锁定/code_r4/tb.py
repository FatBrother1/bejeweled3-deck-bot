#!/usr/bin/env python3
"""tb.py —— 闪电倒计时定位 最终版（Time-lock Bot）。

三次事故换来的三条纪律，全部内置：
  ① 内存纪律：分块文件流，峰值 < 20MB；候选列表上限 20 万条，超了立刻截断。
  ② Δ 纪律：Δcs 必须 > 0，否则立即报错退出 —— 绝不用 Δ≈0 去比较
     （否则「差值≈0」退化成匹配全部未变化槽，3 亿条候选 → earlyoom 杀进程）。
  ③ 自愈纪律：每次点击后**读游戏时钟验证状态**，不生效就重试；不假设点击成功。

核心机制（本轮最大发现）：
  闪电局中点左下「菜单」→ 弹出【选项】覆盖层，**游戏逻辑完全冻结**
  （实测 Board+0x38 厘秒三次读数恒为 6761），但进程仍在运行，
  可自由读写内存。这就是上一轮「用户暂停报数」法的机制，现已全自动。

Δt 来源：游戏自己的时钟 Board+0x38（厘秒），精度 10ms，不依赖读画面。

用法：
  python3 tb.py status              # 报告当前状态（是否在局中/是否暂停）
  python3 tb.py probe N1 N2 N3      # 三次暂停快照 + 交叉验证（主命令）
  python3 tb.py pin 0xADDR i4 +300 12  # 钉住实验
"""
import ctypes, json, os, re, subprocess, sys, time
sys.path.insert(0, "/home/deck")
import numpy as np
from reader_mem import _IOV, _libc, find_pid, GAPP_ADDR, OFF_BOARD

CHUNK = 256 * 1024
SNAP_DIR = "/home/deck/tb"
W, H = 1280, 800
MENU = (215, 730)
BACK = (882, 597)
AGAIN = (628, 739)
TREE_LIGHT = (300, 590)
TITLE_START = (640, 430)
MAXCAND = 200000
DT = {"i4": "<i4", "u4": "<u4", "f4": "<f4", "f8": "<f8"}
_libc.process_vm_writev.restype = ctypes.c_ssize_t
WB = ctypes.create_string_buffer(8)


def rss_mb():
    try:
        for l in open("/proc/self/status"):
            if l.startswith("VmRSS:"):
                return int(l.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def rd(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    lo = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    r = _IOV(ctypes.c_void_p(addr), size)
    n = _libc.process_vm_readv(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0)
    if n == size:
        return buf.raw
    return buf.raw[:n] if n and n > 0 else None


def ru32(pid, addr):
    d = rd(pid, addr, 4)
    return int(np.frombuffer(d, "<u4")[0]) if d and len(d) == 4 else None


def wv(pid, addr, dt, val):
    step = 8 if dt == "<f8" else 4
    WB.raw = np.array(val, dtype=dt).tobytes()
    lo = _IOV(ctypes.cast(WB, ctypes.c_void_p), step)
    r = _IOV(ctypes.c_void_p(addr), step)
    return _libc.process_vm_writev(pid, ctypes.byref(lo), 1, ctypes.byref(r), 1, 0) == step


def board_of(pid):
    g = ru32(pid, GAPP_ADDR)
    if not g:
        return None
    return ru32(pid, g + OFF_BOARD)


def clock(pid):
    b = board_of(pid)
    if not b:
        return None, None, None
    return b, ru32(pid, b + 0x38), ru32(pid, b + 0xC84)


def regions(pid):
    out = []
    for l in open("/proc/%d/maps" % pid):
        m = re.match(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s*\S*\s*(.*)", l)
        if not m:
            continue
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        perm, path = m.group(3), m.group(4).strip()
        if "w" not in perm or hi <= lo or "/dev/" in path or "memfd" in path:
            continue
        out.append((lo, hi))
    return out


def click(pt):
    from vmouse2 import VMouse2
    m = VMouse2()
    m.click(pt[0], pt[1])
    m.close()


def shot(path, crop=False):
    cmd = ["timeout", "20", "gst-launch-1.0", "-q", "pipewiresrc", "path=93",
           "num-buffers=1", "!", "videoconvert", "!"]
    if crop:
        cmd += ["videocrop", "left=980", "right=%d" % (W - 1170),
                "top=0", "bottom=%d" % (H - 120), "!",
                "videoscale", "!", "video/x-raw,width=1180", "!"]
    cmd += ["pngenc", "!", "filesink", "location=" + path]
    subprocess.run(cmd, capture_output=True)


# ---------------- 自愈状态机 ----------------

def is_paused(pid):
    """连续三次读时钟，全同 = 已冻结。"""
    _, c1, _ = clock(pid)
    if c1 is None:
        return None
    time.sleep(0.35)
    _, c2, _ = clock(pid)
    time.sleep(0.35)
    _, c3, _ = clock(pid)
    if c2 is None or c3 is None:
        return None
    return c1 == c2 == c3


def ensure_paused(pid, tries=4):
    """点「菜单」直到时钟真的冻结。返回 True/False。"""
    for i in range(tries):
        if is_paused(pid) is True:
            return True
        click(MENU)
        time.sleep(1.0)
        st = is_paused(pid)
        if st is True:
            return True
        if st is None:
            print("     ⚠️ 时钟读不到（可能不在局中）")
            return False
    print("     ⚠️ 尝试 %d 次仍未暂停" % tries)
    return False


def ensure_running(pid, tries=4):
    """点「返回」直到时钟真的在走。"""
    for i in range(tries):
        st = is_paused(pid)
        if st is False:
            return True
        click(BACK)
        time.sleep(1.0)
        st = is_paused(pid)
        if st is False:
            return True
    print("     ⚠️ 尝试 %d 次仍未恢复运行" % tries)
    return False


# ---------------- 快照 / 比较 ----------------

def snap(tag):
    pid = find_pid()
    if pid is None:
        raise RuntimeError("游戏没在跑")
    if not ensure_paused(pid):
        raise RuntimeError("无法进入暂停态，中止（不冒险拍快照）")
    os.makedirs(SNAP_DIR, exist_ok=True)
    regs = regions(pid)
    b, cs, s = clock(pid)
    binp = "%s/%s.bin" % (SNAP_DIR, tag)
    idx, pos = [], 0
    with open(binp, "wb") as f:
        for lo, hi in regs:
            off, n, wrote, ok = 0, hi - lo, 0, True
            while off < n:
                sz = min(CHUNK, n - off)
                d = rd(pid, lo + off, sz)
                if d is None or len(d) != sz:
                    ok = False
                    break
                f.write(d)
                wrote += sz
                off += sz
            idx.append([lo, pos, wrote if ok else -1])
            if ok:
                pos += wrote
    json.dump({"regions": idx, "cs": cs, "s": s, "board": b},
              open("%s/%s.json" % (SNAP_DIR, tag), "w"))
    print("  [%s] Board=0x%X  cs=%s s=%s  快照 %.0fMB"
          % (tag, b or 0, cs, s, os.path.getsize(binp) / 1048576.0))
    return cs


def diff(tagA, tagB):
    ma = json.load(open("%s/%s.json" % (SNAP_DIR, tagA)))
    mb = json.load(open("%s/%s.json" % (SNAP_DIR, tagB)))
    if ma["cs"] is None or mb["cs"] is None:
        raise RuntimeError("时钟缺失")
    dcs = mb["cs"] - ma["cs"]
    # ★ 纪律②：Δ 必须为正且合理
    if dcs <= 0:
        raise RuntimeError("Δcs=%d ≤ 0（两次快照间游戏未真正运行）—— 拒绝比较。"
                           "请检查「返回」是否生效。" % dcs)
    if dcs > 3000:
        raise RuntimeError("Δcs=%d 过大（>30s），可能跨局" % dcs)
    pid = find_pid()
    fa = open("%s/%s.bin" % (SNAP_DIR, tagA), "rb")
    cand = []
    truncated = False
    for (lo_a, pos_a, n_a), (lo_b, _, n_b) in zip(ma["regions"], mb["regions"]):
        if n_a <= 0 or n_b <= 0 or lo_a != lo_b or n_a != n_b:
            continue
        fa.seek(pos_a)
        off = 0
        while off < n_a:
            sz = min(CHUNK, n_a - off)
            db = rd(pid, lo_a + off, sz)
            if db is None or len(db) != sz:
                off += sz
                continue
            da = fa.read(sz)
            if len(da) != sz:
                break
            cnt = sz // 4
            va = np.frombuffer(da[:cnt * 4], "<i4")
            vb = np.frombuffer(db[:cnt * 4], "<i4")
            fva = va.view("<f4").astype(np.float32, copy=False)
            fvb = vb.view("<f4").astype(np.float32, copy=False)
            fin = np.isfinite(fva) & np.isfinite(fvb)
            dfa = fva.astype(np.float64) - fvb.astype(np.float64)
            tsec = dcs / 100.0
            # float 秒刻度
            m = fin & (np.abs(dfa - tsec) <= 0.30) & (fva > 0) & (fva < 400)
            if m.any():
                for k in np.nonzero(m)[0]:
                    cand.append((lo_a + off + int(k) * 4, float(fva[k]), float(fvb[k]), "f4_s"))
            # float 十分秒
            m = fin & (np.abs(dfa - dcs / 10.0) <= 3.0) & (fva > 0) & (fva < 4000)
            if m.any():
                for k in np.nonzero(m)[0]:
                    cand.append((lo_a + off + int(k) * 4, float(fva[k]), float(fvb[k]), "f4_t"))
            # int 秒
            ia = va.astype(np.int64)
            ib = vb.astype(np.int64)
            di = ia - ib
            m = (np.abs(di - tsec) <= 1.5) & (ia > 0) & (ia < 400)
            if m.any():
                for k in np.nonzero(m)[0]:
                    cand.append((lo_a + off + int(k) * 4, float(ia[k]), float(ib[k]), "i4_s"))
            # int 十分秒
            m = (np.abs(di - dcs / 10.0) <= 1.5) & (ia > 0) & (ia < 4000)
            if m.any():
                for k in np.nonzero(m)[0]:
                    cand.append((lo_a + off + int(k) * 4, float(ia[k]), float(ib[k]), "i4_t"))
            if len(cand) > MAXCAND:
                truncated = True
                break
            off += sz
        if truncated:
            break
    fa.close()
    if truncated:
        print("  ⚠️ 候选超过 %d，已截断（判据可能过松）" % MAXCAND)
    print("  %s→%s：Δcs=%d (%.2fs)  候选 %d / RSS %.0fMB"
          % (tagA, tagB, dcs, dcs / 100.0, len(cand), rss_mb()))
    return dcs, cand


def cmd_status():
    pid = find_pid()
    if pid is None:
        print("游戏未运行")
        return
    b, cs, s = clock(pid)
    st = is_paused(pid)
    print("PID=%d Board=%s cs=%s s=%s 状态=%s"
          % (pid, hex(b) if b else None, cs, s,
             "暂停中" if st else ("运行中" if st is False else "未知(不在局中)")))


def cmd_probe(gaps):
    pid = find_pid()
    if pid is None:
        print("  ❌ 游戏没在跑")
        return
    if not ensure_paused(pid):
        print("  ❌ 无法暂停，中止")
        return
    print("[A] 暂停态快照")
    a = snap("A")
    res = []
    for i, g in enumerate(gaps):
        tag_next = chr(ord("B") + i)
        print("[%s] 返回运行 %.1fs" % (tag_next, g))
        # 点返回 → 等 → 再暂停
        ensure_running(pid)
        time.sleep(g)
        if not ensure_paused(pid):
            print("  ❌ 第 %s 次暂停失败，中止" % tag_next)
            return
        c = snap(tag_next)
        # 立即算这一段的 Δ，早发现问题
        prev = chr(ord(tag_next) - 1)
        if c is not None and json.load(open("%s/%s.json" % (SNAP_DIR, prev)))["cs"] is not None:
            pass
    tags = ["A"] + [chr(ord("B") + i) for i in range(len(gaps))]
    for i in range(len(tags) - 1):
        print("\n--- 比较 %s → %s ---" % (tags[i], tags[i + 1]))
        try:
            dcs, cand = diff(tags[i], tags[i + 1])
            res.append((tags[i], tags[i + 1], dcs, cand))
        except RuntimeError as e:
            print("  ❌ %s" % e)
    if len(res) < 2:
        print("\n有效比较不足 2 组，无法交叉验证")
        if res:
            print("\n单组候选（前 60）：")
            for a, va, vb, ax in sorted(res[0][3], key=lambda t: -abs(t[1]))[:60]:
                print("   0x%-11X [%-5s] %12.4f → %12.4f" % (a, ax, va, vb))
        return
    s1 = {(a, ax): (va, vb) for a, va, vb, ax in res[0][3]}
    s2 = {(a, ax): (va, vb) for a, va, vb, ax in res[1][3]}
    both = set(s1) & set(s2)
    print("\n=== 交叉验证：组1 Δ=%d cs 候选%d；组2 Δ=%d cs 候选%d；交集 %d ==="
          % (res[0][2], len(s1), res[1][2], len(s2), len(both)))
    for a, ax in sorted(both):
        print("   ★ 0x%-11X [%-5s] A=%.3f B=%.3f C=%.3f"
              % (a, ax, s1[(a, ax)][0], s1[(a, ax)][1], s2[(a, ax)][0]))
    json.dump([{"addr": "0x%X" % a, "axis": ax} for a, ax in sorted(both)],
              open(SNAP_DIR + "/hit.json", "w"), indent=1)
    if not both:
        print("   （交集为空）")


def cmd_pin(addr, kind, delta, hold):
    pid = find_pid()
    dt = DT[kind]
    step = 8 if dt == "<f8" else 4
    d = rd(pid, addr, step)
    if d is None:
        print("读不到")
        return
    v0 = float(np.frombuffer(d, dt)[0])
    print("0x%X [%s] 当前=%.3f → 写 %.3f" % (addr, kind, v0, v0 + delta))
    shot("/home/deck/tb/pin_before.png", crop=True)
    wv(pid, addr, dt, v0 + delta)
    t0 = time.time()
    n = 0
    while time.time() - t0 < hold:
        el = time.time() - t0
        if abs(el - 1.0) < 0.05 or abs(el - 3.0) < 0.05 or abs(el - 6.0) < 0.05:
            shot("/home/deck/tb/pin_%d.png" % int(el), crop=True)
        wv(pid, addr, dt, v0 + delta)
        n += 1
        time.sleep(0.03)
    shot("/home/deck/tb/pin_end.png", crop=True)
    d = rd(pid, addr, step)
    print("保持 %.0fs（写 %d 次），终值=%.3f"
          % (hold, n, float(np.frombuffer(d, dt)[0]) if d else -1))


if __name__ == "__main__":
    os.makedirs(SNAP_DIR, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        cmd_status()
    elif cmd == "probe":
        cmd_probe([float(x) for x in sys.argv[2:]] or [2.0, 3.0])
    elif cmd == "pin":
        cmd_pin(int(sys.argv[2], 16), sys.argv[3], float(sys.argv[4]),
                float(sys.argv[5]) if len(sys.argv) > 5 else 12.0)
    else:
        print(__doc__)
