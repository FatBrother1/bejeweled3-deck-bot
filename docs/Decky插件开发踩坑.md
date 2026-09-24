# Decky 插件开发：四个真实的坑

> 本文记录开发 `BJBot` 插件时踩过的四个坑，**全部有实测证据**。
> 其中坑 1 导致了一次真实事故（整个 Decky 前端崩溃）。

---

## 坑 1：手写 bundle 猜全局变量 ⇒ 整个 Decky 前端崩溃 ★最严重

### 我的错误做法

为了省事，**手写** `dist/index.js`，**没有编译**，凭目测猜全局变量：

```js
const DFL = window.DFL || window.DFL_;   // ← 猜的，实际不存在
const React = SP_REACT;                   // ← 这个猜对了
```

### 真相

`DFL` **不是全局变量**，而是 rollup 把 `@decky/ui` 打包进来后的**局部绑定名**，
只在那份 bundle 内部存在。

查参考插件的 sourcemap 可证：
```
sources: ['decky://.../node_modules/@decky/api/dist/index.js',
          'decky://.../node_modules/react-icons/...',
          'decky://.../src/index.tsx']
```

### 后果

`window.DFL` 是 `undefined` ⇒ `DFL.definePlugin(...)` 抛异常
⇒ **整个 QAM 面板渲染失败、插件商城也打不开**。

```
Error Reference: Shared SteamUI_1097
Decky Version: v3.2.8-pre1
```

### ★ 最要命的误导：加载日志显示"成功"

```
[loader][INFO]: found plugin: BJBot
[loader][INFO]: Loaded BJBot (v0.1.0)
BJBot 插件已加载
```

**这只证明后端 `main.py` 起来了**；前端 bundle 的错
**要到 Steam UI 真正渲染那个面板时才暴露**。

> **判断插件是否可用，不能只看 loader 日志 —— 必须看 QAM 里能不能打开。**

### 正确做法

```bash
npm install
npm run build        # rollup -c → dist/index.js
```

源码从正规包导入：
```tsx
import { definePlugin, PanelSection, PanelSectionRow, ButtonItem, staticClasses } from "@decky/ui";
import { callable } from "@decky/api";
```

**依赖版本**（照抄已验证可用的插件）：
```json
{
  "dependencies":    { "@decky/api": "^1.1.3", "react-icons": "^5.3.0", "tslib": "^2.7.0" },
  "devDependencies": { "@decky/rollup": "^1.0.2", "@decky/ui": "^4.11.0",
                       "@rollup/rollup-linux-x64-gnu": "^4.53.3", "typescript": "^5.6.2" },
  "scripts": { "build": "rollup -c" }
}
```

`rollup.config.mjs` 只有 3 行：
```js
import deckyPlugin from "@decky/rollup";
export default deckyPlugin({});
```

---

## 坑 2：arm64 机器装不上 x64 的 rollup 原生包

### 现象

```bash
npm install
npm error code EBADPLATFORM
npm error notsup Unsupported platform for @rollup/rollup-linux-x64-gnu@4.63.5:
  wanted {"os":"linux","cpu":"x64","libc":"glibc"}
  (current: {"os":"linux","cpu":"arm64","libc":"glibc"})
```

### 原因

参考插件的 `package.json` 写的是 `@rollup/rollup-linux-x64-gnu`（给 Steam Deck 用的，x64）。
如果在 **arm64 机器**上构建（比如手机容器），需要换成对应架构。

### 修法

```json
"@rollup/rollup-linux-arm64-gnu": "^4.53.3"
```

> rollup 4.x 把原生二进制拆成了按平台分的可选依赖，装错架构会直接 `EBADPLATFORM`。

---

## 坑 3：`jsx` 设成 `"react-jsx"` 引入 `SP_JSX`

### 现象

`tsconfig.json` 里 `"jsx": "react-jsx"` 构建出的产物使用了 **`SP_JSX`** 全局。

### 为什么是坑

对比参考插件的产物，**只有 `SP_REACT`，没有 `SP_JSX`**：
```bash
# 参考插件（已验证可用）
$ grep -oE "SP_[A-Z_]+" dist/index.js | sort -u
SP_REACT

# 我的产物
$ grep -oE "SP_[A-Z_]+" dist/index.js | sort -u
SP_JSX
SP_REACT
```

**`SP_JSX` 是 Decky 不注入的全局**（至少未经检验）⇒ 装载会崩。

### 修法

```json
"jsx": "react"        // classic，只用 SP_REACT
```

改后产物与参考插件一致。

> **一般规律**：Decky 只注入 `SP_REACT`。任何产物里出现其他 `SP_*` 全局都要警惕。

