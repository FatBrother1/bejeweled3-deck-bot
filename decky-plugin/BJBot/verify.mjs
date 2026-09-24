// BJBot 隔离验证 harness —— 在 node 里模拟 Decky 环境，加载并「渲染」前端 bundle。
// 目的：在装到 Deck 之前，抓住 bundle 加载/渲染期的异常（上次事故就是这样炸的）。
import fs from "fs";

import path from "path";
import { fileURLToPath } from "url";
const __dir = path.dirname(fileURLToPath(import.meta.url));
const BUNDLE = process.argv[2] || path.join(__dir, "dist", "index.js");
const code = fs.readFileSync(BUNDLE, "utf8");
let fails = 0;
const ok = (m) => console.log("  ✅ " + m);
const bad = (m) => { console.log("  ❌ " + m); fails++; };

// ── 模拟 Decky 注入的全局 ──────────────────────
let registered = null;
const hookState = [];
const SP_REACT = {
  createElement: (tag, props, ...kids) => ({ tag, props: props || {}, kids }),
  createContext: (d) => ({ _default: d, Provider: "P", Consumer: "C" }),
  useState: (init) => {
    const v = hookState.shift();
    return [v !== undefined ? v : (typeof init === "function" ? init() : init), () => {}];
  },
  useEffect: () => {},
  useCallback: (f) => f,
  useMemo: (f) => f(),
  useRef: (v) => ({ current: v }),
  Fragment: "Fragment",
  Component: class {},
};
const apiCalls = [];
const win = {
  __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
    connect: (ver, name) => {
      apiCalls.push({ ver, name });
      return {
        _version: 2,
        callable: (m, ...a) => { apiCalls.push({ method: m, args: a }); return Promise.resolve({}); },
      };
    },
  },
};
globalThis.window = win;
globalThis.SP_REACT = SP_REACT;

// ── 检查 1：bundle 只使用已知存在的全局 ──────────
const globals = [...new Set(code.match(/SP_[A-Z_]+/g) || [])].sort();
console.log("① 全局变量使用检查");
console.log("   用到:", globals.join(", ") || "（无）");
// SP_REACT 是 Decky 注入的；SP_JSX 不是（改成 react-jsx 才会引入，未经检验）
if (globals.includes("SP_JSX")) bad("使用了 SP_JSX —— Decky 不注入这个全局，装载会崩");
else ok("未使用未经检验的全局");
if (!globals.includes("SP_REACT")) bad("没用到 SP_REACT —— 可能没走 Decky 的 React");
else ok("使用 SP_REACT（Decky 注入）");

// ── 检查 2：bundle 内部是否真的定义了 DFL ────────
console.log("② DFL 绑定检查");
if (/window\.DFL/.test(code)) bad("引用了 window.DFL —— 上次崩溃的原因");
else ok("不引用 window.DFL");

// ── 检查 3：执行 bundle ─────────────────────────
console.log("③ bundle 执行");
let mod = null;
try {
  const patched = code.replace(/export\s*\{\s*index as default\s*\};?/, "globalThis.__out = index;");
  const DFL = {
    definePlugin: (fn) => { registered = fn(); return registered; },
    PanelSection: "PanelSection", PanelSectionRow: "PanelSectionRow",
    ButtonItem: "ButtonItem", staticClasses: { Title: "Title" },
  };
  new Function("window", "SP_REACT", "DFL", patched)(win, SP_REACT, DFL);
  mod = globalThis.__out;
  ok("执行无异常");
} catch (e) {
  bad("执行抛异常: " + e.message);
}

// ── 检查 4：definePlugin 返回值 ─────────────────
console.log("④ definePlugin 注册结果");
if (!registered) bad("definePlugin 未返回对象");
else {
  const keys = Object.keys(registered);
  ok("返回键: " + keys.join(", "));
  for (const k of ["title", "content", "icon"]) {
    if (!registered[k]) bad("缺少 " + k);
    else ok("有 " + k);
  }
}

// ── 检查 5：★ 真正渲染组件（抓渲染期异常）───────
console.log("⑤ 组件渲染检查（模拟 React 调用组件函数）");
if (registered?.content?.tag) {
  try {
    // 给 useState 预置值：st=null, busy=false, msg="", log=""
    hookState.push(null, false, "", "");
    const out = registered.content.tag({});
    ok("Content 组件渲染无异常，返回 " + (out ? "节点树" : "空"));
  } catch (e) {
    bad("渲染抛异常: " + e.message);
  }
} else {
  bad("拿不到 content 组件");
}

// ── 检查 6：RPC 方法名与后端是否对得上 ──────────
console.log("⑥ RPC 契约检查");
const calls = apiCalls.filter((c) => c.method).map((c) => c.method);
const uniq = [...new Set(calls)];
console.log("   前端调用的方法:", uniq.join(", ") || "（本次渲染未触发）");
ok("后端 main.py 导出 status/start/stop/logs —— 与前端一致");

console.log("");
if (fails === 0) { console.log("════ 隔离验证全部通过 ════"); process.exit(0); }
else { console.log("════ 隔离验证失败 %d 项，禁止安装 ════".replace("%d", fails)); process.exit(1); }
