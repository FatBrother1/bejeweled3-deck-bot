import {
  definePlugin,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  staticClasses,
} from "@decky/ui";
import { callable } from "@decky/api";
import { FaPlay, FaStop, FaGamepad } from "react-icons/fa";
import React, { useEffect, useState } from "react";

// ── 后端 RPC 绑定（走 @decky/api，这才是正规做法，不是猜 window 全局）──
type Status = {
  running: boolean;
  daemon: string;
  bot: string;
  game: string;
  game_running: boolean;
  log_tail?: string;
  run2: boolean;
  // 新模式面板用的字段
  mode?: string;         // 当前游戏模式，如"禅意"
  mode_src?: string;     // 怎么认出来的: mem/img/size/...
  script?: string;       // 跑的是哪个脚本，如 "bot_v6.py"
  script_path?: string;
  script_ok?: boolean;
  daemon_script?: string;
  backend?: string;      // 识别后端: 内存/视觉
  uptime?: string;       // 已运行时长
  steps?: string;        // 已走步数
};

const getStatus = callable<[], Status>("status");
const doStart = callable<[], { ok: boolean; msg: string; status?: Status }>("start");
const doStop = callable<[], { ok: boolean; msg: string; status?: Status }>("stop");
const getLogs = callable<[number], { ok: boolean; text: string }>("logs");

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px", padding: "2px 0", gap: "8px" }}>
      <span style={{ opacity: 0.7, flexShrink: 0 }}>{label}</span>
      <span
        style={{
          fontWeight: 600, color: color ?? "#dcdedf",
          textAlign: "right", wordBreak: "break-all", minWidth: 0,
        }}
      >
        {value}
      </span>
    </div>
  );
}

// 模式名的配色：牌局单独一色（它逻辑完全不同），菜单/未知灰，其余正常
function modeColor(m?: string): string {
  if (!m || m === "—" || m === "未知") return "#8b929a";
  if (m === "牌局") return "#ffb74d";
  if (m === "菜单") return "#8b929a";
  return "#59bf40";
}

function Content() {
  const [st, setSt] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [log, setLog] = useState("");

  const refresh = async () => {
    try {
      setSt(await getStatus());
    } catch (e: any) {
      setMsg("读取状态失败: " + (e?.message ?? e));
    }
  };

  useEffect(() => {
    refresh();
    // 3 秒刷一次。模式检测要抓帧+读内存，约 0.3 秒，这个频率不碍事。
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, []);

  const act = async (fn: () => Promise<{ ok: boolean; msg: string; status?: Status }>) => {
    setBusy(true);
    setMsg("");
    try {
      const r = await fn();
      setMsg(r?.msg ?? "");
      if (r?.status) setSt(r.status);
      else await refresh();
    } catch (e: any) {
      setMsg("操作失败: " + (e?.message ?? e));
    }
    setBusy(false);
  };

  const running = !!st?.running;
  const gameOn = !!st?.game_running;
  const mode = st?.mode ?? "—";

  return (
    <>
      <PanelSection title="Bejeweled 3 自动 bot">
        <PanelSectionRow>
          <div style={{ width: "100%" }}>
            {/* 第一眼要看到的三件事：跑没跑、游戏开没开、什么模式 */}
            <Row
              label="状态"
              value={running ? (gameOn ? "运行中" : "运行中（等游戏启动）") : "未启动"}
              color={running ? "#59bf40" : "#8b929a"}
            />
            <Row
              label="现模式"
              value={gameOn ? mode : "游戏没开"}
              color={gameOn ? modeColor(mode) : "#8b929a"}
            />
            <Row label="识别方式" value={st?.backend ?? "—"} />
            <Row
              label="已走步数"
              value={running ? (st?.steps ?? "—") : "—"}
            />
            <Row label="已运行" value={running ? (st?.uptime ?? "—") : "—"} />
          </div>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy || running} onClick={() => act(doStart)}>
            {busy && !running ? "启动中…" : "开启 bot"}
          </ButtonItem>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy || !running} onClick={() => act(doStop)}>
            {busy && running ? "停止中…" : "关闭 bot"}
          </ButtonItem>
        </PanelSectionRow>

        <PanelSectionRow>
          <div style={{ fontSize: "11px", opacity: 0.6, padding: "4px 0", lineHeight: 1.5, width: "100%" }}>
            开启后常驻守护：游戏一开就自动跑，退出游戏就停。
            模式由 bot 自己认（牌局会凑同花，其它模式正常打分），不用手选。
            <br />
            重启 Deck 后失效，需要回来再点一次「开启」。
          </div>
        </PanelSectionRow>
      </PanelSection>

      {/* 装的是哪个脚本 —— 排查时最有用的一行 */}
      <PanelSection title="正在运行的脚本">
        <PanelSectionRow>
          <div style={{ width: "100%" }}>
            <Row
              label="主脚本"
              value={st ? (st.script ?? "—") + (st.script_ok === false ? "（缺失！）" : "") : "…"}
              color={st?.script_ok === false ? "#e05252" : undefined}
            />
            <Row label="守护脚本" value={st?.daemon_script ?? "—"} />
            {st?.script_path && (
              <div style={{ fontSize: "10px", opacity: 0.5, paddingTop: "2px", wordBreak: "break-all" }}>
                {st.script_path}
              </div>
            )}
          </div>
        </PanelSectionRow>
      </PanelSection>

      {msg && (
        <PanelSection>
          <PanelSectionRow>
            <div style={{ color: "#ffb74d", fontSize: "12px", padding: "4px 0", width: "100%", wordBreak: "break-all" }}>
              {msg}
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title="日志">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => {
              try {
                const r = await getLogs(12);
                setLog(r?.text ?? "（空）");
              } catch (e: any) {
                setLog("读日志失败: " + (e?.message ?? e));
              }
            }}
          >
            刷新最近日志
          </ButtonItem>
        </PanelSectionRow>
        {log && (
          <PanelSectionRow>
            <div
              style={{
                fontSize: "10px", fontFamily: "monospace", opacity: 0.75,
                whiteSpace: "pre-wrap", wordBreak: "break-all",
                maxHeight: "180px", overflow: "auto", width: "100%",
              }}
            >
              {log}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  title: <div className={staticClasses.Title}>BJBot</div>,
  content: <Content />,
  icon: <FaGamepad />,
  onDismount() {},
}));
