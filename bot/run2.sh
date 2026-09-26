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
# ★★ 续局开关（2026-09-25）：当局结束后是否自动点「再来一次」
#   1 = 自动点（原守护默认行为）
#   0 = 不做任何操作 —— bot 待命在结算画面，玩家手动开局后自动继续
#   单次覆盖：AUTORESTART=0 ./run2.sh turbo    ；改默认值就直接改下面这行
AUTORESTART=${AUTORESTART:-$(cat /home/deck/bjbot/autorestart 2>/dev/null || echo 1)}
RSFLAG=""
[ "$AUTORESTART" = "1" ] && RSFLAG="--auto-restart"
case "${1:-help}" in
  on)
      systemctl --user stop bejewel-watch 2>/dev/null
      pkill -f "python3 /home/deck/bo[t]_" 2>/dev/null
      sleep 1
      systemd-run --user --unit=bejewel-watch --collect \
        --setenv=AUTORESTART=$AUTORESTART \
        /usr/bin/python3 /home/deck/watch2.py
      echo "守护已启动（临时单元，重启后失效）续局=$([ "$AUTORESTART" = 1 ] && echo 自动点 || echo 待命)"
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
      echo "续局: AUTORESTART=$AUTORESTART ($([ "$AUTORESTART" = 1 ] && echo 当局结束自动点再来一次 || echo 当局结束待命不操作))"
      ;;
  logs)   tail -n "${2:-30}" /home/deck/bjbot/bot.out ;;
  modes)  echo "认得的模式（modes/ 里一个模式一个文件）："
          for f in /home/deck/bot_*.py; do
            [ -e "$f" ] || continue
            m=$(basename "$f" .py); m=${m#bot_}
            [ "$m" = "v6" ] && continue
            echo "    $m"
          done
          echo "  用法: ./run2.sh run <模式> [步数]   # 不写模式=自动识别" ;;
  run)    M="${2:-auto}"
          if [ "$M" = "auto" ]; then S=/home/deck/bot_v6.py; A="--mode auto";
          else S="/home/deck/bot_$M.py"; A=""; fi
          if [ ! -f "$S" ]; then echo "没有这个模式的脚本: $S"; exit 1; fi
          exec python3 "$S" $A --engine pro --vision mem --still-ms $STILL $RSFLAG --moves "${3:-0}" ;;
  play)   exec python3 $BOT --engine pro --vision mem --mode auto --still-ms $STILL $RSFLAG --moves "${2:-0}" ;;
  turbo)  exec python3 $BOT --engine pro --vision mem --mode auto --still-ms $STILL $RSFLAG --moves "${2:-0}" ;;
  dry)    exec python3 $BOT --engine pro --vision mem --mode auto --still-ms $STILL --no-click --moves "${2:-3}" ;;
  *)      sed -n '2,12p' "$0" ;;
esac
