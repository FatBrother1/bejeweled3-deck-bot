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
LOG = os.path.join(HOME, "bjbot", "bot.log")


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


class Plugin:

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
        if os.path.exists(LOG):
            rc2, tail = _run(["/usr/bin/tail", "-n", "6", LOG], timeout=8)
            if rc2 == 0:
                st["log_tail"] = tail.strip()
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
