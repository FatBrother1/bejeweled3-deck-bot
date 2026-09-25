#!/usr/bin/env python3
"""Bejeweled 3 bot v6 —— 回到经过验证的 VMouse2（相对+归零），专注速度。

★ 实测教训（本轮最重要）
  VMouseAbs（EV_ABS 绝对定位）在本 gamescope 环境**不生效**：
    请求 (4,2)<->(4,3)，游戏收到点击并高亮，但**交换不被接受**，棋盘不变。
  而 VMouse2（EV_REL 相对 + 撞角归零）**完全正常**：
    旧 bot_pw 同场景 10/10 成功、棋盘真实变化。
  ⇒ **不要用绝对定位**，用 VMouse2。

★ 本版目标：在"每帧识别"这个真瓶颈已被解耦的前提下，测出诚实速度。
"""
import argparse, json, os, sys, time, ctypes, struct, subprocess
import numpy as np
sys.path.insert(0, "/home/deck")
from capture_pw import PwCapture
from reader_fast import FastReader
from vmouse2 import VMouse2
from vision_np import BOARD
import solver_pro

SCORE_ADDRS = [0x0a1de408, 0x2a542394, 0x2a5423d4]

# ── 像素几何（棋盘格子画在屏幕上的哪儿）────────────────────────
# ★ 不同游戏模式的棋盘位置不一样（2026-09-25 实测，1280x800）：
#     经典/禅意（board.json）  x0=476.0  y0= 79.0  px=89.17  py=88.17
#     钻石矿                   x0=469.0  y0=133.1  px=85.25  py=84.50
#   钻石矿比经典低了约 54px、格距也小一点（矿坑上方有装饰框）。
#   ★ 用错几何的后果（用户报的"钻石矿重复点击空转"就是这个）：
#     拖动落到**错误的两格**上 → 游戏认为这不是合法交换 → 原样弹回 →
#     棋盘一动不动，而 bot 还在按自己的棋盘反复算同一招、反复点。
GEO = dict(BOARD)                  # 当前生效的几何
GEO_DIR = "/home/deck/bjbot"
_GEO_CACHE = {}
STALL_LIMIT = 12                   # 连续被拒多少步就停手等一等
STALL_WAIT = 20.0                  # 停手后最多等多少秒（秒）再试


def geo_for(key):
    """取某个模式的像素几何：先找 bjbot/board_<key>.json，没有就退回 board.json。"""
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]
    d = dict(BOARD)
    try:
        with open(os.path.join(GEO_DIR, "board_%s.json" % key)) as f:
            j = json.load(f)
        if all(k in j for k in ("x0", "y0", "pitch_x", "pitch_y")):
            d = j
    except Exception:
        pass
    _GEO_CACHE[key] = d
    return d


def set_geo(d):
    GEO.clear(); GEO.update(d)

libc = ctypes.CDLL("libc.so.6", use_errno=True)
class _IOV(ctypes.Structure):
    _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]
libc.process_vm_readv.restype = ctypes.c_ssize_t
def _vmread(pid, addr, size=4):
    buf = ctypes.create_string_buffer(size)
    l = _IOV(ctypes.cast(buf, ctypes.c_void_p), size)
    r = _IOV(ctypes.c_void_p(addr), size)
    n = libc.process_vm_readv(pid, ctypes.byref(l), 1, ctypes.byref(r), 1, 0)
    return buf.raw[:n] if n > 0 else None
def game_pid():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open("/proc/%s/comm" % p).read().strip() == "Bejeweled3.exe": return int(p)
            except Exception: pass
    return None
