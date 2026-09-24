# Bejeweled 3 Bot

自动玩 Bejeweled 3。截屏认棋盘，算一步，动鼠标。不改游戏文件，也不碰内存。

## 装

Arch 或 SteamOS：

```bash
sudo pacman -S --needed python-numpy python-evdev python-pillow \
    gstreamer gst-plugin-pipewire xdotool
```

Debian 或 Ubuntu：

```bash
sudo apt install python3-numpy python3-evdev python3-pil \
    gstreamer1.0-tools gstreamer1.0-pipewire xdotool
```

然后跑安装脚本：

```bash
bash install.sh              # 装到 $HOME
bash install.sh /home/deck   # 或者指定目录
```

它会检查依赖、把脚本里的路径改成你的实际目录、建 `bjbot/` 目录、做个自检。

## 标定

换机器、换分辨率、换画质之后都得重做：

```bash
python3 calib.py
```

它会存一张 `calib_overlay.png`。打开看，紫色小圆点应该落在每颗宝石正中心，
青色方框应该框住整个棋盘。同时打印识别结果，未知格必须是 0。

没做成全自动，因为试过不靠谱。覆盖率会随关卡背景变，同一套正确参数白天
丛林 0.912，夜间森林只有 0.568，自动搜索会漂到错位置。所以得人眼看。

## 用

```bash
./run2.sh on        # 开，守护模式
./run2.sh off       # 关
./run2.sh status    # 看状态
./run2.sh logs 50   # 看日志
./run2.sh play 20   # 手动跑 20 步
./run2.sh dry 3     # 只识别不点击
```

`on` 之后游戏启动它就跟着跑，游戏退了它就停。重启 Deck 之后失效，不会开机自启。

## 文件

| 文件 | 作用 |
|---|---|
| `run2.sh` | 控制台，开关在这儿 |
| `bot_v6.py` | 主程序 |
| `reader_fast.py` | 抓帧、静止判定、识别 |
| `vision_np.py` | 认棋盘。颜色阈值在这儿，换画质要改 |
| `solver_pro.py` `solver_fast.py` | 求解器 |
| `vmouse2.py` | 虚拟鼠标，必须用相对移动 |
| `capture_pw.py` | PipeWire 抓帧，`path=93` 可能要改 |
| `watch2.py` | 守护进程 |
| `calib.py` | 标定工具 |
| `install.sh` | 安装脚本 |
| `bjbot/board.json` | 标定数据 |

## 参数

```bash
python3 bot_v6.py --engine pro --still-ms 250 --moves 100
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--engine` | pro | pro 或 fast，推荐 pro |
| `--still-ms` | 250 | 静止窗，实测最好，不建议改 |
| `--moves` | 0 | 跑多少步，0 是一直播 |
| `--out` | — | 结果存哪 |

## 速度

单步 1155 毫秒，一秒 0.87 步，一分得 168 分，有效率 98%。

上限是每步 717 毫秒（拖动 182 加动画 535），也就是每秒 1.39 步。
再快就是丢步。

## 几个注意的

别用 sudo 跑，会把 `XDG_RUNTIME_DIR` 清掉导致 PipeWire 失败。

`pkill -f` 在 SSH 里如果模式匹配到自己的命令行会自杀，用 `[x]` 绕开。

绝对定位虚拟鼠标不生效，必须用相对移动那套。

详细文档在仓库的 `docs/` 下面。
