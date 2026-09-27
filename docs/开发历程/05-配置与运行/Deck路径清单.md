# Deck 路径清单

机器 Steam Deck（SteamOS），`deck@192.168.3.11`，密钥 SSH 免密；非交互 SSH 的 PATH
极简，命令前先 `export PATH=$PATH:/usr/bin:/bin`。游戏 Bejeweled 3，AppId 78000，
启动命令 `steam steam://rungameid/78000`。

## bot 代码
在 `/home/deck/` 下，不是 `/home/deck/bjbot/`；后者只放标定、日志与备份。
`install.sh` 的部署清单（`TARGET` 默认 `$HOME`）就是下面这些：

- `bot_v6.py` 引擎主程序；`bot_<模式>.py` 八个薄壳入口（classic zen lightning
  icescape butterfly diamond poker quest），内容就是 `bot_v6.py --mode <key>`
- `modes/` 一个模式一个文件，另有 `__init__.py` 与 `base.py`，共 10 个文件
- `reader_mem.py` 内存后端；`reader_fast.py` `vision_np.py` 视觉后端与颜色阈值
- `solver_pro.py` 求解器；`cap2.py` `capture_pw.py` 抓帧入口与 PipeWire 实现
- `vmouse2.py` 虚拟鼠标，必须用相对移动；`watch2.py` 按需守护
- `which_mode.py` 模式探测；`run2.sh` 控制台，所有子命令在这儿

## 标定数据
`bot_v6.py` 里 `GEO_DIR = "/home/deck/bjbot"`，每个模式一份几何，找不到退回
`board.json`。

- `bjbot/board.json` 经典/禅意 x0=476.0 y0=79.0 px=89.17 py=88.17；`board_diamond.json` 钻石矿
- `bjbot/board_butterfly.json` 蝴蝶；`board_poker.json` 牌局 x0=482.5 y0=113.0 px=py=85.25
- `bjbot/board_lightning.json` 闪电 498.0/126.0/85.286/85.90

`calib.py` 读写的也是 `bjbot/board.json`，加 `--save` 才写，旧文件先备份成 `.bak`。

## 日志与标记文件
- `/home/deck/bjbot/bot.out` 活跃日志，守护拉起的 bot 的 stdout 追加在这儿；
  `run2.sh logs` 与插件面板读的都是它
- `/home/deck/bjbot/bot.log` 旧版 bot 写的，2026-09-24 之后不再更新，别拿它判断状态
- `/home/deck/bjbot/watch.log` 守护自己的日志（`watch2.py` 里的 `LOG`）
- `/home/deck/bjbot/autorestart` 续局开关，内容 1 或 0；插件面板写它、run2.sh 读它
- `/home/deck/bjbot/cs_live` 钻石矿对局活跃标记，cs 走动时写时间戳，10 分钟窗口

## 备份
都在 `/home/deck/bjbot/` 下，名字形如 `backup-*`：`backup-plugin-143312`、`backup-premodes-20260926`、
`backup-lc-20260927`、`backup-hc-20260927`、`backup-poker-20260927`。备份必须放 `bjbot/` 下，
放进 `homebrew/plugins/` 会被 Decky 当成插件加载。

## 插件与插件日志
- `/home/deck/homebrew/plugins/BJBot/` 插件安装目录，版本 v2.0.0
- `plugin.json` 版本号唯一来源，属主 root:root，同步时用 `sudo -n cp`；
  `package.json` 属主 deck:deck
- `main.py` 插件后端，只认 `/home/deck/` 下的 `bot_v6.py` / `which_mode.py` /
  `run2.sh`，不打包 bot
- `dist/` Decky 实际加载的前端产物；`refs/` 是 `which_mode.py` 的图像兜底参考图
- `/home/deck/homebrew/logs/BJBot/<加载时刻>.log` 插件开关日志，写 `stop rc=0` /
  `start rc=0`

## systemd 单元与常用命令
`bejewel-watch` 是 `systemd --user` 的临时单元，由 `run2.sh on` 用
`systemd-run --user --unit=bejewel-watch --collect` 起，重启 Deck 失效、没装开机自启。
`plugin_loader` 是系统单元（Decky 加载器），查它要 `journalctl -u plugin_loader`，
加 `--user` 查不到东西。

```bash
cd /home/deck && bash run2.sh status          # 守护/bot/游戏三行状态
systemctl --user is-active bejewel-watch      # 守护在不在
systemctl --user stop bejewel-watch           # 做单 bot 测量前必须先停它
sudo systemctl restart plugin_loader          # 插件改动后重载
sudo journalctl -u plugin_loader --since "-10min" | grep BJBot
journalctl --user -u bejewel-watch            # 守护自己的日志
pgrep -af "python3 /home/deck/bo[t]_"         # bot 进程与它跑的入口脚本
tail -30 /home/deck/bjbot/bot.out             # 最近日志
```

## 一致性核对
Deck 上的 bot 代码与仓库 main（`5bab585`）逐字节一致，md5 前 8 位：`bot_v6.py` `e0a9c772`、
`cap2.py` `f95446dd`、`capture_pw.py` `1a15a2ace`、`install.sh` `482a3b53`（**Deck 上那份 install.sh 还是旧版**，
仓库 main 与开发历程内已是 `f0c6a77d`，等 Deck 醒来同步；这四行与
`01-项目概况/当前运行状态.md` 里那张表一致）；`run2.sh` `7d46429f`、`watch2.py` `a61f2906`（我自己算的）。

## 未核实与缺口
- `install.sh` 的部署清单与现实对不上 —— **2026-09-27 已核实并修复**（提交 `9924d9d`）：
  ① 漏了 `calib.py`、`solver_fast.py`、`poker.py`、`solver_poker.py`（`modes/poker.py`
  在 choose 里 `import poker` 与 `import solver_poker`，第 43、72 行）；
  ② 清单里的 `which_mode.py` 在 `bot/` 下不存在（只有插件目录那一份）⇒ `set -e` 会让
  安装中断在那一步，`watch2.py`、`run2.sh` 都装不上。
  离线两条证据：`check_install.py`（清单存在性 + import 完整性，修复前报 3 个缺失、
  修复后通过）、`dryrun_install.sh`（把「② 复制文件」整段源码抠出来干装，38 个文件
  全落地、退出码 0）。**仍未做**：Deck 上那份 install.sh 的同步（Deck 睡眠中）。
  细节见 `02-技术报告/25-安装清单修复-20260927.md`。
- 早期还有一个临时单元 `bjtest`（记忆里提到它 inactive），当前是否还存在未核实。
- 游戏目录本身没被改过；补丁（`main.pak` / `Bejeweled3.exe` / `compat.cfg`）是用户自己装的，不在安装范围里。
