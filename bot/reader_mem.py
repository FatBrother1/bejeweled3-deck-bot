#!/usr/bin/env python3
"""内存读取后端 —— 直接读游戏的 Board / Piece 对象，不走视觉识别。

实测依据（2026-09-24 Steam Deck 实机验证，逐格比对 64/64 命中）：
    gApp            0x008E1730
    Board           [gApp + 0xBE8]
    Piece 指针数组   [Board + 0xF8 + 4*x + 32*y]      x=列, y=行
    颜色            [piece + 0x220]      -1..6（红=0）
    状态位          [piece + 0x228]      火焰1 超立方2 闪电4 超新星5
    分数            [Board + 0xD24]
    关卡            [Board + 0xE0C]

性能：读一次完整棋盘 1.18 ms（视觉识别 54~77 ms）。

只读。仅用 process_vm_readv，不写内存、不调用游戏内部函数、不用 sudo。
"""
import ctypes
import os
import time

# ── 地址常量（Steam 版实测）──────────────────────────────────
GAPP_ADDR = 0x008E1730
OFF_BOARD = 0xBE8
OFF_PIECE_ARR = 0xF8
PIECE_STRIDE = 32          # 每行 32 字节 = 8 个 4 字节指针
OFF_COLOR = 0x220
OFF_FLAGS = 0x228
OFF_SCORE = 0xD24
OFF_LEVEL = 0xE0C
OFF_PROGRESS = 0xE00

# ── 颜色编码 → bot 字形（与 vision_np 的 KEYS 对齐）──────────
# 0=红 1=白 2=绿 3=黄 4=紫 5=橙 6=蓝，-1=未着色
COLOR2GLYPH = {-1: "?", 0: "R", 1: "W", 2: "G", 3: "Y", 4: "P", 5: "O", 6: "B"}

# 状态位（与报告 §4.2 一致）
FLAG_FLAME = 1
FLAG_HYPERCUBE = 2
FLAG_STAR = 4
FLAG_SUPERNOVA = 5
# ★ 时间宝石 / 计数宝石（闪电模式的核心机制）
#   实测（2026-09-25，闪电模式实机抓取）：
#     flags = 131072 (0x20000) 且 +0x244 的计数 = 5（画面上正是"+5"）
#   出现 8 次、计数全是 5，与画面完全吻合。
#   来源：bognarit80/Bejeweled3PlusExtender 的 sandboxfunctions.cpp 里
#     AddGemCounter() 判断 (gemPtr+552) & PieceFlag::COUNTER，
#     计数存在 gemPtr+580；注释写明 "Works on both Time and Counter gems"。
#     552 = 0x228、580 = 0x244，两边对得上。
FLAG_COUNTER = 131072
OFF_COUNTER = 0x244

# 超立方体没有固定颜色（color = -1），但状态位是 HYPERCUBE。
# 视觉路线把它识别成 "S"，这里保持一致，避免被当成未知格。
GLYPH_HYPERCUBE = "S"

# 颜色读不到但状态位有效的宝石：用原色 +0x21C 兜底（超立方体带原色）。
OFF_PRECOLOR = 0x21C

MAX_BAD = 3                # 与 vision_np.is_board_like 的 max_bad 保持一致

# ── libc ────────────────────────────────────────────────────
_libc = ctypes.CDLL("libc.so.6", use_errno=True)


class _IOV(ctypes.Structure):
    _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]


_libc.process_vm_readv.restype = ctypes.c_ssize_t


def find_pid(comm="Bejeweled3.exe"):
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open("/proc/%s/comm" % p).read().strip() == comm:
                    return int(p)
            except Exception:
                pass
    return None


class _Proc:
    """带复用缓冲的只读访问器。"""

    def __init__(self, pid):
        self.pid = pid
        self._buf = ctypes.create_string_buffer(4)
        self._local = _IOV(ctypes.cast(self._buf, ctypes.c_void_p), 4)

    def raw(self, addr):
        remote = _IOV(ctypes.c_void_p(addr), 4)
        n = _libc.process_vm_readv(self.pid, ctypes.byref(self._local), 1,
                                   ctypes.byref(remote), 1, 0)
        if n != 4:
            return None
        return self._buf.raw

    def u32(self, addr):
        d = self.raw(addr)
        return int.from_bytes(d, "little") if d else None

    def i32(self, addr):
        d = self.raw(addr)
        if d is None:
            return None
        v = int.from_bytes(d, "little")
        return v - 0x100000000 if v >= 0x80000000 else v


def _ptr_ok(p):
    return p is not None and 0x00400000 <= p < 0x80000000


