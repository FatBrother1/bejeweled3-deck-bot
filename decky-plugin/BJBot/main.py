"""BJBot —— Bejeweled 3 自动 bot 的 Decky 插件后端。

★ 设计原则（吸取事故教训）
  后端只做三件事：status / start / stop，实际执行一律复用已实测可用的
  /home/deck/run2.sh —— 不在插件里重新实现一套逻辑，减少出错面。

★ 为什么游戏模式需要它
  Steam Deck 游戏模式没有终端，`./run2.sh on` 只能桌面模式/SSH 用。
  本插件把开关搬进 Quick Access Menu（侧边栏），游戏模式内一键开/关。
"""
import asyncio
import os
import subprocess

import decky

logger = decky.logger

HOME = "/home/deck"
RUN2 = os.path.join(HOME, "run2.sh")
# ★★ 日志文件有两个，别搞混（2026-09-25 实测踩坑）★★
#   bot.out —— watch2.py 守护拉起的 bot_v6.py 的输出（**实际在写的就是这个**）
#   bot.log —— 旧版 bot 写的，2026-09-24 之后就没再更新过
#   插件原先读的是 bot.log，于是「识别方式/步数/时长」全显示陈旧数据。
LOG = os.path.join(HOME, "bjbot", "bot.out")
LOG_OLD = os.path.join(HOME, "bjbot", "bot.log")

# bot 内核脚本（实际干活的那个）与守护脚本。
#   UI 上要显示"启动的是哪个脚本"，排查时一眼能看出装的是哪一版。
BOT_SCRIPT = os.path.join(HOME, "bot_v6.py")
WATCH_SCRIPT = os.path.join(HOME, "watch2.py")
MODE_SCRIPT = os.path.join(HOME, "which_mode.py")


def _env():
    env = os.environ.copy()
    env["PATH"] = env.get("PATH", "") + ":/usr/bin:/bin:/usr/sbin:/sbin"
    env["XDG_RUNTIME_DIR"] = env.get("XDG_RUNTIME_DIR", "/run/user/1000")
    env["DBUS_SESSION_BUS_ADDRESS"] = env.get(
        "DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    # ★★ 必须清空 LD_LIBRARY_PATH（实测踩坑，方案来自 decky-wmsxwd 的处理）
    #   Decky 用 PyInstaller 打包，会把解包目录（如 /tmp/_MEIPmBEEx）注入
    #   LD_LIBRARY_PATH。该目录里有它自带的 libreadline，子进程调 /bin/bash 时
    #   会加载到错误版本，直接崩：
    #       /bin/bash: symbol lookup error: undefined symbol: rl_trim_arg_from_keyseq
    #   实测复现：LD_LIBRARY_PATH=/tmp/_MEIPmBEEx /bin/bash -c "echo ok" → 同样报错；
    #             清空后立即正常。
    env["LD_LIBRARY_PATH"] = ""
    env.pop("LD_PRELOAD", None)
    return env


def _run(args, timeout=30):
    """跑一条命令，返回 (rc, stdout+stderr)。不抛异常，失败也返回字符串。"""
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, env=_env(), cwd=HOME)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "命令超时（%ss）" % timeout
    except Exception as e:
        return -2, "执行失败: %s" % e


def _pgrep(pattern):
    rc, out = _run(["/usr/bin/pgrep", "-f", pattern], timeout=8)
    return [l for l in out.strip().splitlines() if l] if rc == 0 else []


REPLAY_FLAG = "/home/deck/bjbot/autorestart"