---

## 坑 4：`LD_LIBRARY_PATH` 污染导致 `/bin/bash` 崩溃

### 现象

插件面板正常，但点按钮报错：
```
开启失败: /bin/bash: symbol lookup error:
/bin/bash: undefined symbol: rl_trim_arg_from_keyseq
```

### 根因（实测复现）

Decky 用 **PyInstaller** 打包，运行时把解包目录注入 `LD_LIBRARY_PATH`：

```bash
# 实测插件子进程的环境
$ cat /proc/<bjbot-pid>/environ | tr '\0' '\n' | grep LD_LIBRARY_PATH
LD_LIBRARY_PATH=/tmp/_MEIPmBEEx

# 复现
$ LD_LIBRARY_PATH=/tmp/_MEIPmBEEx /bin/bash -c "echo ok"
/bin/bash: symbol lookup error: /bin/bash: undefined symbol: rl_trim_arg_from_keyseq

# 清空后正常
$ LD_LIBRARY_PATH="" /bin/bash -c "echo ok"
ok
```

该目录里有 PyInstaller 自带的 `libreadline`，被子进程继承后
`/bin/bash` 加载到**错误版本**。

### 修法

在任何 `subprocess` 调用前清空：

```python
def _env():
    env = os.environ.copy()
    env["PATH"] = env.get("PATH", "") + ":/usr/bin:/bin:/usr/sbin:/sbin"
    env["LD_LIBRARY_PATH"] = ""          # ★ 必须清空
    env.pop("LD_PRELOAD", None)
    return env
```

> 这个处理方式来自参考项目 `decky-wmsxwd` 的源码
> （它当年也踩了同一个坑，那行 `clean_env["LD_LIBRARY_PATH"] = ""`）。

### ★ 甄别提示

`journalctl -u plugin_loader` 里**本来就有**这类报错：
```
sh: symbol lookup error: sh: undefined symbol: rl_trim_arg_from_keyseq
```
**这与你的插件无关** —— 是 Decky 自身启动任意插件时调 `sh` 的既有现象。

**甄别方法：看时间戳**。如果最早一条出现在你安装之前，就不是你引起的。

---

## 隔离验证（装前必跑）

`verify.mjs` 在 node 里模拟 Decky 环境做 6 项检查：

```
① 全局变量检查   只用 SP_REACT，无未经检验的全局
② DFL 绑定检查   不引用 window.DFL
③ bundle 执行    无异常（patch export → globalThis.__out）
④ definePlugin   返回 title/content/icon/onDismount
⑤ 组件渲染       模拟 React 调用 Content 组件，无异常
⑥ RPC 契约       status/start/stop/logs 与后端一致
```

**⑤ 是重点** —— 坑 1 是**渲染期**才炸的，光看加载日志发现不了。

关键实现：预置 `useState` 返回值，然后**直接调用组件函数**抓渲染期异常：
```js
hookState.push(null, false, "", "");        // st, busy, msg, log
const out = registered.content.tag({});     // ← 真的渲染一次
```

---

## 部署纪律（血的教训）

1. **绝不手写 `dist/index.js`** —— 必须过 rollup
2. **装新插件前先备份插件目录**，出问题立即移出
3. **验证顺序**：装 → 重启 loader → **等 30~60 秒** → 看 QAM 是否正常
   （SteamOS 有自愈：SDDM 检测会话崩溃会自动拉起，先等）
4. **出问题第一动作**：插件移出目录 + 重启 loader，别犹豫
5. **改 `main.py` 只 kill 该插件进程**，不要动 PluginLoader
   （强杀 PluginLoader 会导致插件风暴 → 内存吃爆 → **全机黑屏**）
6. **打包时 zip 内必须保留一层插件目录**（`BJBot/plugin.json`），
   打成扁平结构会导致安装后不显示

---

## 附：一键回滚脚本

```bash
#!/bin/bash
# 移出插件 + 重启 loader + 报告健康状态
export PATH=$PATH:/usr/bin:/bin
sudo -n rm -rf /home/deck/homebrew/plugins/BJBot
sudo -n systemctl restart plugin_loader
sleep 12
echo "插件数: $(ls /home/deck/homebrew/plugins/ | wc -l)"
echo "BJBot : $(ls /home/deck/homebrew/plugins/ | grep -c BJBot)"
echo "loader: $(sudo -n systemctl is-active plugin_loader)"
echo "内存  : $(free -m | awk '/Mem:/{print $7}') MB 可用"
```

---

*本文所有坑均有实测证据；坑 1 造成了真实事故并已修复。*
