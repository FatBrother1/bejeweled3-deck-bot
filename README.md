# Bejeweled 3 Deck Bot

[![AI Developed](https://img.shields.io/badge/AI%20Developed-100%25-blueviolet)](#-关于-ai-开发)
[![Model](https://img.shields.io/badge/Model-deepseek--v4.1--flash-blue)](https://deepseek.com)
[![Platform](https://img.shields.io/badge/Platform-Steam%20Deck-1a9fff)](#)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

**Bejeweled 3 自动游玩机器人 + Steam Deck 游戏模式控制插件。**

外置视觉方案 —— 截屏识别棋盘、模拟鼠标点击。**不注入、不改游戏文件、不读写游戏内存做作弊**。

> 🤖 **本项目全程由 AI 开发** —— 模型 `deepseek-v4.1-flash`，无人工编写代码。
> 详见 [关于 AI 开发](#-关于-ai-开发)。

---

## ✨ 特性

| 特性 | 说明 |
|---|---|
| 🎯 **纯外置视觉** | 不注入游戏、不修改任何游戏文件（`Bejeweled3.exe` / `main.pak` 保持原样） |
| ⚡ **高性能抓帧** | 走 PipeWire 直取（~90 fps），不用 Steam 自带截屏（只有 2.2 fps） |
| 🧩 **解耦识别架构** | 静止判定只做 1ms 像素差，确认静止后才识别一次 —— **单步 3940ms → 1155ms** |
| 🎮 **游戏模式开关** | 配套 Decky 插件，在 Steam Deck 侧边栏一键开/关，不用开终端 |
| 📦 **便携安装** | 一条命令安装，路径自动改写，支持非 Steam Deck 的 Linux 机器 |
| 🛡️ **抗遮挡** | 连续读不到棋盘时自动尝试关闭弹窗 |

## 🚀 快速开始

### Steam Deck

```bash
git clone https://github.com/<你的用户名>/bejeweled3-deck-bot.git
cd bejeweled3-deck-bot/bot
bash install.sh              # 装到 $HOME
./run2.sh on                 # 开启（守护模式）
./run2.sh off                # 关闭
./run2.sh status             # 看状态
```

### 游戏模式（无需终端）

装配套的 Decky 插件，在侧边栏一键开关：

```bash
cd decky-plugin/BJBot
npm install && npm run build
node verify.mjs              # ★ 隔离验证，必须全过
bash rollback.sh             # 一键回滚
```

详见 [`decky-plugin/BJBot/`](decky-plugin/BJBot/) 与 [安装与使用](docs/安装与使用.md)。

## 📊 性能

实测 100 步长跑（Steam Deck，禅模式）：

| 指标 | 优化前 | 优化后 |
|---|---|---|
| **单步耗时** | 3940 ms | **1155 ms** |
| **步/秒** | 0.25 | **0.87** |
| **分/秒** | 26.2 | **168.3** |
| 每步识别次数 | ~40 | **2.0** |
| 有效率 | — | **98/100** |

**关键：游戏消除动画真实只有 535 ms**（不是最初以为的 1900 ms）。
单步物理下限 = 拖动 182 ms + 动画 535 ms = **717 ms**（≈1.39 步/秒）。

> ⚠️ 任何声称能跑 2 步/秒以上的配置都是**假速度** ——
> 交换会被游戏吃掉（实测 1.39 步/秒的配置分/秒反而更低）。
> 详见 [性能优化](docs/性能优化.md)。

## 🏗️ 架构

```
   ①抓帧              ②识别            ③求解            ④点击
┌──────────┐     ┌──────────┐    ┌──────────┐    ┌──────────┐
│ PipeWire │────▶│ 64 格    │───▶│ 模拟连消 │───▶│ 虚拟鼠标 │
│ ~90 fps  │     │ 宝石颜色 │    │ 打分排序 │    │ (uinput) │
└──────────┘     └──────────┘    └──────────┘    └──────────┘
      ▲                                                │
      └────────── 等画面静止（动画演完）◀───────────────┘
```

**五个关键设计**（都是实测踩坑换来的）：

1. **抓帧走 PipeWire** —— 比 Steam 截屏快 40 倍
2. **静止判定与识别解耦** —— 每帧只做 1 ms 像素差，避免"每帧都识别"的 2.1 秒浪费
3. **必须先见运动、再见静止** —— 静止判定太快会抢在动画前出手，交换被吃掉
4. **pending 复用** —— 上一步已确认静止，不重复等待（等待 2583 → 888 ms）
5. **拉黑机制** —— 同格 3 次无效交换即标记，避免死循环

## 🤖 关于 AI 开发

**本项目 100% 由 AI 编写，无一行代码由人类手写。**

| 项 | 值 |
|---|---|
| **模型** | `deepseek-v4.1-flash` |
| **开发方式** | 对话式迭代 + 真机实测验证 |
| **开发环境** | 安卓手机上的 DSH 容器 → SSH 远程操作 Steam Deck |

### AI 开发过程中真实踩过的坑（全部记录在案）

本项目的一个特点是：**所有失败、事故、错误判断都被如实记录**，而不是只留下光鲜的结果。

| 类别 | 例子 |
|---|---|
| **重大事故** | AI 手写 Decky 前端 bundle 时猜错了全局变量，**导致整个 Decky 前端白屏、插件商城打不开**（用户拍照反馈）→ 已修复并记录教训 |
| **错误判断** | AI 曾从"bot 日志异常"倒推"bot 误触进了牌局模式"，**实为用户手动进入** → 已更正 |
| **架构错误** | 最初以为"动画占单步 96.7%"，实测发现**那 2.1 秒是 AI 自己的识别开销**，与游戏动画无关 |
| **故弄玄虚被证伪** | 曾尝试用绝对定位虚拟鼠标"绕过鼠标加速"，实测**该设备在 gamescope 下根本不生效** |
| **被否定的路线** | 尝试 SpeedHack 加速游戏动画 → 两次崩溃游戏 → **证伪**（结论：时间 API 加速不可行） |

完整开发日志见 [docs/开发日志.md](docs/开发日志.md)。

## 📁 目录结构

```
├── bot/                    Bejeweled bot 本体（可独立安装）
├── decky-plugin/BJBot/     Steam Deck 游戏模式控制插件
├── tools/                  测量/剖析工具
└── docs/                   技术报告与开发日志
```

## 📚 文档

| 文档 | 内容 |
|---|---|
| [技术报告](docs/技术报告.md) | 完整技术方案、架构、实现细节 |
| [开发日志](docs/开发日志.md) | 全程记录：决策、事故、修正 |
| [性能优化](docs/性能优化.md) | 单步 3940→1155ms 的完整证据链 |
| [安装与使用](docs/安装与使用.md) | 详细安装、标定、故障排查 |
| [Decky 插件开发踩坑](docs/Decky插件开发踩坑.md) | 四个真实的坑 |

## ⚙️ 环境要求

| 要求 | 说明 |
|---|---|
| 操作系统 | Linux（SteamOS 验证；其他发行版理论可行） |
| **PipeWire** | **抓帧依赖它（主要门槛）** |
| Python 3 | + `numpy` / `evdev` / `Pillow` |
| GStreamer | + `gst-plugin-pipewire` |
| `/dev/uinput` | 模拟鼠标（一般加入 `input` 组即可） |
| xdotool | 可选（用于关弹窗） |

**游戏本体**：Bejeweled 3（Steam AppID 78000），原生或 Proton 均可。

## ⚠️ 免责声明

- 本项目**仅供学习与技术研究**（计算机视觉、自动化、Steam Deck 平台开发）
- **不修改任何游戏文件**，不读写游戏内存用于作弊
- 使用自动化工具**可能违反游戏服务条款**，**风险自负**
- 作者不对账号封禁等后果负责

## 📄 许可

[MIT](LICENSE)

---

<div align="center">

**本项目由 [deepseek-v4.1-flash](https://deepseek.com) 全程开发**

如果这个项目对你有帮助，欢迎 ⭐ Star

</div>
