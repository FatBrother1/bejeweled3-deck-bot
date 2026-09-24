const manifest = {"name":"BJBot"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized. This is likely a bug in Decky Loader.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version 1. Some features may not work.`);
}
if (api._version != API_VERSION) {
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version ${api._version}. Some features may not work.`);
}
const callable = api.callable;

var DefaultContext = {
  color: undefined,
  size: undefined,
  className: undefined,
  style: undefined,
  attr: undefined
};
var IconContext = SP_REACT.createContext && /*#__PURE__*/SP_REACT.createContext(DefaultContext);

var _excluded = ["attr", "size", "title"];
function _objectWithoutProperties(e, t) { if (null == e) return {}; var o, r, i = _objectWithoutPropertiesLoose(e, t); if (Object.getOwnPropertySymbols) { var n = Object.getOwnPropertySymbols(e); for (r = 0; r < n.length; r++) o = n[r], -1 === t.indexOf(o) && {}.propertyIsEnumerable.call(e, o) && (i[o] = e[o]); } return i; }
function _objectWithoutPropertiesLoose(r, e) { if (null == r) return {}; var t = {}; for (var n in r) if ({}.hasOwnProperty.call(r, n)) { if (-1 !== e.indexOf(n)) continue; t[n] = r[n]; } return t; }
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), true).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: true, configurable: true, writable: true }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == typeof i ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != typeof t || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r); if ("object" != typeof i) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function Tree2Element(tree) {
  return tree && tree.map((node, i) => /*#__PURE__*/SP_REACT.createElement(node.tag, _objectSpread({
    key: i
  }, node.attr), Tree2Element(node.child)));
}
function GenIcon(data) {
  return props => /*#__PURE__*/SP_REACT.createElement(IconBase, _extends({
    attr: _objectSpread({}, data.attr)
  }, props), Tree2Element(data.child));
}
function IconBase(props) {
  var elem = conf => {
    var attr = props.attr,
      size = props.size,
      title = props.title,
      svgProps = _objectWithoutProperties(props, _excluded);
    var computedSize = size || conf.size || "1em";
    var className;
    if (conf.className) className = conf.className;
    if (props.className) className = (className ? className + " " : "") + props.className;
    return /*#__PURE__*/SP_REACT.createElement("svg", _extends({
      stroke: "currentColor",
      fill: "currentColor",
      strokeWidth: "0"
    }, conf.attr, attr, svgProps, {
      className: className,
      style: _objectSpread(_objectSpread({
        color: props.color || conf.color
      }, conf.style), props.style),
      height: computedSize,
      width: computedSize,
      xmlns: "http://www.w3.org/2000/svg"
    }), title && /*#__PURE__*/SP_REACT.createElement("title", null, title), props.children);
  };
  return IconContext !== undefined ? /*#__PURE__*/SP_REACT.createElement(IconContext.Consumer, null, conf => elem(conf)) : elem(DefaultContext);
}

// THIS FILE IS AUTO GENERATED
function FaGamepad (props) {
  return GenIcon({"attr":{"viewBox":"0 0 640 512"},"child":[{"tag":"path","attr":{"d":"M480.07 96H160a160 160 0 1 0 114.24 272h91.52A160 160 0 1 0 480.07 96zM248 268a12 12 0 0 1-12 12h-52v52a12 12 0 0 1-12 12h-24a12 12 0 0 1-12-12v-52H84a12 12 0 0 1-12-12v-24a12 12 0 0 1 12-12h52v-52a12 12 0 0 1 12-12h24a12 12 0 0 1 12 12v52h52a12 12 0 0 1 12 12zm216 76a40 40 0 1 1 40-40 40 40 0 0 1-40 40zm64-96a40 40 0 1 1 40-40 40 40 0 0 1-40 40z"},"child":[]}]})(props);
}

