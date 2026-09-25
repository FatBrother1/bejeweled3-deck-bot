# Bejeweled 3 Bot

自动玩 Bejeweled 3。从游戏内存里读棋盘（只读，从不写入），算一步，动鼠标。
不改游戏文件。

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
| `reader_mem.py` | 内存读取后端（地址出处见 `内存后端说明.md`）|
| `poker.py` | 牌局模式：读手牌（看画面）+ 骷髅风险表 |
| `solver_poker.py` | 牌局求解器：优先凑同花 |
| `reader_fast.py` | 抓帧、静止判定、识别 |
| `vision_np.py` | 认棋盘。颜色阈值在这儿，换画质要改 |
| `solver_pro.py` `solver_fast.py` | 求解器 |
| `vmouse2.py` | 虚拟鼠标，必须用相对移动 |
| `capture_pw.py` | PipeWire 抓帧，`path=93` 可能要改 |
| `watch2.py` | 守护进程 |
| `calib.py` | 标定工具 |
| `install.sh` | 安装脚本 |
| `bjbot/board.json` | 标定数据 |

## 两个读取后端

bot 有两种拿棋盘的方式，默认自动选：

**内存后端**（推荐）—— 直接读游戏进程里的棋盘对象，一次 1.18 ms，
而且不会把火焰宝石读成白色、不会误判超立方体、不依赖画面标定。

**视觉后端** —— 截屏识别，一直是原来的默认。现在作为后备保留：
内存偏移依赖游戏版本，游戏一更新就可能失效，那时自动退回来。

```bash
python3 bot_v6.py                    # 默认 auto：优先内存，失效自动退视觉
python3 bot_v6.py --vision mem       # 强制内存
python3 bot_v6.py --vision vision_np # 强制视觉
python3 reader_mem.py                # 自检：读一次棋盘并打印
```

**静止怎么判**：现在是内存轮询——棋盘指纹和分数都不动了就算静止。
早期版本是像素差判静止，后来被同名的内存轮询版覆盖（坑记在开发日志里）。
过场动画期间内存数据冻结，这时靠结算画面判据兜底。
所以最终方案是**像素差判静止 + 内存读棋盘**。

地址来源与实现细节见 [`内存后端说明.md`](内存后端说明.md)。

## 游戏模式

`--mode` 选游戏模式，默认 normal：

```bash
python3 bot_v6.py --mode normal   # 普通（经典/禅意/闪电等）：每次消除都给分
python3 bot_v6.py --mode poker    # 牌局：只有集齐5张牌型才给分，优先凑同花
```

牌局模式和普通模式的规则完全不同，机制见
[`牌局模式说明.md`](牌局模式说明.md)。

牌局模式会死（凑出带骷髅标记的牌型要抛硬币，翻到骷髅就结束），
所以加了个自动续局：

```bash
python3 bot_v6.py --mode poker --auto-restart   # 死后自动点「再玩一次」
```

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