def board_score(pid=None):
    """从 Board 对象读分数（固定链，重启游戏不变）。失败返回 None。"""
    try:
        pid = pid or find_pid()
        if pid is None:
            return None
        pr = _Proc(pid)
        gapp = pr.u32(GAPP_ADDR)
        if not _ptr_ok(gapp):
            return None
        board = pr.u32(gapp + OFF_BOARD)
        if not _ptr_ok(board):
            return None
        v = pr.i32(board + OFF_SCORE)
        if v is None or v < 0 or v > 100000000:
            return None
        return v
    except Exception:
        return None


def mem_available(verbose=False):
    """检查内存后端当前是否可用。

    返回 (ok: bool, reason: str)。

    这是给"自动降级"用的：游戏更新、换版本、或没在游戏里时，
    gApp 槽会读不到有效指针 —— 那时应当回退到视觉后端，而不是崩掉。
    """
    pid = find_pid()
    if pid is None:
        return False, "找不到 Bejeweled3.exe 进程"
    try:
        pr = _Proc(pid)
        gapp = pr.u32(GAPP_ADDR)
        if not _ptr_ok(gapp):
            return False, ("gApp 槽 0x%08X 无效（读到 %s）—— "
                           "游戏版本可能已更新，偏移失效"
                           % (GAPP_ADDR, ("0x%X" % gapp) if gapp is not None else "读取失败"))
        board = pr.u32(gapp + OFF_BOARD)
        if not _ptr_ok(board):
            # ★ 区分两种情况：
            #   ① 分数/关卡字段所在的对象不存在 → 通常是在主菜单，没进游戏
            #   ② gApp 本身读不到 → 多半是游戏版本变了、偏移失效
            #   两者对调用方的含义不同：①耐心等进游戏，②该退视觉。
            if board == 0:
                return False, ("不在游戏中（Board 指针为空）—— "
                               "可能停在主菜单，进游戏后即可用")
            return False, ("Board 指针 gApp+0x%X 无效（读到 0x%X）—— 偏移可能已变"
                           % (OFF_BOARD, board))
        # 抽查一格 Piece 是否可读
        piece = pr.u32(board + OFF_PIECE_ARR)
        if not _ptr_ok(piece):
            return False, "Piece 数组首元素无效 —— 可能不在棋盘界面"
        color = pr.i32(piece + OFF_COLOR)
        if color is None:
            return False, "Piece 颜色字段读不到"
        return True, "gApp=0x%08X Board=0x%08X" % (gapp, board)
    except Exception as e:
        return False, "检查异常: %s" % e


