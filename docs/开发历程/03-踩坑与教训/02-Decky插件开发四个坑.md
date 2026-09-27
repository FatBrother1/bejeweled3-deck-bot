# Decky 插件开发的四个坑

这四个都是我自己踩出来的，第一个把用户的 Decky 前端搞崩了。

## 一、手写 bundle 猜全局变量

现象：装上手写的 `dist/index.js`，Decky 侧边栏整个渲染失败，报
`Error Reference: Shared SteamUI_1097`，连插件商城也打不开。

根因：我没编译，凭目测猜了两个全局变量。`const DFL = window.DFL || window.DFL_`
是错的 —— `DFL` 是 rollup 把 `@decky/ui` 打进来之后的局部绑定名，只在那份 bundle
内部存在；`window.DFL` 是 undefined，`DFL.definePlugin(...)` 抛异常，整棵 React 树
跟着崩。`const React = SP_REACT` 倒是猜对了。查参考插件的 sourcemap 就能看出来，
sources 里能看到 `@decky/ui` 的 dist 被打了进来。

最骗人的一点：加载日志显示成功。`found plugin` / `Loaded BJBot` 只证明后端 main.py
起来了，前端的错要等 Steam UI 真渲染那个面板才暴露。

现在：源码从正规包导入（`@decky/ui` / `@decky/api`），`npm install` + `npm run build`
（rollup -c），依赖版本照抄一个已经能用的插件，`rollup.config.mjs` 只有三行。

## 二、arm64 机器装 x64 的 rollup

现象是 `npm error code EBADPLATFORM`，说 `@rollup/rollup-linux-x64-gnu` 要 x64。
根因：参考插件的 package.json 写的是 x64 版，那是给 Deck 用的；本机容器是 aarch64
（`uname -m` → aarch64，`node -p process.arch` → arm64）。rollup 4.x 把原生二进制
拆成了按平台分的可选依赖，装错架构直接报错。现在本机构建换成
`@rollup/rollup-linux-arm64-gnu`。

## 三、jsx 设置引入 SP_JSX

现象：`tsconfig.json` 写 `"jsx": "react-jsx"` 时，产物里出现 `SP_JSX` 这个全局。
根因：Decky 只注入 `SP_REACT`，不注入 `SP_JSX`。对照参考插件的产物，
`grep -oE "SP_[A-Z_]+"` 只有 `SP_REACT`，我那份多一个，装上会崩。
现在改成 classic 的 `"jsx": "react"`，产物只剩 `SP_REACT`。
一般来说产物里出现 `SP_REACT` 以外的 `SP_*` 都得留个心眼。

## 四、LD_LIBRARY_PATH 污染让 bash 崩掉

现象：面板正常了，点「开启 bot」报 `/bin/bash: symbol lookup error:
undefined symbol: rl_trim_arg_from_keyseq`。

根因：Decky 用 PyInstaller 打包，运行时把解包目录 `/tmp/_MEIxxxxxx` 塞进
`LD_LIBRARY_PATH`；那目录里有 PyInstaller 自带的 libreadline，子进程继承之后
bash 加载到错版本。实测复现：带污染变量跑 `/bin/bash -c "echo ok"` 崩，清空立即正常。

现在：`main.py` 的 `_env()` 里 `env["LD_LIBRARY_PATH"] = ""` 并 pop 掉 `LD_PRELOAD`。
这招是从 decky-wmsxwd 的源码里学来的，它踩过同一个坑。
顺带一个甄别：`journalctl -u plugin_loader` 里本来就有 `sh: symbol lookup error`，
最早一条出现在我安装之前，判断是不是自己引起的看时间戳。

## 装之前先验证，出问题先撤

`verify.mjs` 在 node 里模拟 Decky 环境做六项检查：全局变量、DFL 绑定、bundle 执行、
definePlugin 返回值、组件渲染、RPC 契约。第五项最关键，第一个坑就是渲染期才炸的，
光看加载日志发现不了。部署纪律：别手写 dist；装前备份插件目录；装完重启 loader
等半分钟再看 QAM 能不能开；出问题的第一动作是把插件移出目录再重启 loader。
改 main.py 只 kill 那个插件进程，别动 PluginLoader（强杀会引发插件风暴，
内存吃爆，全机黑屏）。zip 里要保留一层插件目录（`BJBot/plugin.json`），
打成扁平的装上不显示。
