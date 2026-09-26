#!/usr/bin/env python3
"""按需守护：只在 Bejeweled 3 运行时拉起 bot，游戏退出即停 bot。

这就是你要的"打开这个游戏才启动 bot"：
  * 不玩游戏时零占用（没有 gst 抓帧、没有虚拟鼠标设备）
  * 游戏一开自动接手，游戏一关自动收工
  * 用 systemd-run 临时单元跑（重启失效、好撤销）

# ★ 2026-09-26 模式脚本化

以前这里写死 `bot_v6.py --mode auto`，也就是"一个脚本自己猜模式"。现在改成
**按 which_mode.py 检测到的模式拉起对应的入口脚本**：

    检测到蝴蝶   -> /home/deck/bot_butterfly.py
    检测到牌局   -> /home/deck/bot_poker.py
    ...
    认不出来     -> /home/deck/bot_v6.py --mode auto（退回引擎自己认）

运行中模式变了（玩家切了模式）也会换脚本 —— 加了两拍防抖，避免转场那几帧
把模式认花导致来回重启。
"""
import json, subprocess, sys, time, signal, os

GAME_PAT = "Bejeweled3.exe"
# ★ 2026-09-25：续局改为开关 —— 环境变量 AUTORESTART（run2.sh on 会传进来）：
#   1 = 当局结束自动点「再来一次」；0 = 当局结束不操作（bot 待命，手动开局自动继续）
AUTORESTART = os.environ.get("AUTORESTART", "1") == "1"

HOME = "/home/deck"
ENGINE = os.path.join(HOME, "bot_v6.py")
MODE_SCRIPT = os.path.join(HOME, "which_mode.py")
# 认得出、且有对应入口脚本的模式。quest 现在认不出来，等 which_mode 补上就自动生效。
BOT_MODES = ["classic", "zen", "lightning", "icescape",
             "butterfly", "diamond", "poker", "quest"]

POLL = 2.0
LOG = "/home/deck/bjbot/watch.log"
OUT = "/home/deck/bjbot/bot.out"


def log(m):
    line = time.strftime("%H:%M:%S ") + m
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def game_running():
    return subprocess.run(["pgrep", "-f", GAME_PAT],
                          capture_output=True).returncode == 0


def detect_mode_key():
    """问 which_mode.py 现在是什么模式。认不出来返回 None。"""
    if not os.path.exists(MODE_SCRIPT):
        return None
    try:
        r = subprocess.run(["/usr/bin/python3", MODE_SCRIPT, "--json"],
                           capture_output=True, text=True, timeout=25)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        d = json.loads(r.stdout.strip().splitlines()[-1])
        k = d.get("key")
        return k if k in BOT_MODES else None
    except Exception:
        return None


def bot_cmd(key):
    """按模式选入口脚本。返回 (命令行, 脚本路径)。"""
    common = ["--engine", "pro", "--vision", "mem", "--still-ms", "250"]
    if AUTORESTART:
        common.append("--auto-restart")
    if key:
        s = os.path.join(HOME, "bot_%s.py" % key)
        if os.path.exists(s):
            return ["/usr/bin/python3", s] + common, s
    # 认不出来 ⇒ 退回引擎自己认（行为与改造前完全一致）
    return ["/usr/bin/python3", ENGINE, "--mode", "auto"] + common, ENGINE


def _spawn(cmd):
    return subprocess.Popen(cmd, cwd=HOME, stdout=open(OUT, "a"),
                            stderr=subprocess.STDOUT)


def _stop(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


def main():
    log("=== watcher start (poll %.1fs) 续局=%s 模式脚本化=开 ==="
        % (POLL, "自动点再来一次" if AUTORESTART else "待命不操作"))
    proc = None
    cur_key = None          # 当前跑着的入口对应的模式（None = 未识别/引擎自动）
    pending = None          # 防抖：上一拍看到的新模式
    while True:
        alive = game_running()
        if alive:
            key = detect_mode_key()
            if proc is None or proc.poll() is not None:
                cmd, script = bot_cmd(key)
                log("检测到游戏启动 -> 拉起 %s（模式=%s）"
                    % (os.path.basename(script), key or "未识别，引擎自己认"))
                proc = _spawn(cmd)
                cur_key = key
                pending = None
            elif key is not None and key != cur_key:
                # 模式变了 → 换脚本。要求连着两拍都看到新模式才动，
                # 否则转场那几帧认花一次就重启一次。
                if pending == key:
                    _stop(proc)
                    cmd, script = bot_cmd(key)
                    log("模式变了 %s -> %s → 换 %s"
                        % (cur_key or "未识别", key, os.path.basename(script)))
                    proc = _spawn(cmd)
                    cur_key = key
                    pending = None
                else:
                    pending = key
            else:
                pending = None
        elif proc is not None and proc.poll() is None:
            log("游戏已退出 -> 停止 bot")
            _stop(proc)
            proc = None
            cur_key = None
            pending = None
        else:
            proc = None
            cur_key = None
            pending = None
        time.sleep(POLL)


if __name__ == "__main__":
    main()