const getStatus = callable("status");
const doStart = callable("start");
const doStop = callable("stop");
const getLogs = callable("logs");
function Line({ label, value, color }) {
    return (SP_REACT.createElement("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "13px", padding: "2px 0" } },
        SP_REACT.createElement("span", { style: { opacity: 0.7 } }, label),
        SP_REACT.createElement("span", { style: { fontWeight: 600, color: color ?? "#dcdedf" } }, value)));
}
function Content() {
    const [st, setSt] = SP_REACT.useState(null);
    const [busy, setBusy] = SP_REACT.useState(false);
    const [msg, setMsg] = SP_REACT.useState("");
    const [log, setLog] = SP_REACT.useState("");
    const refresh = async () => {
        try {
            setSt(await getStatus());
        }
        catch (e) {
            setMsg("读取状态失败: " + (e?.message ?? e));
        }
    };
    SP_REACT.useEffect(() => {
        refresh();
        const t = setInterval(refresh, 3000);
        return () => clearInterval(t);
    }, []);
    const act = async (fn) => {
        setBusy(true);
        setMsg("");
        try {
            const r = await fn();
            setMsg(r?.msg ?? "");
            if (r?.status)
                setSt(r.status);
            else
                await refresh();
        }
        catch (e) {
            setMsg("操作失败: " + (e?.message ?? e));
        }
        setBusy(false);
    };
    const running = !!st?.running;
    const game = !!st?.game_running;
    return (SP_REACT.createElement(SP_REACT.Fragment, null,
        SP_REACT.createElement(DFL.PanelSection, { title: "Bejeweled 3 \u81EA\u52A8 bot" },
            SP_REACT.createElement(DFL.PanelSectionRow, null,
                SP_REACT.createElement("div", { style: { width: "100%" } },
                    SP_REACT.createElement(Line, { label: "bot", value: running ? "● 运行中" : "○ 已停止", color: running ? "#59bf40" : "#8b929a" }),
                    SP_REACT.createElement(Line, { label: "\u6E38\u620F", value: game ? "运行中" : "未运行", color: game ? "#59bf40" : "#8b929a" }),
                    SP_REACT.createElement(Line, { label: "\u5B88\u62A4", value: st ? (st.daemon === "active" ? "已启用" : "未启用") : "…" }))),
            SP_REACT.createElement(DFL.PanelSectionRow, null,
                SP_REACT.createElement(DFL.ButtonItem, { layout: "below", disabled: busy || running, onClick: () => act(doStart) }, busy && !running ? "启动中…" : "开启 bot")),
            SP_REACT.createElement(DFL.PanelSectionRow, null,
                SP_REACT.createElement(DFL.ButtonItem, { layout: "below", disabled: busy || !running, onClick: () => act(doStop) }, busy && running ? "停止中…" : "关闭 bot")),
            SP_REACT.createElement(DFL.PanelSectionRow, null,
                SP_REACT.createElement("div", { style: { fontSize: "11px", opacity: 0.6, padding: "4px 0", lineHeight: 1.5, width: "100%" } },
                    "\u5F00\u542F\u540E\u5E38\u9A7B\u5B88\u62A4\uFF1A\u6E38\u620F\u4E00\u5F00\u5C31\u81EA\u52A8\u8DD1\uFF0C\u9000\u51FA\u6E38\u620F\u5C31\u505C\u3002",
                    SP_REACT.createElement("br", null),
                    "\u91CD\u542F Deck \u540E\u5931\u6548\uFF0C\u9700\u91CD\u65B0\u70B9\u4E00\u6B21\u300C\u5F00\u542F\u300D\u3002"))),
        msg && (SP_REACT.createElement(DFL.PanelSection, null,
            SP_REACT.createElement(DFL.PanelSectionRow, null,
                SP_REACT.createElement("div", { style: { color: "#ffb74d", fontSize: "12px", padding: "4px 0", width: "100%", wordBreak: "break-all" } }, msg)))),
        SP_REACT.createElement(DFL.PanelSection, { title: "\u65E5\u5FD7" },
            SP_REACT.createElement(DFL.PanelSectionRow, null,
                SP_REACT.createElement(DFL.ButtonItem, { layout: "below", onClick: async () => {
                        try {
                            const r = await getLogs(12);
                            setLog(r?.text ?? "（空）");
                        }
                        catch (e) {
                            setLog("读日志失败: " + (e?.message ?? e));
                        }
                    } }, "\u5237\u65B0\u6700\u8FD1\u65E5\u5FD7")),
            log && (SP_REACT.createElement(DFL.PanelSectionRow, null,
                SP_REACT.createElement("div", { style: {
                        fontSize: "10px", fontFamily: "monospace", opacity: 0.75,
                        whiteSpace: "pre-wrap", wordBreak: "break-all",
                        maxHeight: "180px", overflow: "auto", width: "100%",
                    } }, log))))));
}
var index = DFL.definePlugin(() => ({
    title: SP_REACT.createElement("div", { className: DFL.staticClasses.Title }, "BJBot"),
    content: SP_REACT.createElement(Content, null),
    icon: SP_REACT.createElement(FaGamepad, null),
    onDismount() { },
}));

export { index as default };
//# sourceMappingURL=index.js.map
