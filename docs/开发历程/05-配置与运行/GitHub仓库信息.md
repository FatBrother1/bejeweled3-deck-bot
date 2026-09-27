# GitHub 仓库信息

## 仓库
- 地址：https://github.com/FatBrother1/bejeweled3-deck-bot
- clone：`https://github.com/FatBrother1/bejeweled3-deck-bot.git`
- 可见性 public，不是 fork；许可证 MIT；默认分支 main
- 当前 main：`5bab585`，提交信息 `fix: which_mode.py 放一份进 bot/`。上一个提交
  `9924d9d` 的提交信息 `fix: 全新安装会缺文件 —— 牌局的 poker/solver_poker
  没进部署清单，which_mode.py 更会把安装中断`，时间 2026-09-27T16:08:47+08:00
  （v2.0.0 之后唯一的新提交；没有发版、没有动版本号）
- 仓库创建 2026-09-24T15:03:59Z，最后一次推送 2026-09-27T07:10:07Z
- 描述：Bejeweled 3 auto-play bot for Steam Deck. Reads the board from game memory
  (read-only, never writes), plays with a simulated mouse. + Decky plugin for Game
  Mode. 100% AI-developed.
- topics：ai-generated、automation、bejeweled、computer-vision、decky-plugin、
  opencv、pipewire、python、steam-deck、uinput

## Release 列表
共 23 个，按发布时间倒序；tag 与标题取自仓库的 Release 列表，时间是世界时。

| tag | 标题 | 发布时间 | id |
|---|---|---|---|
| v2.0.0 | v2.0.0 — 正式版 | 2026-09-27T07:10:07Z | 397545869 |
| v0.2.20 | v0.2.20 — 抓帧兜底修复 | 2026-09-27T06:47:06Z | 397540352 |
| v0.2.19 | v0.2.19 — 牌局按牌型阶梯重写选步 | 2026-09-27T06:26:20Z | 397535359 |
| v0.2.18 | v0.2.18 — 经典模式攒万变魔方 | 2026-09-27T04:28:13Z | 397508452 |
| v0.2.17 | v0.2.17 | 2026-09-27T00:11:10Z | 397441352 |
| v0.2.16 | v0.2.16 — 模式脚本化 | 2026-09-26T15:04:49Z | 397277491 |
| v0.2.15 | v0.2.15 — 牌局优先拿同花 | 2026-09-26T07:35:18Z | 397142233 |
| v0.2.14 | 0.2.14 — 通用失焦暂停自愈 | 2026-09-26T06:31:40Z | 397124585 |
| v0.2.13 | 0.2.13 — 模式显示全错修复 | 2026-09-26T00:44:51Z | 397003728 |
| v0.2.12 | 0.2.12 — 特殊宝石引爆范围建模 | 2026-09-25T17:48:47Z | 396812066 |
| v0.2.11 | 0.2.11 — 钻石矿挖深后假死局修复 | 2026-09-25T17:14:57Z | 396791053 |
| v0.2.10 | 0.2.10 — 钻石矿空转修复 | 2026-09-25T16:39:51Z | 396768898 |
| v0.2.9 | 0.2.9 — 钻石矿持续挖掘 | 2026-09-25T15:41:03Z | 396730443 |
| v0.2.8 | 0.2.8 — 挖深优先 | 2026-09-25T15:27:43Z | 396721341 |
| v0.2.7 | 0.2.7 — 钻石矿挖金策略 | 2026-09-25T15:22:12Z | 396717388 |
| v0.2.6 | 0.2.6 — 钻石矿识别与自动续局 | 2026-09-25T14:56:06Z | 396699080 |
| v0.2.4 | 0.2.4 — 闪电修复与面板续局开关 | 2026-09-25T13:51:22Z | 396649294 |
| v0.2.3 | 0.2.3 — 闪电修复与续局开关 | 2026-09-25T12:51:03Z | 396600686 |
| v0.2.2 | 0.2.2 — 面板显示当前模式 | 2026-09-25T04:11:26Z | 396290068 |
| v0.2.1 | 0.2.1 — 牌局模式自动续局 | 2026-09-24T18:56:15Z | 395981893 |
| v1.2.0 | v1.2.0 — 牌局模式 | 2026-09-24T18:28:54Z | 395960209 |
| v1.1.0 | v1.1.0 — 内存读取后端 | 2026-09-24T17:11:39Z | 395901473 |
| v1.0.0 | v1.0.0 — 首个版本 | 2026-09-24T15:21:02Z | 395817930 |

没有 v0.2.5：那一版没发出去，tag 被删掉并入 v0.2.6。v1.0.0 / v1.1.0 / v1.2.0 是早期
乱发的三个，插件当时还是 0.2.1；正式版没动它们，另起了 v2.0.0。

## 每个 Release 的三个资产
| 资产 | 内容 | 打包命令 |
|---|---|---|
| `bejeweled3-deck-bot-<版本>.zip` | 整仓 | `git archive HEAD` |
| `bejeweled-bot-<版本>.zip` | bot 本体 | `git archive HEAD:bot` |
| `BJBot-<版本>.zip` | Decky 插件 | `git archive HEAD:decky-plugin/BJBot` |

用 `git archive` 打包，自动排除 `.git` 与 `__pycache__`，打完过 `zipfile.testzip()`。
v0.2.16 及更早是 `.tar.gz`，从 v0.2.17 起改成 `.zip`。v2.0.0 三个资产的大小：整仓
1523829、bot 本体 131733、插件 1320730。
**⚠️ 2026-09-27 这三个资产被覆盖过一次**（install.sh 修复 + `which_mode.py` 进 `bot/`），
文件名与 tag 不变、字节变了，见 `02-技术报告/26-发行资产覆盖-20260927.md`。
早期三个（v1.0.0 / v1.1.0 / v1.2.0）的第三个资产都叫 `BJBot-v0.2.1.tar.gz`，
v1.1.0 的 bot 资产沿用了 `bejeweled-bot-1.0.0.tar.gz` 这个名字，命名不统一。

## 发布流程与纪律
发一次算发完要走四步，缺一不算：commit → push → release → Deck 插件目录版本同步。
同步 Deck 是 scp 两个 json（必要时再补源码文件）、`sudo -n cp`、重启 `plugin_loader`，
然后 `journalctl -u plugin_loader` 确认日志里出现 `Loaded BJBot (vX.Y.Z)`。

- 版本号的唯一来源是 `decky-plugin/BJBot/plugin.json`，GitHub Release 的 tag 与它一致；
  `package.json` 也同步改，但版本纪律以 `plugin.json` 为准。
- 提交粒度：功能提交只动代码文件，release 提交只动 `plugin.json` + `package.json`
  这两个版本文件；docs 改动（如 README）单独一个提交。
- 已发布版本的资产不覆盖，不 force-push。
- 发布说明用拟人化口吻写，不用加粗、表格、emoji。
- 建 release 与传资产走纯 urllib 脚本（token 前缀是 `github_pat_`，用 `gh` 开头的
  正则取不到）。
- 仓库里的 `scripts/push-to-github.sh` 是 2026-09-24 建仓时的一键脚本，它第 79 行的
  push 带了 `--force`。那是建仓引导用的；发版纪律按上面那条，不 force-push。

## 未记录
各 Release 的发布说明正文没有全部存档，仓库里只留了 0.2.15、0.2.18、0.2.19、2.0.0
四份（在 `输出/2026-09-26/bejeweled/` 各自轮次的 `release/` 下）；每个 Release 的
资产具体字节数与下载数未记录。
