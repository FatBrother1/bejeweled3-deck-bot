# 参与

## 环境

```bash
git clone https://github.com/FatBrother1/bejeweled3-deck-bot.git
cd bejeweled3-deck-bot
```

bot 部分：

```bash
cd bot
python3 -m venv .venv && source .venv/bin/activate
pip install numpy evdev pillow
./run2.sh dry 3        # 只识别不点击，验证环境
```

插件部分：

```bash
cd decky-plugin/BJBot
npm install            # arm64 机器要把 rollup 原生包换成 arm64-gnu
npm run build
node verify.mjs        # 必须全过
```

## 提交之前

`node verify.mjs` 必须全过。这是防止插件把 Decky 搞崩的最后一道防线。

改了 `bot/vision_np.py` 的颜色阈值，要重新标定并说明情况。

改了性能相关的代码，要给出前后的对比数据。

## 关于 AI 开发

这个项目全程由 AI 写的，模型先后用过 deepseek-v4.1-flash 和
glm-5.3-flash。如果你也想用 AI 做类似
的东西，有几点值得注意。

所有结论都要有实测证据。AI 很容易给出看起来合理但实际是错的推断，
这个项目里就吃过好几次亏。

失败也要记下来。`docs/开发日志.md` 里保留了所有事故和误判，这些比成功经验
更有用。

改之前先在隔离环境验证。涉及系统级插件的时候尤其要这样，这个项目曾经把
用户的 Decky 前端搞崩过一次。

## 报问题

带上这些：

```
./run2.sh status
./run2.sh logs 30
```

如果是界面问题，加张截图。
