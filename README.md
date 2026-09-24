# Bejeweled 3 Deck Bot

在 Steam Deck 上自动玩 Bejeweled 3。

做法很直白：截屏，认出棋盘，算一步，动鼠标。游戏文件一个字节不改，
内存也不碰。另外做了个 Decky 插件，这样在游戏模式里也能开关，
不用切到桌面模式开终端。

代码全部由 AI 编写，模型是 deepseek-v4.1-flash，我一行没写。
中间的失败和翻车也都记在 `docs/开发日志.md` 里了。

## 装

SteamOS / Arch 先补依赖：

```bash
sudo pacman -S --needed python-numpy python-evdev python-pillow \
    gstreamer gst-plugin-pipewire xdotool
```

Debian / Ubuntu：

```bash
sudo apt install python3-numpy python3-evdev python3-pil \
    gstreamer1.0-tools gstreamer1.0-pipewire xdotool
```

然后：

```bash
git clone https://github.com/FatBrother1/bejeweled3-deck-bot.git
cd bejeweled3-deck-bot/bot
bash install.sh
```

## 标定

这一步不能跳。分辨率、画质、机器不同，棋盘位置就不同：

```bash
python3 calib.py
```

它会存一张 `calib_overlay.png`。打开看一眼，网格上的紫点应该正好落在每颗
宝石中心，青色方框应该框住整个棋盘。同时它会打印识别结果，未知格必须是 0。

看着对了就写进去：

```bash
python3 calib.py --x0 476 --y0 79 --px 89.17 --py 88.17 --save
```

我没做成全自动的，因为试过，不靠谱。同一套正确参数，白天关卡覆盖率 0.912，
到了夜间森林只有 0.568，自动搜索会漂到错的位置还以为自己更准。所以还是得
眼睛看一遍。

## 用

```bash
./run2.sh on        # 开
./run2.sh off       # 关
./run2.sh status    # 看状态
./run2.sh logs 50   # 看日志
./run2.sh play 20   # 手动跑 20 步
./run2.sh dry 3     # 只识别不点击，用来验证识别正不正常
```

`on` 是守护模式，游戏一启动它就跟着跑，游戏退了它就停。重启 Deck 之后就没了，
不会偷偷在后台跑着。

想确认环境行不行，最直接的办法是：

```bash
./run2.sh dry 3
```

输出的未知格是 0 就说明没问题。有一两个可能是道具特效，超过三个就是标定
或者颜色阈值不对。

## 游戏模式

游戏模式没有终端，上面那些命令在那边用不了。想方便就装 Decky 插件：

```bash
cd decky-plugin/BJBot
npm install
npm run build
node verify.mjs                      # 装之前必须先跑这个
sudo cp -r . /home/deck/homebrew/plugins/BJBot
sudo chown -R deck:deck /home/deck/homebrew/plugins/BJBot
sudo systemctl restart plugin_loader
```

重启 loader 之后等半分钟，Steam 侧边栏里会出现 BJBot，点一下就开。

`verify.mjs` 那步别省。我一开始手写前端忘了编译，猜了个全局变量叫什么，
结果整个 Decky 面板白屏，连插件商城都打不开，用户拍照发我我才知道。
这个脚本就是为了在装机之前把这类问题拦下来。

万一出了事：

```bash
bash rollback.sh
```

## 速度

单步 1155 毫秒，一秒 0.87 步，一分得 168 分。跑了 100 步，98 步有效。

这个数字已经贴着上限了。游戏自己的消除动画要 535 毫秒，鼠标那套动作要
182 毫秒，加起来 717 毫秒，也就是最快 1.39 步每秒。

再快就是自欺欺人。我之前跑到过 1.39 步每秒那一版，看着最漂亮，但分/秒只有
69，比现在还差——因为它不等动画演完就出手，交换被游戏吃掉了，步数虚高、
得分虚低。所以看速度得看分/秒，光看步/秒会骗人。

## 它怎么工作的

```
截屏 (PipeWire, 90fps) → 认棋盘 → 算一步 → 动鼠标
                            ↑                │
                            └── 等画面静止 ───┘
```

拿棋盘有两种方式，默认自动选：

**视觉** —— 截屏识别颜色，一直以来的做法。

**内存** —— 直接读游戏进程里棋盘对象的数据。一次 1.18 毫秒，
而且不会把火焰宝石读成白色、不会误判超立方体、不依赖画面标定。

内存那套的完整对象布局来自公开逆向项目
[Ykzl/Bejeweled-3-Helper](https://github.com/Ykzl/Bejeweled-3-Helper)（MIT），
我做了 Proton 环境的验证、接进 bot、并解决了一个超立方体误判问题。
地址出处与实现见 [`bot/内存后端说明.md`](bot/内存后端说明.md)。

不过有一件事视觉做得更好：**过场动画约 8.45 秒，这期间内存里的棋盘数据是冻结的**，
只看内存会以为画面静止、抢在动画里出手。所以最终是**像素差判静止 + 内存读棋盘**。

几个地方是自己踩坑踩出来的：

抓屏用 PipeWire 而不是 Steam 自带截屏。后者只有 2.2 帧每秒，瓶颈在 PNG 编码，
前者 90 帧。

等画面静止的时候，每帧只做一次像素差比较（一毫秒左右），确认静止了才认一次
棋盘。原来我每帧都认，一次等待要认 40 多遍，光这就花了 2.1 秒。

判断静止前得先看见画面在动。解耦之后静止判定只要 40 毫秒就成立，比动画启动
还快，结果就是抢在动画前面出手，交换全被吃掉。

上一步确认过静止了，这一步就不用再等一遍。省下来大概 800 毫秒。

同一格连着三次没效果就拉黑不用了，不然会在那儿死循环。

## 装不上的话

它依赖 PipeWire 抓屏。换机器之后 `capture_pw.py` 里那个 `path=93` 大概率要改，
那是本机的 PipeWire 节点号，用 `pw-cli ls Node` 找工作机的视频流。

`vision_np.py` 里的颜色阈值是按 1280x800 加汉化高清补丁调的。换分辨率或者
换回原版素材，可能得重调。

没装 PipeWire 的纯 X11 环境得改抓屏实现，这个我没试过，`docs/未实测部分说明.md`
里列了哪些是我验证过的、哪些只是理论上可行。

## 文档

- `docs/技术报告.md` 完整方案和实现
- `docs/开发日志.md` 按时间记的全过程，包括翻车
- `docs/性能优化.md` 单步 3940 到 1155 毫秒怎么来的
- `docs/安装与使用.md` 安装、标定、排查
- `docs/Decky插件开发踩坑.md` 踩过的四个坑
- `docs/未实测部分说明.md` 哪些没验证过

## 说明

这东西是拿来学技术的——计算机视觉、自动化、Steam Deck 平台开发。它不改游戏
文件，也不读内存作弊，就是一个看屏幕动鼠标的程序。

不过自动玩可能违反游戏的服务条款，被封号的风险自己承担。

MIT 协议。
