# Decky 插件开发的四个坑

都是实测踩出来的。第一个坑把用户的 Decky 前端搞崩了。

## 一、手写 bundle 猜全局变量

### 怎么错的

为了省事，我没编译，直接手写 `dist/index.js`，凭感觉猜了两个全局变量：

```js
const DFL = window.DFL || window.DFL_;   // 猜的，实际不存在
const React = SP_REACT;                   // 这个猜对了
```

`DFL` 不是全局变量。它是 rollup 把 `@decky/ui` 打包进来之后的局部绑定名，
只在那份 bundle 内部存在。

查参考插件的 sourcemap 就能看出来：

```
sources: ['decky://.../node_modules/@decky/api/dist/index.js',
          'decky://.../node_modules/react-icons/...',
          'decky://.../src/index.tsx']
```

### 后果

`window.DFL` 是 undefined，`DFL.definePlugin(...)` 抛异常，整个 QAM 面板
渲染失败，插件商城也打不开。

```
Error Reference: Shared SteamUI_1097
```

### 最坑的地方

加载日志显示的是成功：

```
[loader][INFO]: found plugin: BJBot
[loader][INFO]: Loaded BJBot (v0.1.0)
BJBot 插件已加载
```

这只说明后端 `main.py` 起来了。前端的错要到 Steam UI 真正渲染那个面板的时候
才会暴露出来。

所以判断插件能不能用，不能只看 loader 日志，得看 QAM 里能不能打开。

### 正确做法

```bash
npm install
npm run build
```

源码从正规的包导入：

```tsx
import { definePlugin, PanelSection, PanelSectionRow, ButtonItem, staticClasses } from "@decky/ui";
import { callable } from "@decky/api";
```

依赖版本照抄一个已经能用的插件：

```json
{
  "dependencies":    { "@decky/api": "^1.1.3", "react-icons": "^5.3.0", "tslib": "^2.7.0" },
  "devDependencies": { "@decky/rollup": "^1.0.2", "@decky/ui": "^4.11.0",
                       "@rollup/rollup-linux-x64-gnu": "^4.53.3", "typescript": "^5.6.2" },
  "scripts": { "build": "rollup -c" }
}
```

`rollup.config.mjs` 就三行：

```js
import deckyPlugin from "@decky/rollup";
export default deckyPlugin({});
```

## 二、arm64 机器装不上 x64 的 rollup

```
npm error code EBADPLATFORM
npm error notsup Unsupported platform for @rollup/rollup-linux-x64-gnu@4.63.5:
  wanted {"os":"linux","cpu":"x64","libc":"glibc"}
  (current: {"os":"linux","cpu":"arm64","libc":"glibc"})
```

参考插件的 package.json 里写的是 x64 版，那是给 Steam Deck 用的。
如果在 arm64 机器上构建，要换成：

```json
"@rollup/rollup-linux-arm64-gnu": "^4.53.3"
```

rollup 4.x 把原生二进制拆成了按平台分的可选依赖，装错架构直接报这个错。

## 三、jsx 设置引入 SP_JSX

`tsconfig.json` 里如果写 `"jsx": "react-jsx"`，构建出来的产物会用到 `SP_JSX`
这个全局。

对比一下就清楚了：

```
# 参考插件，能正常用
$ grep -oE "SP_[A-Z_]+" dist/index.js | sort -u
SP_REACT

# 我的产物
$ grep -oE "SP_[A-Z_]+" dist/index.js | sort -u
SP_JSX
SP_REACT
```

Decky 不注入 `SP_JSX`，装上会崩。

改成 classic 的 `"jsx": "react"` 就好了，产物只会有 `SP_REACT`。

一般来说 Decky 只注入 `SP_REACT`，产物里出现别的 `SP_*` 都得留个心眼。

## 四、LD_LIBRARY_PATH 污染让 bash 崩掉

面板正常了，但点按钮报错：

```
开启失败: /bin/bash: symbol lookup error:
/bin/bash: undefined symbol: rl_trim_arg_from_keyseq
```

### 原因

Decky 用 PyInstaller 打包，运行时会把解包目录塞进 `LD_LIBRARY_PATH`：

```
$ cat /proc/<pid>/environ | tr '\0' '\n' | grep LD_LIBRARY_PATH
LD_LIBRARY_PATH=/tmp/_MEIPmBEEx

$ LD_LIBRARY_PATH=/tmp/_MEIPmBEEx /bin/bash -c "echo ok"
/bin/bash: symbol lookup error: /bin/bash: undefined symbol: rl_trim_arg_from_keyseq

$ LD_LIBRARY_PATH="" /bin/bash -c "echo ok"
ok
```

那个目录里有 PyInstaller 自带的 libreadline，被子进程继承之后 bash 加载到错版本。

### 修法

调 subprocess 之前清掉：

```python
def _env():
    env = os.environ.copy()
    env["PATH"] = env.get("PATH", "") + ":/usr/bin:/bin:/usr/sbin:/sbin"
    env["LD_LIBRARY_PATH"] = ""
    env.pop("LD_PRELOAD", None)
    return env
```

这个处理方式是从参考项目 decky-wmsxwd 的源码里学到的，它踩过同一个坑。

### 顺带说一个甄别

`journalctl -u plugin_loader` 里本来就有这类报错：

```
sh: symbol lookup error: sh: undefined symbol: rl_trim_arg_from_keyseq
```

这跟你的插件没关系，是 Decky 自己启动别的插件时调 sh 的既有现象。

判断方法看时间戳。如果最早一条出现在你安装之前，那就不是你引起的。

## 装之前先验证

`verify.mjs` 在 node 里模拟 Decky 环境，做六项检查：

```
① 全局变量检查   只用 SP_REACT
② DFL 绑定检查   不引用 window.DFL
③ bundle 执行    无异常
④ definePlugin   返回 title/content/icon/onDismount
⑤ 组件渲染       真的调用一次组件函数
⑥ RPC 契约       status/start/stop/logs 和后端对得上
```

第五项是关键。第一个坑就是渲染期才炸的，光看加载日志发现不了。

实现上是先给 `useState` 预置返回值，然后直接调组件：

```js
hookState.push(null, false, "", "");
const out = registered.content.tag({});
```

## 部署的时候注意

别手写 `dist/index.js`，一定要过 rollup。

装新插件之前先备份插件目录，出问题立刻移出去。

验证顺序是装完重启 loader，等半分钟，看 QAM 能不能打开。SteamOS 有自愈，
SDDM 检测到会话崩溃会自己把 session 拉起来，所以先等一下。

出问题的第一件事就是把插件移出目录再重启 loader，别犹豫。

改 `main.py` 只要 kill 那个插件进程就行了，不要去动 PluginLoader。强杀
PluginLoader 会导致插件风暴，内存吃爆，全机黑屏。

打包的时候 zip 里要保留一层插件目录（`BJBot/plugin.json`），打成扁平的
结构装上会不显示。

## 回滚脚本

```bash
#!/bin/bash
export PATH=$PATH:/usr/bin:/bin
sudo -n rm -rf /home/deck/homebrew/plugins/BJBot
sudo -n systemctl restart plugin_loader
sleep 12
echo "插件数: $(ls /home/deck/homebrew/plugins/ | wc -l)"
echo "BJBot : $(ls /home/deck/homebrew/plugins/ | grep -c BJBot)"
echo "loader: $(sudo -n systemctl is-active plugin_loader)"
echo "内存  : $(free -m | awk '/Mem:/{print $7}') MB 可用"
```