class MemReader:
    """与 FastReader 同接口，但棋盘来自内存。"""

    def __init__(self, still_ms=250.0, cap=None, downsample=4):
        self.pid = find_pid()
        if self.pid is None:
            raise RuntimeError("找不到 Bejeweled3.exe 进程")
        # ★ 混合模式：抓帧只用于「判静止」，棋盘仍从内存读。
        #   原因（2026-09-24 用户实测 + 我复现）：
        #     过场/换关动画约 8.45 秒，期间内存里的棋盘数据【完全冻结】，
        #     内存看数据稳定就以为能出手，实际游戏在播动画 ⇒ 交换必被拒。
        #     视觉因为看得见画面在动，天然会等。
        #   ⇒ 静止判定交给像素差，读棋盘交给内存，取两者之长。
        self.cap = cap
        self.ds = downsample
        self.prev = None
        self._bx0 = self._bx1 = self._by0 = self._by1 = None
        try:
            from vision_np import BOARD as _B
            self._bx0 = int(_B["x0"]) - 44
            self._bx1 = int(_B["x0"] + 7 * _B["pitch_x"]) + 44
            self._by0 = int(_B["y0"]) - 44
            self._by1 = int(_B["y0"] + 7 * _B["pitch_y"]) + 44
        except Exception:
            self.cap = None      # 拿不到标定就退回纯内存模式
        if self.cap is not None and self._bx1 is None:
            self.cap = None
        self.pr = _Proc(self.pid)
        self.gapp = self.pr.u32(GAPP_ADDR)
        if not _ptr_ok(self.gapp):
            raise RuntimeError("gApp 槽 0x%08X 无效（=0x%X）—— 游戏版本可能已更新，"
                               "偏移失效" % (GAPP_ADDR, self.gapp or 0))
        self.mod = self            # bot_v6 会调 rd.mod.fingerprint()
        self.still_ms = still_ms
        # ★ 最近一次读盘附带的额外信息（分数/关卡/特殊宝石/时间宝石）。
        #   调用方（bot）通过 rd.last_extra 取，不用改 wait_still_and_read 的
        #   返回签名 —— FastReader 也是 4 元组，保持两者接口一致更省事。
        self.last_extra = {}
        self.stats = {"frames": 0, "grabs": 0, "visions": 0,
                      "t_grab": 0.0, "t_diff": 0.0, "t_vision": 0.0,
                      "waits": 0, "t_wait": 0.0, "reads": 0}

    # ── 像素差（仅用于判静止；棋盘不走视觉）──────────────────
    def _pix_diff(self):
        """抓一帧算降采样像素差。返回 (frame, diff|None)。"""
        if self.cap is None:
            return None, None
        a = self.cap.get(timeout=0.5)
        if a is None:
            return None, None
        try:
            r = a[self._by0:self._by1:self.ds,
                  self._bx0:self._bx1:self.ds].astype("int16")
        except Exception:
            return a, None
        d = None
        if self.prev is not None and self.prev.shape == r.shape:
            import numpy as _np
            d = float(_np.abs(r - self.prev).mean())
        self.prev = r
        return a, d

    # ── 核心：读一次棋盘 ────────────────────────────────────
    def _read_grid(self):
        """返回 (grid|None, bad, extra)。extra = {score, level, flags}"""
        pr = self.pr
        board = pr.u32(self.gapp + OFF_BOARD)
        if not _ptr_ok(board):
            return None, 99, {}
        grid = []
        bad = 0
        flags = []
        timegems = []
        for i in range(8):                      # i = 行 → y
            row = []
            for j in range(8):                  # j = 列 → x
                piece = pr.u32(board + OFF_PIECE_ARR + 4 * j + PIECE_STRIDE * i)
                if not _ptr_ok(piece):
                    row.append("?")
                    bad += 1
                    continue
                c = pr.i32(piece + OFF_COLOR)
                f = pr.i32(piece + OFF_FLAGS)
                g = COLOR2GLYPH.get(c)
                if g is None or g == "?":
                    # ★ 颜色无效不等于未知格：
                    #   超立方体(状态位2) 本来就没有颜色，但它是可用的特殊宝石。
                    #   实测 (4,2) 颜色=-1 状态=2，若判 "?" 会让 solver 误判死局。
                    if f == FLAG_HYPERCUBE:
                        g = GLYPH_HYPERCUBE
                    else:
                        # 其它无色情形：用原色 +0x21C 兜底（超立方体带原色）
                        pc = pr.i32(piece + OFF_PRECOLOR)
                        g2 = COLOR2GLYPH.get(pc)
                        if g2 and g2 != "?":
                            g = g2
                        else:
                            g = "?"
                row.append(g)
                if g == "?":
                    bad += 1
                if f:
                    flags.append((i, j, f))
                # ★ 时间宝石（闪电模式）：记下格子与剩余计数，
                #   供 bot 优先去消它 —— 不然时间不够，必死。
                if f is not None and (f & FLAG_COUNTER):
                    timegems.append((i, j, pr.i32(piece + OFF_COUNTER)))
            grid.append(row)
        extra = {"score": pr.i32(board + OFF_SCORE),
                 "level": pr.i32(board + OFF_LEVEL),
                 "flags": flags,
                 "timegems": timegems,          # [(行, 列, 计数), ...]
                 "board": board}
        return grid, bad, extra

    # ── 接口兼容 ────────────────────────────────────────────
    @staticmethod
    def fingerprint(g):
        return tuple("".join(r) for r in g)

    @staticmethod
    def is_board_like(conf, max_bad=MAX_BAD):
        if isinstance(conf, int):
            return conf <= max_bad, conf
        return True, 0

    def read_now(self):
        """立即读一次（不等稳定）。返回 (grid|None, bad)"""
        t0 = time.perf_counter()
        g, bad, extra = self._read_grid()
        self.last_extra = extra or {}
        self.stats["t_vision"] += time.perf_counter() - t0
        self.stats["visions"] += 1
        self.stats["reads"] += 1
        if g is None or bad > MAX_BAD:
            return None, bad
        return g, bad

    def wait_still_and_read(self, thr=2.0, need=4, max_wait=12.0,
                            min_still_ms=None, require_motion=False,
                            motion_timeout=3.0, min_score_delta=0,
                            min_anim_ms=0):
        """等画面静止 → 从内存读一次棋盘。返回 (grid|None, bad, ms_waited, ms_read)

        ★ 混合设计（2026-09-24 实测定型，这是本后端最关键的一条）★

        为什么静止判定必须用像素差、而不是内存稳定性：

          过场 / 换关动画实测约 **8.45 秒**（用户秒表实测）。
          这段时间里，内存中的棋盘数据是**完全冻结**的 ——
          内存每 5ms 读一次都稳定不变，于是被误判成"画面静止、可以出手"，
          但游戏其实在播动画，交换必然被拒。

          实测症状：同一个走法前一次 实际=0 被拉黑、紧接着重试同一走法就成功；
          100 步里有效率掉到 90%，而视觉后端有 99%。

          视觉路线因为看得见画面在动，天然会等 —— 这是它唯一的、但决定性的优势。
          ⇒ 于是：**静止判定交给像素差（看得见过场），棋盘数据交给内存（快且准）**。

        纯内存回退：cap 不可用时（无标定 / 非游戏窗口），退化为只用内存稳定性判断，
        此时对过场动画缺乏抵抗力，属已知限制。
        """
        if min_still_ms is None:
            min_still_ms = self.still_ms

        # ── 分支 A：有抓帧能力 → 像素差判静止 ──
        if self.cap is not None:
            t0 = time.time()
            q = 0
            quiet_since = None
            motion = False
            while time.time() - t0 < max_wait:
                a, d = self._pix_diff()
                if a is None:
                    time.sleep(0.002)
                    continue
                moving = (d is not None and d >= thr)
                if moving:
                    motion = True
                    q = 0
                    quiet_since = None
                else:
                    q += 1
                    if quiet_since is None:
                        quiet_since = time.time()
                still_ok = (q >= need and quiet_since is not None and
                            (time.time() - quiet_since) * 1000 >= min_still_ms)
                if require_motion:
                    if motion and still_ok:
                        break
                else:
                    if still_ok:
                        break
            waited = (time.time() - t0) * 1000
            # 画面静了 → 从内存读棋盘
            tv = time.perf_counter()
            g, bad, extra = self._read_grid()
            self.last_extra = extra or {}
            rms = (time.perf_counter() - tv) * 1000
            self.stats["waits"] += 1
            self.stats["t_wait"] += waited
            self.stats["visions"] += 1
            self.stats["t_vision"] += rms
            self.stats["reads"] += 1
            if g is None or bad > MAX_BAD:
                return None, bad, waited, rms
            return g, bad, waited, rms

        # ── 分支 B：无抓帧 → 纯内存稳定性（已知对过场动画无抵抗力）──
        t0 = time.time()
        last_fp = None
        last = None
        stable_since = None
        motion = False
        first_score = None
        last_score = None
        POLL = 0.005
        while time.time() - t0 < max_wait:
            tick = time.time()
            g, bad, extra = self._read_grid()
            self.last_extra = extra or {}
            self.stats["reads"] += 1
            if g is None:
                time.sleep(POLL)
                continue
            fp = self.fingerprint(g)
            sc = extra.get("score")
            if first_score is None:
                first_score = sc
            score_moved = (sc is not None and last_score is not None and
                           abs(sc - last_score) >= max(1, min_score_delta))
            last_score = sc
            fp_moved = (last_fp is not None and fp != last_fp)
            if last_fp is None:
                stable_since = tick
            elif fp_moved or score_moved:
                if not motion:
                    motion = True
                stable_since = None
            elif stable_since is None:
                stable_since = tick
            last_fp = fp
            last = (g, bad)
            still_ok = (stable_since is not None and
                        (tick - stable_since) * 1000 >= min_still_ms)
            if require_motion:
                if motion and still_ok:
                    break
            else:
                if still_ok:
                    break
            spent = time.time() - tick
            if spent < POLL:
                time.sleep(POLL - spent)
        waited = (time.time() - t0) * 1000
        if waited <= max_wait * 1000 + 500:
            self.stats["waits"] += 1
            self.stats["t_wait"] += waited
        if last is None:
            return None, 99, waited, 0.0
        g, bad = last
        if bad > MAX_BAD:
            return None, bad, waited, 0.0
        return g, bad, waited, 0.0

    def read_now(self):
        """立即读一次（不等稳定）。返回 (grid|None, bad)"""
        t0 = time.perf_counter()
        g, bad, extra = self._read_grid()
        self.last_extra = extra or {}
        self.stats["t_vision"] += time.perf_counter() - t0
        self.stats["visions"] += 1
        self.stats["reads"] += 1
        if g is None or bad > MAX_BAD:
            return None, bad
        return g, bad

    def wait_still_and_read(self, thr=None, need=None, max_wait=4.0,
                            min_still_ms=None, require_motion=False,
                            motion_timeout=3.0, min_score_delta=0,
                            min_anim_ms=520.0):
        """轮询内存直到棋盘稳定 → 返回 (grid|None, bad, ms_waited, ms_read)

        require_motion=True 时要求先见到「变化」再见到「稳定」。

        关键教训（2026-09-24 实测）：
          游戏消除动画期间，**棋盘数据可能完全不变**（只有结算那一刻才变）。
          只看棋盘指纹会误判 —— 要么等到 max_wait 超时（实测 4005ms），
          要么在动画中途判定"静止"、拿到尚未结算的旧棋盘 ⇒ changed=False。
          ⇒ 因此把**分数变化**也当作运动信号：分数一动就说明确实有东西发生了。
        """
        if min_still_ms is None:
            min_still_ms = self.still_ms
        t0 = time.time()
        # ★ 核心教训（2026-09-24 实测，最有价值的一条）：
        #   内存里的棋盘数据【可能在消除动画播完之前就更新好了】。
        #   视觉能看到像素在动，所以天然会等；内存看到数据稳定就以为可以出手，
        #   结果游戏还没准备好接受输入 ⇒ 交换被拒。
        #   实测症状：同一个走法前一次被拒(实际=0)、紧接着重试同一走法就成功。
        #   ⇒ 因此 require_motion 时先硬等一个"动画时间"，再去轮询稳定性。
        #     游戏消除动画实测中位 535ms，留足余量取 min_anim_ms。
        t0 = time.time()
        last_fp = None
        last = None
        stable_since = None
        motion = False
        first_score = None
        last_score = None
        motion_deadline = t0 + motion_timeout
        POLL = 0.005
        while time.time() - t0 < max_wait:
            tick = time.time()
            g, bad, extra = self._read_grid()
            # ★ 2026-09-25 修复：本方法（生效的最后一个同名定义）此前从不写
            #   last_extra ⇒ bot 永远拿不到 timegems，加分宝石优先完全失效。
            self.last_extra = extra or {}
            self.stats["reads"] += 1
            if g is None:
                time.sleep(POLL)
                continue
            fp = self.fingerprint(g)
            sc = extra.get("score")
            if first_score is None:
                first_score = sc
            # 运动信号 = 棋盘指纹变了 OR 分数变了
            score_moved = (sc is not None and last_score is not None
                           and abs(sc - last_score) >= max(1, min_score_delta))
            last_score = sc
            fp_moved = (last_fp is not None and fp != last_fp)
            if last_fp is None:
                stable_since = tick
            elif fp_moved or score_moved:
                if not motion:
                    motion = True
                motion_deadline = tick + motion_timeout
                stable_since = None
            elif stable_since is None:
                stable_since = tick
            last_fp = fp
            last = (g, bad)
            still_ok = (stable_since is not None and
                        (tick - stable_since) * 1000 >= min_still_ms)
            if require_motion:
                # 内存后端的实测教训（2026-09-24）：
                #   连续 3 步无效，等待时间都恰好 1200ms 左右，
                #   说明撞上了 motion_timeout 提前退出。
                #   内存轮询比动画快，且游戏动画期间棋盘数据可能不变
                #   （只有结算瞬间才变），于是"没见到运动"被误判为
                #   "动画没开始"而提前放弃，返回动画未演完的棋盘。
                #   => 未见运动时不提前退出，交给 max_wait 兜底。
                if motion and still_ok:
                    break
            else:
                if still_ok:
                    break
            # 限速到 200Hz
            spent = time.time() - tick
            if spent < POLL:
                time.sleep(POLL - spent)
        waited = (time.time() - t0) * 1000
        # 防脏数据：单次等待超过 max_wait 太多说明有异常，不计入统计
        if waited <= max_wait * 1000 + 500:
            self.stats["waits"] += 1
            self.stats["t_wait"] += waited
        if last is None:
            return None, 99, waited, 0.0
        # 注：Board 为空（在菜单里）时不特殊处理，由上层 miss 计数决定下一步。
        g, bad = last
        if bad > MAX_BAD:
            return None, bad, waited, 0.0
        return g, bad, waited, 0.0


if __name__ == "__main__":
    # 自检：读一次棋盘并打印
    import sys
    r = MemReader()
    print("PID=%d gApp=0x%08X" % (r.pid, r.gapp))
    t0 = time.perf_counter()
    N = 50
    for _ in range(N):
        g, bad, extra = r._read_grid()
    dt = (time.perf_counter() - t0) / N * 1000
    print("读一次 %.2f ms，坏格 %d" % (dt, bad))
    print("分数=%s 关卡=%s" % (extra.get("score"), extra.get("level")))
    for row in g:
        print("  " + " ".join(row))
    if extra.get("flags"):
        print("特殊宝石:", extra["flags"])
