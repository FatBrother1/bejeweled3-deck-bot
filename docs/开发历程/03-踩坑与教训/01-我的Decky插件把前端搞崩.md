# 教训：我写的 Decky 插件把 Decky 前端搞崩了

## 发生了什么

我为了给 Bejeweled bot 做一个"游戏模式开关"，**手写**了一个 Decky 插件前端 `dist/index.js`，
直接 `cp` 进 `/home/deck/homebrew/plugins/BJBot/`，重启 loader。

**结果**：Decky 侧边栏整个渲染失败（`Error Reference: Shared SteamUI_1097`），
**连插件商城也打不开**。用户实机拍照反馈。

## 根因（我猜错了 Decky 的 API 契约）

我**没有编译**，而是凭对 `.min.js` 的目测**猜**了两个全局变量：

```js
const DFL  = window.DFL || window.DFL_;      // ← 猜的，不存在
const React = SP_REACT;                       // ← 这个倒是对的
```

实际查 wmsxwd 的 sourcemap 后确认：**`DFL` 不是全局变量**，
它是 rollup 把 `@decky/ui` 打包进来后的**局部绑定名**——只在那份 bundle 内部存在。
`window.DFL` 是 `undefined`，于是：

```js
export default DFL.definePlugin(...)   // ← DFL is undefined ⇒ 抛异常
```

`definePlugin` 抛异常 ⇒ Decky 渲染该插件面板时崩溃 ⇒ **整个 QAM 面板白屏**，
商城也一起挂（同一个 React 树）。

## 报告里正好写着我该怎么做（而我跳过了）

`decky-wmsxwd` 技术报告里**明确写了正确做法**，我读晚了：

| 报告位置 | 原文 | 我的做法 |
|---|---|---|
| §3.1 目录树 | `src/index.tsx` (**源码**) + `dist/index.js` (**rollup 构建产物**) | ❌ 只手写 dist，无源码 |
| §3.1 | `package.json` + `rollup.config.mjs` + `tsconfig.json` | ❌ 全都没写 |
| §3.3 | 前端走 `@decky/api` 的 `callable` | ⚠️ 猜 `window.DeckyAPI` |
| §6 构建注意 | `npm install` 在 /sdcard 会权限拒绝，**必须复制到 /tmp 构建** | ❌ 我根本没构建 |
| §6 打包纪律 | zip 内**必须保留一层插件目录**；打包后**必须与已知可装版本 diff 文件列表** | ⚠️ 我保留了目录，但没 diff |
| §5.2 事故A | **Decky Loader 禁止强杀**；改插件只需 kill 该插件进程 | ✅ 我只重启了 loader（`systemctl restart`），没强杀 |

## 正确做法（下次必须这样）

```bash
# ① 源码在 /tmp 构建（不能在 /sdcard，权限拒绝）
cp -r 插件源码 /tmp/bjbot-build && cd /tmp/bjbot-build

# ② 装依赖（本机有 node/npm/pnpm）
npm install          # 或 pnpm install

# ③ 正规构建
npm run build        # rollup -c → dist/index.js

# ④ 关键：先看构建产物里 definePlugin 能不能解析
node -e "..."        # 或至少确认产物里有 @decky/api 的注入

# ⑤ 装之前，diff 已知可装插件的结构
#    （本机 15 个插件就是现成的"已知可装"基线）
```

**依赖版本参考 `freedeck-plugin`（本机已验证可用）**：
```json
{
  "dependencies":    { "@decky/api": "^1.1.3", "react-icons": "^5.3.0", "tslib": "^2.7.0" },
  "devDependencies": { "@decky/rollup": "^1.0.2", "@decky/ui": "^4.11.0",
                       "@rollup/rollup-linux-x64-gnu": "^4.53.3",
                       "typescript": "^5.6.2" },
  "scripts": { "build": "rollup -c" }
}
```
`rollup.config.mjs` 只有 3 行：
```js
import deckyPlugin from "@decky/rollup";
export default deckyPlugin({});
```

## 部署纪律（血的教训）

1. **绝不手写 `dist/index.js`** —— 必须过 rollup
2. **装新插件前先备份插件目录**，出问题立即移出
3. **验证顺序**：装 → 重启 loader → **等 30~60 秒** → 看 QAM 是否正常
   （SteamOS 有自愈：SDDM 检测会话崩溃会自动拉起，先等）
4. **出问题的第一动作**：把插件移出目录 + 重启 loader，别犹豫
5. 改插件 `main.py` **只需 kill 该插件进程**，不要动 PluginLoader
   （强杀 PluginLoader 会导致 22 个插件风暴 → 内存吃爆 → 全机黑屏，见报告 §5.2）

## 时间线（我这次的处置）

| 时间 | 动作 |
|---|---|
| 22:00 | 装了手写插件，loader 日志显示 `Loaded BJBot`（**加载成功，但前端渲染时才崩**） |
| 22:02 | 用户拍照：Decky 渲染失败、商城打不开 |
| 22:0x | 我立即 `mv` 插件出目录 + `systemctl restart plugin_loader` |
| 22:0x | 验证：插件数 15、BJBot 0、无错误日志、内存 10 GB 可用、swap 4 MB、load 1.47 |

**加载日志显示"成功"具有误导性** —— `found plugin` / `Loaded` 只证明**后端** main.py 起来了，
前端 bundle 的错要到 Steam UI 真正渲染那个面板时才暴露。

## 一句话总结

> **Decky 插件的前端必须用 `@decky/rollup` 正规构建，不能手写 bundle 猜全局变量。**
> 猜错的代价是**整个 Decky 前端（含商城）崩溃**。
