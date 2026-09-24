# Bejeweled 3 Bot（bot 本体）

外置视觉自动游玩机器人。**不注入、不改游戏文件。**

## 安装

```bash
bash install.sh              # 装到 $HOME
bash install.sh /home/deck   # 或指定目录
```

安装脚本会检查依赖、自动改写路径、建 `bjbot/` 目录、做自检。

### 依赖

```bash
# Arch / SteamOS
sudo pacman -S --needed python-numpy python-evdev python-pillow \
    gstreamer gst-plugin-pipewire xdotool
# Debian / Ubuntu
sudo apt install python3-numpy python3-evdev python3-pil \
    gstreamer1.0-tools gstreamer1.0-pipewire xdotool
```

## 使用

`run2.sh` 是控制台：

```bash
./run2.sh on        # 开启（守护：游戏一开就自动跑）
./run2.sh off       # 关闭
./run2.sh status    # 状态
./run2.sh logs 50   # 日志
./run2.sh play 20   # 手动跑 20 步
./run2.sh dry 3     # 只识别不点击
```

## 标定（重要）

换机器 / 换分辨率 / 换画质后必做：

```bash
python3 calib.py
```

看生成的 `calib_overlay.png`：
- 紫色小圆点应落在**每颗宝石正中心**
- 青色方框应**正好框住棋盘**

**同时检查打印出的"未知格"数量 —— 必须是 0。**

> ⚠️ 标定不能全自动：覆盖率指标随关卡背景变化
> （白天 0.912 / 夜间 0.568），必须肉眼确认。

## 文件说明

| 文件 | 作用 |
|---|---|
| `run2.sh` | ★ 控制台（开关在这） |
| `bot_v6.py` | ★ bot 主程序 |
| `reader_fast.py` | 抓帧/静止判定/识别（性能关键） |
| `vision_np.py` | 棋盘识别（颜色阈值在这，换画质要改） |
| `solver_pro.py` / `solver_fast.py` | 三消求解器 |
| `vmouse2.py` | 虚拟鼠标（**必须用相对移动**） |
| `capture_pw.py` | PipeWire 抓帧（`path=93` 可能要改） |
| `watch2.py` | 守护进程 |
| `calib.py` | ★ 标定工具 |
| `install.sh` | 一键安装 |
| `bjbot/board.json` | 标定数据 |

## 参数

```bash
python3 bot_v6.py --engine pro --still-ms 250 --moves 100
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--engine` | `pro` | `pro`（推荐）/ `fast` |
| `--still-ms` | `250` | 静止窗（**实测最优，不建议改**） |
| `--moves` | 0 | 步数（0=一直跑） |
| `--out` | — | 结果 JSON |
| `--dry` | — | 只识别不点击 |

## 性能

| 指标 | 值 |
|---|---|
| 单步耗时 | **1155 ms** |
| 步/秒 | **0.87** |
| 分/秒 | **168.3** |
| 有效率 | **98%** |

物理下限 **717 ms**（拖动 182 + 动画 535）⇒ 上限 1.39 步/秒。
**再快就是假速度**（交换会被游戏吃掉）。

## 注意事项

- **不要用 `sudo` 跑** —— 会清掉 `XDG_RUNTIME_DIR` 导致 PipeWire 失败
- **`pkill -f` 在 SSH 里会自杀** —— pattern 匹配到自身时用 `[x]` 转义
- **绝对定位鼠标不生效** —— 必须用 `vmouse2.py`

详细文档见仓库根目录 [`docs/`](../docs/)。