PID = game_pid()
def score():
    # ★ 优先 Board 对象链：实测三个绝对地址已失效（读到垃圾大数），
    #   而 Board 链 [gApp+0xBE8]+0xD24 始终正确。失败才回退绝对地址。
    try:
        from reader_mem import board_score
        v = board_score()
        if v is not None: return v
    except Exception:
        pass
    vs = []
    for a in SCORE_ADDRS:
        d = _vmread(PID, a, 4) if PID else None
        if d and len(d) == 4: vs.append(struct.unpack("<i", d)[0])
    if not vs: return None
    vs.sort(); return vs[len(vs)//2]

def log(m): print(time.strftime("%H:%M:%S ") + m, flush=True)
def cxy(i, j):
    """格子 (行 i, 列 j) 的屏幕中心像素 —— 用当前生效的几何 GEO。"""
    return (int(round(GEO["x0"] + j * GEO["pitch_x"])),
            int(round(GEO["y0"] + i * GEO["pitch_y"])))

def detect_mode(frame):
    """从画面自动识别游戏模式。返回 "poker" / "normal" / None。

    ★ 判据的两次迭代（2026-09-24）★

    第一版：看左侧取样区是不是"绿色"（G 是最大分量）。
      **失败** —— 那个区域的颜色受游戏背景亮度影响，
      实测同一模式在不同背景下的 RGB 从 (61,95,31) 变到 (90,81,30)，
      后者 G < R，判据就失效了。教训：不要用"整体色调"当判据。

    第二版（当前）：数【绿色横条像素的占比】。
      牌局模式左侧有 7 行分值表，每行是一条绿色横条 —— 这是它独有的特征。
      实测占比：
        牌局（游戏中）  0.348 ~ 0.461
        禅意 / 菜单     0.000
      差距极大，阈值取 0.2 非常安全。

      判据：G 明显大于 R 和 B（绿色条），且 G 在中等亮度区间（排除高光）。
      区域 x=250..430, y=180..460（分值表所在）。
    """
    if frame is None:
        return None
    try:
        import numpy as np
        f = np.asarray(frame, dtype="float32")
        if f.shape[0] < 470 or f.shape[1] < 440:
            return None
        reg = f[180:460, 250:430]
        G = reg[:, :, 1]
        is_green = ((G > reg[:, :, 0] + 10) & (G > reg[:, :, 2] + 30)
                    & (G > 60) & (G < 170))
        ratio = float(is_green.mean())
    except Exception:
        return None
    if ratio > 0.20:
        return "poker"          # 有整块绿色分值表 ⇒ 牌局
    return "normal"


def board_alive():
    """游戏是否活着（内存判据，**不可靠，仅作参考**）。

    ★ 2026-09-24 实测教训：结算画面上 Board 指针【依然有效】——
      实测停在「最终得分 60,500」画面时 `Board=0x4AD01138` 非零。
      所以"指针归零"不能用来判断游戏结束，我最早写错了这一点，
      导致 bot 对着结算画面反复算同一招（手牌一直不变、0.22 步/秒）。
      判断结束要用画面判据（见 screen_is_gameover）。
    """
    try:
        from reader_mem import _Proc, GAPP_ADDR, OFF_BOARD, _ptr_ok
        pid = game_pid()
        if pid is None:
            return False
        pr = _Proc(pid)
        g = pr.u32(GAPP_ADDR)
        if not _ptr_ok(g):
            return None
        b = pr.u32(g + OFF_BOARD)
        return bool(b)
    except Exception:
        return None


def screen_is_gameover(frame):
    """用画面判断是否停在结算画面。返回 True/False/None（None=抓帧失败）。

    ★ 2026-09-25 第二次重订（第一次也错了，记下来免得再绕）★

    第一版用 mid(280:340,520:880)：实测该区在两画面上都是 R>140、R-G>56，
      毫无区分度，必然误报。
    第二版改用底部条 R>150 且 R-G>40：8 个旧样本全对，但一遇到
      「开局『开始！』动画」那种画面（dump/f_00.png，bottom 是 R153/RG47）
      就跨在阈值线上，照样误报。

    现在这个特征是从 9 个样本、5 个区域、4 种标量里筛出来的：
      结算画面中部那块「等级 / 工匠 / 还有 1,255k」面板是明亮橙黄，蓝分量极低；
      活跃对局同一位置是左侧的蓝紫色背景，蓝分量很高。物理上说得通。

          区域 panel_top(180:260, 300:620)   R-B 值
            活跃对局                         -4, 3, 51, 73
            结算画面                          124

      间隔 51，是所有候选里最大的。再叠一个 R > 200（结算面板 R=229，
      活跃最高 186）做双保险，9 个样本 9/9 全对。
    """
    if frame is None:
        return None
    try:
        import numpy as np
        f = np.asarray(frame, dtype="float32")
        panel = f[180:260, 300:620]
        r = panel[:, :, 0].mean()
        b = panel[:, :, 2].mean()
    except Exception:
        return None
    return bool(r > 200 and (r - b) > 100)


def death_shots(cap, d, n=14, gap=0.75):
    """连拍死亡画面，供人工标定按钮位置。"""
    import os
    os.makedirs(d, exist_ok=True)
    from PIL import Image
    saved = 0
    for k in range(n):
        a = None
        for _ in range(6):
            a = cap.get(timeout=0.5)
            if a is not None:
                break
        if a is not None:
            Image.fromarray(a).save("%s/over_%02d.png" % (d, k))
            saved += 1
        time.sleep(gap)
    return saved


# 结算画面按钮坐标（1280x800，实测标定）
#   依据：2026-09-24 实拍结算画面 —— 底部三个按钮
#     「徽章」   x≈433, y≈738
#     「再玩一次」x≈640, y≈738   ← 用这个
#     「主菜单」 x≈847, y≈738
RESTART_BTN = (640, 738)
MAINMENU_BTN = (847, 738)


def click_restart(m, btn=None):
    """点「再来一次」继续玩。"""
    x, y = btn or RESTART_BTN
    m.click(x, y)
    time.sleep(1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--moves", type=int, default=0)
    ap.add_argument("--engine", choices=["pro", "fast"], default="pro")
    ap.add_argument("--vision", default="auto",
                    choices=["auto", "mem", "vision_np", "vision_np2"],
                    help="识别后端：auto=优先内存、失效自动退视觉（默认）；"
                         "mem=强制内存；vision_np/vision_np2=强制视觉")
    ap.add_argument("--still-ms", type=float, default=250.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--max-seconds", type=float, default=0)
    ap.add_argument("--no-click", action="store_true", help="只识别不点击（dry）")
    ap.add_argument("--no-pending", action="store_true",
                    help="关闭 pending 优化（每步都重新等静止）")
    ap.add_argument("--auto-restart", action="store_true",
                    help="游戏结束后自动点「再来一次」继续玩（牌局模式死了会用）")
    ap.add_argument("--death-shot", metavar="DIR",
                    help="检测到游戏结束时把画面连拍到 DIR（用于标定按钮位置）")
    ap.add_argument("--mode", default="auto",
                    choices=["auto", "normal", "poker"],
                    help="游戏模式：auto=自动识别（默认，看左侧面板是不是绿色分值表）；"
                         "normal=普通（每次消除都给分）；"
                         "poker=牌局（只有集齐5张牌型才给分，优先凑同花）")
    a = ap.parse_args()
    a.mode_auto = (a.mode == "auto")     # 记下是不是自动模式（后面 a.mode 会被改写）
    cap = PwCapture()
    if not cap.start(): log("抓帧失败: %s" % cap.err); return
    # ★ 后端选择：--vision auto（默认）优先内存，不可用则自动降级到视觉。
    #   内存的偏移依赖游戏版本；游戏一更新就可能失效，必须能自己退回去。
    use_mem = (a.vision == "mem")
    if a.vision == "auto":
        try:
            from reader_mem import mem_available
            ok, why = mem_available()
        except Exception as e:
            ok, why = False, "导入失败: %s" % e
        if ok:
            use_mem = True
            log("  后端自动选择: 内存（%s）" % why)
        elif "不在游戏中" in why:
            # 停在菜单：等进游戏再定。视觉在菜单里同样读不到棋盘，
            # 所以先挂内存，进游戏后自然可用；真不可用会走运行中降级。
            use_mem = True
            log("  后端选择: 内存（%s）" % why)
        else:
            log("  后端自动选择: 视觉（内存不可用：%s）" % why)
    if use_mem:
        from reader_mem import MemReader
        rd = MemReader(still_ms=a.still_ms, cap=cap)   # 混合：像素差判静止 + 内存读棋盘
        log("  内存后端: PID=%d gApp=0x%08X Board=0x%08X"
            % (rd.pid, rd.gapp, rd.pr.u32(rd.gapp + 0xBE8) or 0))
    else:
        rd = FastReader(cap, backend=("vision_np" if a.vision in ("mem", "auto") else a.vision))
    m = VMouse2()                      # ★ 常驻（只创建一次）
    s0 = score()
    log("=== bot v6 engine=%s vision=%s still=%.0fms pid=%s 起始分=%s ===" % (
        a.engine, a.vision, a.still_ms, PID, s0))
    done = 0; ok_n = 0; dead = 0; miss = 0; t0 = time.time()
    # ★ 牌局模式：每步都要看手牌决定追哪个花色
    pk = None
    import poker as _pk
    pk = _pk
    if a.mode == "auto":
        # 先用当前画面识别一次
        fr0 = None
        try:
            fr0 = cap.get(timeout=1.0)
        except Exception:
            fr0 = None
        dm = detect_mode(fr0)
        if dm:
            a.mode = dm
            log("  自动识别模式: %s（%s）"
                % ("牌局" if dm == "poker" else "普通",
                   "左侧有绿色分值表" if dm == "poker"
                   else "左侧没有分值表 ⇒ 按普通逻辑跑"))
        else:
            a.mode = "normal"
            log("  ⚠️ 模式识别不了（可能还在菜单/转场），暂用普通模式，"
                "运行中会继续识别")
    if a.mode == "poker":
        log("  牌局模式：优先凑同花（同花 50000 分，是第二名的 1.67 倍）")
    rows = []; tw = 0.0; tv = 0.0; td = 0.0
    blacklist = {}
    banned = set()          # ★ 走法级拉黑：被拒的招在棋盘变化前绝不再出
    banned_sticky = set()   # ★ 整局拉黑：吃时间宝石的招被拒后本局不再试
    pending = None
    prev_fp = None          # ★ 死局时检测洗牌用
    prev_nd = 0             # ★ 钻石矿泥土格数（变化沿触发日志）
    cs_prev = None          # ★ 游戏时钟采样（钻石矿结束检测用）
    cs_frozen = 0           # ★ 时钟连续冻结采样数
    cs_live_marked = False  # ★ 本进程已写过活跃标记
    cs_moved = False        # ★（已废弃，留位免得别处引用炸）
    end_idle_logged = False # 钻石矿结束待命提示只打一次
    was_over = False        # ★ 上一帧是否在结算画面（续局开关状态机）
    idle_logged = False     # 待命提示只打一次
    geo_key = None          # ★ 本局用哪套像素几何（None=还没定；开局/续局时重置）
    stall = 0               # ★ 连续被拒步数（棋盘没被我们打动）
    stall_fp = None         # ★ 停手期间的棋盘指纹（它变了就说明游戏继续了）
    stall_until = 0.0       # ★ 停手截止时间（到点无论如何再试一次）
    stall_logged = False    # 停手提示只打一次

    CS_LIVE = "/home/deck/bjbot/cs_live"

    def marker_live():
        """对局活跃标记（10 分钟窗口）：cs 曾在走时写入，消费后清除。
        跨进程记住「刚才真的在对局中」—— 守护重启不丢，菜单不误点。"""
        try:
            with open(CS_LIVE) as f:
                return (time.time() - int(f.read().strip())) < 600
        except Exception:
            return False

    def replay_switch(default):
        """续局开关：读插件面板写的标记文件（1/0）。文件缺失时用启动参数。"""
        try:
            with open("/home/deck/bjbot/autorestart") as f:
                return f.read().strip() == "1"
        except Exception:
            return default
    try:
        while True:
            if a.moves and done >= a.moves: break
            if a.max_seconds and time.time() - t0 > a.max_seconds: break

            # ★★ 游戏结束检测 —— 必须放在这里（每轮都查）★★
            #   2026-09-24 踩过的坑：我最初把它写在 `if g is None:`（读不到棋盘）
            #   分支里，结果它【从来没被执行过】—— 因为结算画面上棋盘是能读到的
            #   （Board 指针依然有效，返回冻结的棋盘），所以 `g is None` 不成立。
            #   症状：bot 对着结算画面一直"下棋"（反复算同一招、手牌恒定不变）。
            #   判据必须用画面（结算画面是整块橙色面板）。
            # ★★ 结算检测必须【无条件】跑（2026-09-25 实测教训）★★
            #   之前它只在开了 --auto-restart/--death-shot 时才执行，
            #   于是不带这两个参数跑时，撞上结算画面会【死循环】：
            #   实测 60 步里连续 35 步是同一招 (1,4)<->(2,4)、全部 实际=0、分数 0。
            #   原因：结算画面上棋盘是冻结的、但 Board 指针有效、也能读到棋盘，
            #   求解器照常算出走法，而游戏在结算界面根本不响应交换。
            #   ⇒ 判据必须每轮都查；--auto-restart 只决定【查到之后做什么】。
            fr_iter = None
            need_frame = True
            if need_frame:
                # 优先用 reader 自己的抓帧器；纯内存模式下 rd.cap 是 None，
                # 这时用 bot 自己的 cap，否则永远拿不到帧、判据形同虚设。
                _c = getattr(rd, "cap", None) or cap
                if _c is not None:
                    try:
                        fr_iter = _c.get(timeout=0.5)
                    except Exception:
                        fr_iter = None
            if screen_is_gameover(fr_iter):
                was_over = True
                auto_now = replay_switch(a.auto_restart)
                if auto_now or a.death_shot:
                    log("  ★ 检测到游戏结束（结算画面）")
                    if a.death_shot:
                        n = death_shots(cap, a.death_shot)
                        log("  已连拍 %d 帧到 %s" % (n, a.death_shot))
                    if auto_now:
                        click_restart(m)
                        miss = 0
                        ok_new = False
                        for _ in range(24):          # 最多等 12 秒
                            time.sleep(0.5)
                            try:
                                fr2 = (rd.cap.get(timeout=0.5)
                                       if getattr(rd, "cap", None) else None)
                            except Exception:
                                fr2 = None
                            if fr2 is not None and screen_is_gameover(fr2) is False:
                                ok_new = True
                                break
                        if ok_new:
                            log("  已点「再来一次」，新局已开始")
                            time.sleep(0.6)
                        else:
                            log("  ⚠️ 点了「再来一次」但新局未出现，再试一次")
                            click_restart(m)
                            time.sleep(2.5)
                        # ★ 新棋盘 = 旧拉黑全部作废；旧 pending 是上一局的棋盘，
                        #   拿它出招必被拒（对着新棋盘出旧招 = 开局白送几步）
                        banned.clear(); banned_sticky.clear(); blacklist.clear(); pending = None
                        # ★ 新一局重新选像素几何（模式可能换了）
                        geo_key = None; stall = 0; stall_fp = None
                        stall_logged = False
                        t0 = time.time()
                        continue
                else:
                    # ★ 续局开关=关：当局结束【不做任何操作】—— 不点击、不退出。
                    #   待命在结算画面；玩家自己点「再来一次」/开新局后自动继续。
                    #   （开/关由 --auto-restart 参数决定；run2.sh 里是
                    #     AUTORESTART=1/0 变量。旧版这里是直接 break 停机。）
                    if not idle_logged:
                        log("  ■ 当局结束：自动续局=关 → 待命中（不点击；"
                            "玩家手动开局后自动继续）")
                        # 新一局的棋盘与旧局无关，旧拉黑/pending 全部作废
                        banned.clear(); banned_sticky.clear(); blacklist.clear(); pending = None
                        geo_key = None; stall = 0; stall_fp = None
                        stall_logged = False
                        idle_logged = True
                    time.sleep(1.0)
                    continue
            else:
                was_over = False
                idle_logged = False

            # ★ auto 模式：运行中每 20 步复查一次（玩家可能中途换了模式）
            if a.mode_auto and done > 0 and done % 20 == 0 and fr_iter is not None:
                dm2 = detect_mode(fr_iter)
                if dm2 and dm2 != a.mode:
                    log("  ★ 模式变了：%s → %s"
                        % ("牌局" if a.mode == "poker" else "普通",
                           "牌局" if dm2 == "poker" else "普通"))
                    a.mode = dm2
                    if dm2 == "poker":
                        log("  牌局模式：优先凑同花")
                    dead = 0
                    pending = None
                    banned.clear(); banned_sticky.clear(); blacklist.clear()

            # ★ pending 优化：上一步结束时已确认静止，直接复用其结果
            if pending is not None and not a.no_pending:
                g, bad, wms, vms = pending, 0, 0.0, 0.0
                used_pending = True
                pending = None
            else:
                g, bad, wms, vms = rd.wait_still_and_read(min_still_ms=a.still_ms)
                tw += wms; tv += vms
                used_pending = False
            if g is None:
                miss += 1
                # ★ 运行中降级：内存【持续】读不到才切视觉。
                #   阈值不能太小 —— 动画中常有若干格颜色为 -1（超立方体/消除中），
                #   短暂超过 max_bad 属正常，误降级会白白丢掉内存后端的优势。
                #   实测教训：阈值 4 时 100 步里降级了（visions=57）。
                if use_mem and miss >= 25:
                    log("  ⚠️ 内存后端连续 %d 次读不到棋盘，自动降级到视觉后端" % miss)
                    try:
                        rd = FastReader(cap, backend="vision_np")
                        use_mem = False
                        pending = None
                        miss = 0
                        continue
                    except Exception as e:
                        log("  降级失败: %s" % e)
                if miss % 5 == 0: log("  .. 读不到棋盘(bad=%d) %d" % (bad, miss))
                if miss >= 8:
                    m.click(640, 713); time.sleep(0.6)
                    subprocess.run(["xdotool", "key", "Escape"],
                                   env={**os.environ, "DISPLAY": ":0"}, capture_output=True)
                    time.sleep(0.5); miss = 0
                continue
            miss = 0
            # ★ 原始棋盘留底（后面"拉黑"会把 g 里某些格子改写成 '?'，
            #   而"这一步有没有生效"必须拿原始棋盘比 —— 否则被改写的格子会让
            #   每一步都误判成"棋盘变了"→ 假有效 → 永不拉黑 → 反复点同一招）
            g_raw = [r[:] for r in g]
            # ★ 钻石矿识别（2026-09-25）：泥土格读作 'D'，从无到有时打一行
            nd = sum(row.count("D") for row in g)
            if nd and not prev_nd:
                log("  ★ 钻石矿：泥土 %d 格（不可消不可换；消旁边的宝石自动挖开）" % nd)
            prev_nd = nd
            # ★★ 像素几何按模式选（本局第一次读盘时定，局内不再变）★★
            #   有泥土 ⇒ 钻石矿 ⇒ 用 board_diamond.json 那套格子位置。
            if geo_key is None:
                geo_key = "diamond" if nd > 0 else "classic"
                _g = geo_for(geo_key)
                set_geo(_g)
                log("  像素几何: %s  x0=%.0f y0=%.0f px=%.2f py=%.2f%s"
                    % (geo_key, _g["x0"], _g["y0"], _g["pitch_x"], _g["pitch_y"],
                       "  ← 钻石矿格子比经典低约 54px，用错会点错格"
                       if geo_key == "diamond" else ""))
            # ★ 钻石矿计时结束检测（每局 1:30）：结束画面不是标准橙色结算
            #   面板，像素判不出 —— 但游戏时钟会停。判据：有泥 + cs>0（本局
            #   确实开始过）+ 时钟冻结满 8 次采样（约 20 秒；对局中时钟从不
            #   冻这么久）。金子不能当条件 —— 结算画面残留本局金子（实测
            #   13000）。按钮与普通结算同位 (640,738)，实测可点开局。
            cs = rd.cs_now() if hasattr(rd, "cs_now") else None
            if cs is not None:
                if cs == cs_prev:
                    cs_frozen += 1
                else:
                    cs_frozen = 0
                    end_idle_logged = False
                    # 时钟在走 = 对局活跃 → 写标记（每个活跃段只写一次）
                    if cs > 0 and not cs_live_marked:
                        try:
                            with open(CS_LIVE, "w") as f:
                                f.write(str(int(time.time())))
                        except Exception:
                            pass
                        cs_live_marked = True
                cs_prev = cs
                if cs_frozen >= 8 and nd > 0 and cs > 0 and marker_live():
                    try:
                        os.remove(CS_LIVE)
                    except Exception:
                        pass
                    cs_live_marked = False
                    if replay_switch(a.auto_restart):
                        log("  ★ 检测到本局结束（钻石矿计时到，时钟冻结）")
                        click_restart(m)
                        log("  已点「再来一次」")
                        dead = 0; cs_frozen = 0; cs_prev = None
                        t0 = time.time()
                        # ★ 等新局真正开跑（时钟开始走 = 发牌+"开始!"动画结束，
                        #   最多 15 秒）。期间出招必被游戏吃掉、候选全废——
                        #   实测只等 1.2 秒导致整局候选被拉黑、0 金趴窝。
                        cs_wa = rd.cs_now()
                        for _ in range(18):
                            time.sleep(0.8)
                            cs_wb = rd.cs_now()
                            if (cs_wa is not None and cs_wb is not None
                                    and cs_wb > cs_wa):
                                break
                            cs_wa = cs_wb
                        time.sleep(1.0)
                        banned.clear(); banned_sticky.clear()
                        blacklist.clear(); pending = None
                        geo_key = None; stall = 0; stall_fp = None
                        stall_logged = False
                        continue
                    elif not end_idle_logged:
                        log("  ■ 本局结束：自动续局=关 → 待命中（不点击）")
                        banned.clear(); banned_sticky.clear()
                        blacklist.clear(); pending = None
                        geo_key = None; stall = 0; stall_fp = None
                        stall_logged = False
                        end_idle_logged = True
                        dead = 0
            # ★★ 连续被拒保护（2026-09-25）★★
            #   交换连续多次没被游戏接受（棋盘纹丝不动）时不再盲目出手 ——
            #   否则几何不对 / 游戏在转场 / 有弹窗时会一直点同一个地方，
            #   看起来就是用户报的"重复点击空转"。停手等一等，棋盘自己变了
            #   或超时后再试。
            if stall >= STALL_LIMIT:
                fp_now = rd.mod.fingerprint(g_raw)
                if stall_fp is None:
                    stall_fp = fp_now
                    stall_until = time.time() + STALL_WAIT
                if fp_now != stall_fp or time.time() > stall_until:
                    log("  ✓ 恢复出手（%s）"
                        % ("棋盘已变化" if fp_now != stall_fp else "停手超时"))
                    stall = 0; stall_fp = None; stall_logged = False
                else:
                    if not stall_logged:
                        log("  ■ 连续 %d 步交换没被游戏接受 → 停手等待（最多 %d 秒）"
                            % (stall, int(STALL_WAIT)))
                        stall_logged = True
                    pending = None
                    time.sleep(1.0)
                    continue
            for (i, j), n in list(blacklist.items()):
                if n >= 3: g[i][j] = "?"
            if a.engine == "fast":
                try:
                    import solver_fast
                except ImportError:
                    log("  ⚠️ --engine fast 需要 solver_fast.py（包内未含），回退 pro")
                    a.engine = "pro"
                    continue
                mv = solver_fast.best_move([r[:] for r in g])
                if mv is None and blacklist:
                    # 同上：拉黑掩码掩出的假死局，用真实棋盘再算一次
                    mv = solver_fast.best_move([r[:] for r in g_raw])
                    if mv is not None:
                        log("  ★ 拉黑掩码掩出了假死局 → 清空拉黑，按真实棋盘走")
                        blacklist.clear(); g = [r[:] for r in g_raw]
                if mv is None: dead += 1; time.sleep(0.8); continue
                _, _, (i1, j1), (i2, j2) = mv; pred = 0
            elif a.mode == "poker":
                # ★ 牌局模式：先读手牌，据此定目标花色
                fr = fr_iter
                if fr is None and getattr(rd, "cap", None) is not None:
                    try:
                        fr = rd.cap.get(timeout=0.5)
                    except Exception:
                        fr = None
                hand = pk.read_hand(fr) if fr is not None else None
                known = [c for c in (hand or []) if c != "?"]
                import solver_poker
                # ★ 骷髅机制下的纪律：能凑同花就追同花（同花永不生成骷髅），
                #   已有 3~4 张同色更要忍住不打出低阶牌型。
                hv = pk.hand_value(hand)
                # 注：手牌满 5 张会自动结算，玩家只能通过"消哪种颜色"来影响牌型。
                #     所以这里不做"忍住不打"（那是无效操作），
                #     而是由 solver_poker 死盯目标色。
                if not known:
                    # 手牌全背面：没有花色信息。这时也【不能】乱打 ——
                    # 随便凑出的低阶牌型会累积骷髅。仅在别无选择时按普通评分走。
                    rk = solver_pro.rank_moves(g, banned=banned | banned_sticky)
                    if not rk:
                        dead += 1
                        if dead >= 30: break
                        time.sleep(1.0); continue
                    t = rk[0]; pred = t[1]; (i1, j1), (i2, j2) = t[6], t[7]
                else:
                    rk = solver_poker.rank_moves_poker(g, hand=hand, topk=10)
                    if not rk:
                        dead += 1
                        log("  牌局无走法(%d)等洗牌..." % dead)
                        if dead >= 30: break
                        time.sleep(1.0); continue
                    t = rk[0]; pred = t[1]; (i1, j1), (i2, j2) = t[5], t[6]
                    log("  手牌 %s  目标色=%s  牌型=%s  消目标色=%d%s"
                        % ("".join(hand), solver_poker.get_last_target(),
                           hv[0], t[8], "  ★目标色为多数色" if len(t) > 9 and t[9] else ""))
            else:
                # ★ 闪电模式：把时间宝石位置喂给求解器，让它优先去消。
                #   限时模式里不拿时间宝石就必死 —— 实测标记是
                #   flags & 131072（COUNTER 位），计数在 Piece+0x244。
                tg = (rd.last_extra or {}).get("timegems") or []
                if tg:
                    log("  ⏱ 时间宝石 %d 个: %s"
                        % (len(tg), ", ".join("(%d,%d)+%d" % t for t in tg)))
                # ★ 特殊宝石状态位（2026-09-26 新增）：火焰1 超立方2 闪电4 超新星5。
                #   数据本来就在每次读盘的 extra["flags"] 里，白拿 —— 交给求解器
                #   模拟它们的引爆范围（火焰 3×3、闪电整行整列、超新星叠加、链式引爆）。
                #   实测：70% 的帧盘面上有特殊宝石，接进去以后 1/3 的帧首选招会变，
                #   且都是变成"引爆特殊宝石"那一步。
                fl = {(i, j): f for (i, j, f) in
                      ((rd.last_extra or {}).get("flags") or [])
                      if f in (1, 2, 4, 5)}
                rk = solver_pro.rank_moves(g, timegems=tg,
                                           banned=banned | banned_sticky,
                                           flags=fl)
                # ★★ 拉黑掩码会掩出"假死局"（2026-09-26 实测）★★
                #   被拉黑 3 次的格子会被上面改写成 '?'，而 '?' 不但自己不能连线，
                #   还会**切断别人的连线**。钻石矿挖深以后有效走法本来就少，
                #   几个掩码就足以把真棋盘掩成 0 候选 ⇒ bot 判定"死局"、就地待命，
                #   看起来就是用户报的"挖到一定深度就不工作了"。
                #   实测现场（00:54，金币 $327,000）：掩码版候选 0，真实棋盘候选 2
                #   —— (2,3)<->(3,3)、(3,3)<->(4,3)，后者靠第 2 列 R,R,R 成三连，
                #   正是被 (2,3)=? 切断的。
                #   处理：0 候选且确有掩码时，用真实棋盘重算一次；有候选就说明
                #   是掩码造成的，清空拉黑按真实棋盘走。
                if not rk and blacklist:
                    rk_raw = solver_pro.rank_moves(g_raw, timegems=tg,
                                                   banned=banned | banned_sticky,
                                                   flags=fl)
                    if rk_raw:
                        log("  ★ 拉黑掩码掩出了假死局 → 清空拉黑，按真实棋盘走"
                            "（候选 %d，掩码格 %d）" % (len(rk_raw), len(blacklist)))
                        blacklist.clear()
                        g = [r[:] for r in g_raw]
                        rk = rk_raw
                # ★★ 最后一道兜底：连"走法级拉黑"也不带，纯问一句"这盘还有没有合法交换"
                #   （2026-09-26，通用三消文档 §5.1 的 hasAnyMove 思路）。
                #   被游戏拒过的招会被 banned 挡掉；若所有合法招恰好都被挡掉，
                #   上面两步都救不回来，仍会假死局。解禁重试有 stall 保护兜着
                #   （连续被拒会自动停手等待），所以不会退化成"重复点击空转"。
                if not rk and (banned or banned_sticky):
                    rk_free = solver_pro.rank_moves(g, timegems=tg, banned=set(),
                                                    flags=fl)
                    if rk_free:
                        log("  ★ 合法走法全被拉黑 → 解禁重算（候选 %d，原 ban %d 条）"
                            % (len(rk_free), len(banned) + len(banned_sticky)))
                        banned.clear(); banned_sticky.clear()
                        rk = rk_free
                if not rk:
                    dead += 1
                    fp_dead = rd.mod.fingerprint(g)
                    if fp_dead != prev_fp:
                        # 棋盘自己变了（游戏洗牌/换盘）→ 旧拉黑全部作废
                        banned_sticky.clear(); banned.clear()
                    prev_fp = fp_dead
                    if dead <= 2:
                        # ★ 死局现场诊断：棋盘明明读得到却没有候选 —— 打印看看
                        log("  死局现场 bad=%s banned=%d sticky=%d tg=%s 棋盘:"
                            % (bad, len(banned), len(banned_sticky), tg))
                        for row in g:
                            log("    " + " ".join(row))
                    if dead % 30 == 0:
                        log("  死局(%d)等洗牌/新局..." % dead)
                    if dead >= 30:
                        # ★ 长死局就地待命，不退出 —— 退出会被守护立刻拉起，
                        #   又对着同一块冻结盘打一轮（实测 crash-loop）。
                        #   结算/时钟检测每轮照跑，新局一来自动恢复。
                        time.sleep(1.0); continue
                    time.sleep(1.0); continue
                t = rk[0]; pred = t[1]; (i1, j1), (i2, j2) = t[6], t[7]
                tgset = set((i, j) for i, j, _ in tg)
                if tgset and ((i1, j1) in tgset or (i2, j2) in tgset):
                    log("  ★ 这一步直接拿时间宝石")
            dead = 0
            # ★ f0 必须取【原始棋盘】的指纹（g 已被上面的拉黑改写成 '?'）——
            #   2026-09-25 实测的坑：只要有格子被拉黑成 '?'，f0 就永远和
            #   下一帧的真实棋盘不同 ⇒ 每一步都判"棋盘变了"⇒ 假有效 ⇒
            #   拉黑被清 ⇒ 同一招无限重试（钻石矿里就这么空转了 35 步）。
            f0 = rd.mod.fingerprint(g_raw)
            sb = score()
            ts = time.perf_counter()
            if a.no_click:
                log("  [dry] %s<->%s 预测=%d" % ((i1, j1), (i2, j2), pred))
                if done >= 1: break
            m.drag(*cxy(i1, j1), *cxy(i2, j2))
            dms = (time.perf_counter() - ts) * 1000
            td += dms
            done += 1
            # ★ 被拒的交换不会有任何运动（棋盘、分数都不动），1.2 秒还不见
            #   运动就直接当被拒处理，别把 4 秒 max_wait 烧满（实测被拒一步白等 4 秒，
            #   光标钉在原地干等 —— 用户看到的就是"对着一个棋子乱点"）。
            g2, _, w2, v2 = rd.wait_still_and_read(require_motion=True,
                                                   min_still_ms=a.still_ms,
                                                   no_motion_exit=1.2)
            tw += w2; tv += v2
            sa = score()
            changed = (g2 is not None and rd.mod.fingerprint(g2) != f0)
            # ★★ "这次交换真的被游戏接受了没有" ★★
            #   只看我们拖的那两格：被拒的交换一定让这两格原样不动。
            #   棋盘可能因为别的原因变化（泥土状态抖动、洗牌、动画），
            #   只看整体指纹会被这些无关变化骗过去（2026-09-25 实测：
            #   几何不对时拖动落在别的格上，棋盘纹丝不动，却被判成有效）。
            swapped = bool(g2 is not None and
                           (g2[i1][j1] != g_raw[i1][j1] or
                            g2[i2][j2] != g_raw[i2][j2]))
            lvl = (sb is not None and sa is not None and sa < sb)
            real = (sa - sb) if (sb is not None and sa is not None and not lvl) else None
            # ★ 判"有效"要收紧：changed=True 但 real==0 是读数被动画污染的假阳性
            #   （有效交换必得分）。旧判据把这种假阳性当有效 → 清空拉黑 →
            #   同一招被无限重选（"反复算同一招、分数不涨"的根源之一）。
            #   ★ 2026-09-25 再收紧：real=None（分数读不到/局间重置）也不能算
            #   有效 —— 钻石矿实测 None+指纹微变 让两个废招每 0.5 秒无限交替
            #   （2208 次实际=0）。分数读不到就当被拒，宁可保守。
            # ★ 钻石矿（用户纠偏）：目标是挖泥往下走，非挖泥配对游戏也接受
            #   （棋盘会动、会刷新挖泥机会）—— 分数不动不算失败。
            #   ★ 2026-09-25 再收紧：钻石矿的分数在内存里读不到（实测画面
            #   $48,000 而 Board+0xD24 读 0），所以只能靠"棋盘变了"判；
            #   但必须再叠一条 swapped（我们拖的那两格确实变了），
            #   否则无关变化会把被拒的招洗白。
            if nd > 0:
                effective = bool(changed and swapped)
            else:
                effective = (real is not None and real != 0)
            if effective:
                ok_n += 1
                stall = 0; stall_fp = None; stall_logged = False
                blacklist.pop((i1, j1), None); blacklist.pop((i2, j2), None)
                # ★ 棋盘变了：之前被拒的招现在可能有效，全部解禁
                banned.clear()
                # ★ 复用本次的静止结果，下一步跳过"等静止"。
                #   但棋盘带洞（消除动画瞬间 piece 颜色无效）不存 ——
                #   拿有洞的棋盘规划必出错（2026-09-25 实测死局的根源）。
                if (g2 is not None and not a.no_pending
                        and not any(c == "?" for row in g2 for c in row)):
                    pending = g2
            else:
                stall += 1
                blacklist[(i1, j1)] = blacklist.get((i1, j1), 0) + 1
                blacklist[(i2, j2)] = blacklist.get((i2, j2), 0) + 1
                # ★ 走法级拉黑（阈值 1）：棋盘没变时同一招必再被拒，
                #   不 ban 就会连续重复同一招。棋盘一变即全部解禁。
                mv = frozenset(((i1, j1), (i2, j2)))
                banned.add(mv)
                # ★ 吃时间宝石的招被拒：整局拉黑。+100000 的权重会让它每次都排
                #   最前，动态拉黑又会被下一个有效步清掉 —— 结果就是对着宝石格
                #   一遍遍地点（2026-09-25 实测 #131~#135 连续 4 次全被拒）。
                if tgset and ((i1, j1) in tgset or (i2, j2) in tgset):
                    banned_sticky.add(mv)
            el = time.time() - t0
            rows.append({"n": done, "pred": pred, "real": real, "chg": bool(changed),
                         "swp": swapped, "eff": bool(effective),
                         "drag_ms": round(dms, 1),
                         "wait_ms": round(wms + w2, 1), "vision_ms": round(vms + v2, 1),
                         "pend": used_pending})
            log("  #%-3d %s<->%s 预测=%-5d 实际=%-6s %s [%.2f步/秒]" % (
                done, (i1, j1), (i2, j2), pred,
                ("%d" % real) if real is not None else ("过关" if lvl else "?"),
                "✓" if effective else "✗拉黑", done / el if el > 0 else 0))
    except KeyboardInterrupt:
        log("中断")
    finally:
        m.close(); cap.stop()
        el = time.time() - t0
        s1 = score(); st = rd.stats
        reals = [r["real"] for r in rows if r["real"] is not None]
        effs = [r for r in rows if r["eff"]]
        log("=== 结束 ===")
        log("  %d 步 %.1fs = %.2f 步/秒 (每步 %.0fms)" % (
            done, el, done / el if el else 0, el / max(done, 1) * 1000))
        log("  有效 %d/%d (%.0f%%)" % (len(effs), done, len(effs) / max(done, 1) * 100))
        log("  分数 %s → %s" % (s0, s1))
        log("  ── 每步构成 ──")
        n = max(done, 1)
        log("    拖动 %.0fms  等待 %.0fms  识别 %.0fms" % (td / n, tw / n, tv / n))
        if reals:
            log("  实际得分 总 %d, 平均 %.1f/步, ★分/秒 %.1f" % (
                sum(reals), sum(reals) / len(reals), sum(reals) / el if el else 0))
        if a.out:
            json.dump({"engine": a.engine, "vision": a.vision, "still_ms": a.still_ms,
                       "moves": done, "seconds": el, "s0": s0, "s1": s1, "ok": ok_n,
                       "per_step": {"drag": td / n, "wait": tw / n, "vision": tv / n},
                       "stats": st, "rows": rows}, open(a.out, "w"), indent=1)
            log("  已存 %s" % a.out)

if __name__ == "__main__":
    main()
