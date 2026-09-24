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
    a = ap.parse_args()
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
    rows = []; tw = 0.0; tv = 0.0; td = 0.0
    blacklist = {}
    pending = None
    try:
        while True:
            if a.moves and done >= a.moves: break
            if a.max_seconds and time.time() - t0 > a.max_seconds: break
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
