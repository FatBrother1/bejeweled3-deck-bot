#!/usr/bin/env python3
"""按需守护：只在 Bejeweled 3 运行时拉起 bot，游戏退出即停 bot。

这就是你要的"打开这个游戏才启动 bot"：
  * 不玩游戏时零占用（没有 gst 抓帧、没有虚拟鼠标设备）
  * 游戏一开自动接手，游戏一关自动收工
  * 用 systemd-run 临时单元跑（重启失效、好撤销）
"""
import subprocess, sys, time, signal, os

GAME_PAT = "Bejeweled3.exe"
BOT = ["/usr/bin/python3", "/home/deck/bot_v6.py", "--engine", "pro", "--still-ms", "250"]
POLL = 2.0
LOG = "/home/deck/bjbot/watch.log"
OUT = "/home/deck/bjbot/bot.out"

def log(m):
    line = time.strftime("%H:%M:%S ") + m
    print(line, flush=True)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass

def game_running():
    return subprocess.run(["pgrep", "-f", GAME_PAT],
                          capture_output=True).returncode == 0

def main():
    log("=== watcher start (poll %.1fs) ===" % POLL)
    proc = None
    while True:
        alive = game_running()
        if alive and (proc is None or proc.poll() is not None):
            log("检测到游戏启动 -> 拉起 bot")
            proc = subprocess.Popen(BOT, cwd="/home/deck",
                                    stdout=open(OUT, "a"),
                                    stderr=subprocess.STDOUT)
        elif not alive and proc is not None and proc.poll() is None:
            log("游戏已退出 -> 停止 bot")
            proc.send_signal(signal.SIGINT)
            try: proc.wait(timeout=8)
            except subprocess.TimeoutExpired: proc.kill()
            proc = None
        elif not alive:
            proc = None
        time.sleep(POLL)

if __name__ == "__main__":
    main()
