#!/bin/bash
# Bejeweled 3 bot 控制台（Deck）
#   ./run2.sh on            打开按需守护（游戏一起就起 bot，退出就停）—— 临时单元，重启失效
#   ./run2.sh off           关闭守护并停掉 bot
#   ./run2.sh status        看守护与 bot 状态
#   ./run2.sh logs [N]      看 bot 日志
#   ./run2.sh play [N]      手动直接跑 N 步（前台，Ctrl-C 停）
#   ./run2.sh turbo [N]     同 play（pending 优化已内置，无需单独 turbo）
#   ./run2.sh dry [N]       只识别不点击，打印棋盘
#
# ★ 2026-09-24 更新：--vision mem（内存读棋盘）+ --mode auto（自动识别模式）
#   自动识别：牌局看左侧绿色分值表；识别不了则按普通模式跑。
# ★ bot 内核切到 bot_v6.py（VMouse2 常驻 + pending +
#   拉黑 + 运动感知 + 抗遮挡），静止窗默认 250ms（实测分/秒 168.3 最优）。
set -u
export PATH=$PATH:/usr/bin:/bin
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/1000/bus}
cd /home/deck
BOT=/home/deck/bot_v6.py
STILL=250
case "${1:-help}" in
  on)
      systemctl --user stop bejewel-watch 2>/dev/null
      pkill -f "python3 /home/deck/bo[t]_" 2>/dev/null
      sleep 1
      systemd-run --user --unit=bejewel-watch --collect \
        /usr/bin/python3 /home/deck/watch2.py
      echo "守护已启动（临时单元，重启后失效）"
      ;;
  off)
      systemctl --user stop bejewel-watch 2>/dev/null
      pkill -f "python3 /home/deck/bo[t]_" 2>/dev/null
      pkill -f "python3 /home/deck/watc[h]2" 2>/dev/null
      echo "已全部停止"
      ;;
  status)
      echo "守护: $(systemctl --user is-active bejewel-watch 2>/dev/null)"
      echo "bot : $(pgrep -f 'python3 /home/deck/bo[t]_' >/dev/null && echo 运行中 || echo 未运行)"
      echo "游戏: $(pgrep -f 'Bejeweled3.ex[e]' >/dev/null && echo 运行中 || echo 未运行)"
      ;;
  logs)   tail -n "${2:-30}" /home/deck/bjbot/bot.log ;;
  play)   exec python3 $BOT --engine pro --vision mem --mode auto --still-ms $STILL --moves "${2:-0}" ;;
  turbo)  exec python3 $BOT --engine pro --vision mem --mode auto --still-ms $STILL --moves "${2:-0}" ;;
  dry)    exec python3 $BOT --engine pro --vision mem --mode auto --still-ms $STILL --no-click --moves "${2:-3}" ;;
  *)      sed -n '2,12p' "$0" ;;
esac
