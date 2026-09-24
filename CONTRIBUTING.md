# 贡献指南

感谢你对本项目的兴趣！

## 开发环境

```bash
git clone https://github.com/<你的用户名>/bejeweled3-deck-bot.git
cd bejeweled3-deck-bot
```

### bot 部分

```bash
cd bot
python3 -m venv .venv && source .venv/bin/activate
pip install numpy evdev pillow
./run2.sh dry 3        # 只识别不点击，验证环境
```

### Decky 插件部分

```bash
cd decky-plugin/BJBot
npm install            # ⚠️ arm64 机器需把 @rollup/rollup-linux-x64-gnu 换成 arm64-gnu
npm run build
node verify.mjs        # ★ 必须全过才能提交
```

## 提交前检查

1. **`node verify.mjs` 必须全过** —— 这是防止插件把 Decky 搞崩的最后一道防线
2. 改动了 `bot/vision_np.py` 的颜色阈值 ⇒ 需重新标定并说明
3. 改动了性能相关代码 ⇒ 需提供前后对比数据

## 关于本项目的特殊性

本项目**全程由 AI 开发**。如果你也想用 AI 开发类似项目，建议注意：

- **所有结论必须有实测证据** —— AI 很容易"看起来合理"地推断错
- **失败也要记录** —— 本仓库的 `docs/开发日志.md` 保留了所有事故与错误判断
- **改动前先隔离验证** —— 尤其涉及系统级插件（本项目曾把 Decky 前端搞崩）

## 报告问题

请附上：
- `./run2.sh status` 输出
- `./run2.sh logs 30` 输出
- 相关截图（如果涉及界面问题）
