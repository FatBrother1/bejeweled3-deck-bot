#!/bin/bash
# Bejeweled 3 bot —— 一键安装脚本
# 用法：bash install.sh          （装到当前用户的 $HOME）
#       bash install.sh /path    （装到指定目录）
#
# 做的事：① 检查依赖 ② 复制文件并把脚本里的 /home/deck 换成实际目录
#         ③ 建 board.json 目录 ④ 自检
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$HOME}"
echo "════ Bejeweled 3 bot 安装 ════"
mkdir -p /home/deck/bjbot
[ -f /home/deck/bjbot/autorestart ] || echo 1 > /home/deck/bjbot/autorestart
echo "源目录: $HERE"
echo "目标  : $TARGET"
echo

# ── ① 依赖检查 ────────────────────────────────
echo "① 检查依赖"
MISS=0
for c in python3 gst-launch-1.0 xdotool; do
  if command -v $c >/dev/null 2>&1; then echo "   ✅ $c"
  else echo "   ❌ $c 缺失"; MISS=1; fi
done
python3 - <<'PY' || MISS=1
import importlib, sys
ok=True
for m in ["numpy","evdev","PIL"]:
    try:
        importlib.import_module(m); print("   ✅ python:",m)
    except Exception:
        print("   ❌ python:",m,"缺失"); ok=False
sys.exit(0 if ok else 1)
PY
if [ "$MISS" = "1" ]; then
  echo
  echo "缺依赖。Arch/SteamOS 上装法："
  echo "  sudo pacman -S --needed python-numpy python-evdev python-pillow gstreamer pipewire-x11 gst-plugin-pipewire xdotool"
  echo "Debian/Ubuntu 上装法："
  echo "  sudo apt install python3-numpy python3-evdev python3-pil gstreamer1.0-tools gstreamer1.0-pipewire xdotool"
  echo
  echo "（也可只用 pip： pip install --user numpy evdev pillow）"
  exit 1
fi
echo "   ✅ 依赖齐全"
echo

# ── ② 复制并改写路径 ──────────────────────────
echo "② 复制文件到 $TARGET"
mkdir -p "$TARGET/bjbot"
# ★ 关键：若 $TARGET 与源目录相同，`sed ... > 同名文件` 会先截断再读 ⇒ 自毁！
#   所以一律先写 .tmp 再原子改名，并且跳过"源=目标"的文件。
copy_one() {
  local f="$1"
  local src="$HERE/$f"
  local dst="$TARGET/$f"
  # 用两段替换 + 中间占位符 @@DSHROOT@@：
  #  ① 先 /home/deck → 占位符  ② 占位符 → 实际目录
  # 这样"是否还有残留"可以用占位符判断，不会因为目标路径本身含 /home/deck 而误报
  # （例如目标是 /home/deck/fakehome 时，grep '/home/deck' 会假阳性）。
  # 同时用 python3 读写而不是 `sed > 同名文件` —— 后者在 src=dst 时会先截断再读 ⇒ 自毁。
  python3 - "$src" "$dst" "$TARGET" <<'PY' || { echo "   ❌ $f 处理失败"; return 1; }
import sys
src, dst, target = sys.argv[1], sys.argv[2], sys.argv[3]
data = open(src, encoding="utf-8", errors="surrogateescape").read()
data = data.replace("/home/deck", "@@DSHROOT@@").replace("@@DSHROOT@@", target)
tmp = dst + ".tmp"
with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as fh:
    fh.write(data)
import os
os.replace(tmp, dst)          # 原子改名
sys.exit(1 if "@@DSHROOT@@" in data else 0)
PY
  echo "   → $f"
}
for f in bot_v6.py reader_fast.py capture_pw.py vision_np.py solver_pro.py vmouse2.py watch2.py run2.sh; do
  copy_one "$f"
done
chmod +x "$TARGET/run2.sh"
echo "   → run2.sh (已加可执行权限)"
# board.json 只在目标没有时复制（避免覆盖用户自己的标定）
if [ -f "$TARGET/bjbot/board.json" ]; then
  echo "   → board.json 已存在，保留不覆盖（保护你的标定）"
else
  cp board.json "$TARGET/bjbot/board.json"
  echo "   → bjbot/board.json"
fi
echo

# ── ③ 自检 ────────────────────────────────────
echo "③ 自检"
cd "$TARGET"
python3 -c "
import ast,sys
for f in ['bot_v6.py','reader_fast.py','vision_np.py','solver_pro.py','vmouse2.py','watch2.py']:
    ast.parse(open(f).read())
print('   ✅ 语法全部通过')
"
if python3 -c "import json;d=json.load(open('$TARGET/bjbot/board.json'));print('   ✅ 标定: 分辨率',d['screen'],'棋盘起点',d['x0'],d['y0'])"; then :; fi
echo
echo "════ 安装完成 ════"
echo "用法："
echo "  cd $TARGET"
echo "  ./run2.sh on       # 打开守护（游戏一起就自动跑 bot）"
echo "  ./run2.sh off      # 关掉"
echo "  ./run2.sh status   # 看状态"
echo "  ./run2.sh play 20  # 手动跑 20 步"
echo
echo "⚠️ 首次使用前必须确认标定（见 README.md「标定」一节）"