class Plugin:

    # ── 续局开关（当局结束后是否自动点「再来一次」）──────
    # 单一事实源 = /home/deck/bjbot/autorestart 标记文件（内容 1/0）。
    # bot_v6 每次走到结算画面都会重读它 —— 面板上拨一下，下一局就生效。
    async def get_replay(self):
        on = True
        try:
            with open(REPLAY_FLAG) as f:
                on = f.read().strip() == "1"
        except Exception:
            on = True          # 文件不存在 = 默认开（与旧守护行为一致）
        return {"on": on}

    async def set_replay(self, on: bool):
        try:
            os.makedirs(os.path.dirname(REPLAY_FLAG), exist_ok=True)
            with open(REPLAY_FLAG, "w") as f:
                f.write("1" if on else "0")
            logger.info("续局开关 -> %s" % ("开" if on else "关"))
            return {"ok": True, "on": bool(on)}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    async def _main(self):
        logger.info("BJBot 已加载；run2.sh 存在=%s" % os.path.exists(RUN2))

    async def _unload(self):
        logger.info("BJBot 已卸载（不停止正在跑的 bot）")

    async def _migration(self):
        pass

    # ── 状态 ────────────────────────────────────
    async def status(self):
        rc, out = _run([RUN2, "status"], timeout=20)
        st = {
            "running": False, "daemon": "unknown", "bot": "unknown",
            "game": "unknown", "game_running": False,
            "run2": os.path.exists(RUN2), "log_tail": "",
        }
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("守护:"):
                st["daemon"] = s.split(":", 1)[1].strip()
            elif s.startswith("bot :") or s.startswith("bot:"):
                st["bot"] = s.split(":", 1)[1].strip()
            elif s.startswith("游戏:"):
                st["game"] = s.split(":", 1)[1].strip()
        # 兜底：自己查进程，不依赖 run2.sh 输出格式
        if st["bot"] == "unknown":
            st["bot"] = "运行中" if _pgrep("python3 /home/deck/bo[t]_") else "未运行"
        if st["game"] == "unknown":
            st["game"] = "运行中" if _pgrep("Bejeweled3.ex[e]") else "未运行"
        st["running"] = (st["bot"] == "运行中")
        st["game_running"] = (st["game"] == "运行中")

        # ── 新增：给面板用的五项 ──────────────────────────
        # ① 当前游戏模式（自动检测）：内存优先，图像兜底
        st["mode"] = "—"
        st["mode_src"] = ""
        if st["game_running"] and os.path.exists(MODE_SCRIPT):
            rc3, out3 = _run(["/usr/bin/python3", MODE_SCRIPT, "--json"], timeout=25)
            if rc3 == 0 and out3.strip():
                try:
                    import json as _json
                    d = _json.loads(out3.strip().splitlines()[-1])
                    st["mode"] = d.get("name") or "—"
                    st["mode_src"] = d.get("src") or ""
                except Exception:
                    pass

        # ② 跑的是哪个脚本
        #   ★ 2026-09-26 模式脚本化：守护按 which_mode.py 检测到的模式拉起
        #     bot_<mode>.py，所以面板必须显示【实际在跑的那个】，
        #     不能再写死成 bot_v6.py（那样这栏永远是同一个名字、等于没信息）。
        st["script"] = os.path.basename(BOT_SCRIPT)
        st["script_path"] = BOT_SCRIPT
        st["script_ok"] = os.path.exists(BOT_SCRIPT)
        st["daemon_script"] = os.path.basename(WATCH_SCRIPT)
        #   ★ 必须用 pgrep -af（带命令行）：`_pgrep` 那个只给 PID，
        #     拿它去找 .py 永远找不到，面板会一直显示默认的 bot_v6.py。
        try:
            _rc_s, _out_s = _run(["/usr/bin/pgrep", "-af",
                                  "python3 /home/deck/bo[t]_"], timeout=8)
            if _rc_s == 0:
                for _line in _out_s.strip().splitlines():
                    for _tok in _line.split():
                        if _tok.endswith(".py") and "/home/deck/" in _tok:
                            st["script"] = os.path.basename(_tok)
                            st["script_path"] = _tok
                            st["script_ok"] = os.path.exists(_tok)
                            break
        except Exception:
            pass

        # ③ 识别后端：从 bot 日志抓（它会打"后端自动选择: 内存/视觉"）
        #    没跑过就是"—"
        st["backend"] = "—"
        # ④ 运行时长 / 已走步数：从日志抓最后一条
        st["uptime"] = "—"
        st["steps"] = "—"

        # 识别方式 / 步数 / 时长都从日志末段取。
        # ★ 但**必须先确认 bot 真的在跑** —— 否则读到的是上一次运行的历史，
        #   会显示"已运行 125 分钟"而实际根本没开（实测踩过这个坑）。
        if os.path.exists(LOG):
            rc2, tail = _run(["/usr/bin/tail", "-n", "6", LOG], timeout=8)
            if rc2 == 0:
                st["log_tail"] = tail.strip()

            # ★ 后端/步数/时长必须从【本次启动之后】的日志里找。
            #   踩过的坑：bot.out 是追加写的，累积了几千行历史，
            #   只 tail 最后 40 行够不到启动行（后端信息在第 2183 行、
            #   启动行在第 2184 行），导致 backend 一直显示"—"。
            #   做法：先定位最后一次 "=== bot v6" 启动行，只取它之后的内容。
            if st["running"]:
                rc3, allout = _run(["/usr/bin/tail", "-n", "3000", LOG], timeout=15)
                if rc3 == 0 and allout:
                    # 注意：bot 的启动顺序是
                    #     "内存后端: ..."        ← 后端信息在这里
                    #     "=== bot v6 ... ==="   ← 启动行
                    #     "自动识别模式: ..."     ← 模式识别
                    # 所以从启动行【往前多取一段】，否则会漏掉后端那行。
                    # （这是我改 --mode auto 时踩的坑：起初只从启动行往后截，
                    #   结果 backend 永远显示"—"。）
                    sess = allout
                    marker = "=== bot v6"
                    idx = allout.rfind(marker)
                    if idx >= 0:
                        start = max(0, idx - 400)
                        sess = allout[start:]
                    import re as _re
                    for line in sess.splitlines():
                        if "内存后端:" in line or "后端自动选择: 内存" in line:
                            st["backend"] = "内存"
                        elif "后端自动选择: 视觉" in line or "视觉后端" in line:
                            st["backend"] = "视觉"
                        m = _re.search(r"#(\d+)\s", line)
                        if m:
                            st["steps"] = m.group(1)
                    # 时间戳只取【启动行之后】的 ——
                    # 往前多取那 400 字符是为了抓后端信息，
                    # 但它带着上一会话的时间戳，算进去会得出几百分钟的假时长。
                    after = sess
                    mi = sess.rfind("=== bot v6")
                    if mi >= 0:
                        after = sess[mi:]
                    stamps = [l[:8] for l in after.splitlines()
                              if len(l) > 8 and l[2] == ":" and l[5] == ":"]
                    if len(stamps) >= 2:
                        try:
                            a = stamps[0].split(":")
                            b2 = stamps[-1].split(":")
                            sa = int(a[0]) * 3600 + int(a[1]) * 60 + int(a[2])
                            sb = int(b2[0]) * 3600 + int(b2[1]) * 60 + int(b2[2])
                            dd = sb - sa
                            if dd < 0:
                                dd += 86400
                            st["uptime"] = "%d分%02d秒" % (dd // 60, dd % 60)
                        except Exception:
                            pass
        return st

    # ── 开 ──────────────────────────────────────
    async def start(self):
        if not os.path.exists(RUN2):
            return {"ok": False, "msg": "找不到 %s" % RUN2}
        rc, out = _run([RUN2, "on"], timeout=45)
        logger.info("start rc=%s" % rc)
        await asyncio.sleep(1.5)
        st = await self.status()
        if st["running"] or st["daemon"] == "active":
            return {"ok": True, "msg": "已开启（守护运行中）", "status": st}
        return {"ok": False, "msg": "开启失败: %s" % out.strip()[:200], "status": st}

    # ── 关 ──────────────────────────────────────
    async def stop(self):
        rc, out = _run([RUN2, "off"], timeout=45)
        logger.info("stop rc=%s" % rc)
        await asyncio.sleep(1.5)
        st = await self.status()
        if not st["running"]:
            return {"ok": True, "msg": "已关闭", "status": st}
        return {"ok": False, "msg": "仍检测到 bot 在跑", "status": st}

    # ── 日志 ────────────────────────────────────
    async def logs(self, n=12):
        try:
            n = max(1, min(200, int(n)))
        except Exception:
            n = 12
        if not os.path.exists(LOG):
            return {"ok": False, "text": "还没有日志（bot 未运行过）"}
        rc, out = _run(["/usr/bin/tail", "-n", str(n), LOG], timeout=10)
        return {"ok": rc == 0, "text": out.strip()}
