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
    return (int(round(BOARD["x0"] + j * BOARD["pitch_x"])),
            int(round(BOARD["y0"] + i * BOARD["pitch_y"])))

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
    """用画面判断是否停在结算画面。

    实测依据（2026-09-24 实拍结算画面）：
      结算画面是一整块橙色面板 —— 顶部「最终得分」横幅区
      约 RGB(202,141,84)，中部棋盘区被面板覆盖约 RGB(208,158,91)，
      两者都是明显的 R > G > B（橙棕色调）。
      而游戏中棋盘区是深蓝紫背景 + 彩色宝石，不会有这种整体橙棕。

    返回 True/False/None（None = 抓帧失败，无法判断）。
    """
    if frame is None:
        return None
    try:
        import numpy as np
        f = np.asarray(frame, dtype="float32")
        top = f[45:95, 480:800]
        mid = f[280:340, 520:880]
        tr, tg, tb = top[:, :, 0].mean(), top[:, :, 1].mean(), top[:, :, 2].mean()
        mr, mg, mb = mid[:, :, 0].mean(), mid[:, :, 1].mean(), mid[:, :, 2].mean()
    except Exception:
        return None
    orange_top = (tr > 150 and tr > tg + 25 and tg > tb + 20)
    orange_mid = (mr > 140 and mr > mg + 20 and mg > mb + 10)
    return bool(orange_top and orange_mid)


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
    pending = None
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
            # 需要抓帧的条件：要判游戏结束、或者 auto 模式要复查模式。
            # （后者容易漏 —— 不开 --auto-restart 时也得抓，否则复查永远拿不到帧）
            fr_iter = None
            need_frame = (a.auto_restart or a.death_shot
                          or (a.mode_auto and done > 0 and done % 20 == 0))
            if need_frame:
                if getattr(rd, "cap", None) is not None:
                    try:
                        fr_iter = rd.cap.get(timeout=0.5)
                    except Exception:
                        fr_iter = None
            if a.auto_restart or a.death_shot:
                if screen_is_gameover(fr_iter):
                    log("  ★ 检测到游戏结束（结算画面）")
                    if a.death_shot:
                        n = death_shots(cap, a.death_shot)
                        log("  已连拍 %d 帧到 %s" % (n, a.death_shot))
                    if a.auto_restart:
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
                        t0 = time.time()
                        continue
                    else:
                        break

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

            # ★ pending 优化：上一步结束时已确认静止，直接复用其结果
            if pending is not None and not a.no_pending:
                g, bad, wms, vms = pending, 0, 0.0, 0.0
                pending = None
            else:
                g, bad, wms, vms = rd.wait_still_and_read(min_still_ms=a.still_ms)
                tw += wms; tv += vms
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
                    rk = solver_pro.rank_moves(g)
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
                rk = solver_pro.rank_moves(g)
                if not rk:
                    dead += 1
                    log("  死局(%d)等洗牌..." % dead)
                    if dead >= 30: break
                    time.sleep(1.0); continue
                t = rk[0]; pred = t[1]; (i1, j1), (i2, j2) = t[6], t[7]
            dead = 0
            f0 = rd.mod.fingerprint(g)
            sb = score()
            ts = time.perf_counter()
            if a.no_click:
                log("  [dry] %s<->%s 预测=%d" % ((i1, j1), (i2, j2), pred))
                if done >= 1: break
            m.drag(*cxy(i1, j1), *cxy(i2, j2))
            dms = (time.perf_counter() - ts) * 1000
            td += dms
            done += 1
            g2, _, w2, v2 = rd.wait_still_and_read(require_motion=True, min_still_ms=a.still_ms)
            tw += w2; tv += v2
            sa = score()
            changed = (g2 is not None and rd.mod.fingerprint(g2) != f0)
            lvl = (sb is not None and sa is not None and sa < sb)
            real = (sa - sb) if (sb is not None and sa is not None and not lvl) else None
            effective = changed or (real is not None and real > 0)
            if effective:
                ok_n += 1
                blacklist.pop((i1, j1), None); blacklist.pop((i2, j2), None)
                # ★ 复用本次的静止结果，下一步跳过"等静止"
                if g2 is not None and not a.no_pending:
                    pending = g2
            else:
                blacklist[(i1, j1)] = blacklist.get((i1, j1), 0) + 1
                blacklist[(i2, j2)] = blacklist.get((i2, j2), 0) + 1
            el = time.time() - t0
            rows.append({"n": done, "pred": pred, "real": real, "chg": bool(changed),
                         "eff": bool(effective), "drag_ms": round(dms, 1),
                         "wait_ms": round(wms + w2, 1), "vision_ms": round(vms + v2, 1)})
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
