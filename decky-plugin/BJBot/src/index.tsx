import {
  definePlugin,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  staticClasses,
} from "@decky/ui";
import { callable } from "@decky/api";
import { FaPlay, FaStop, FaTerminal, FaGamepad } from "react-icons/fa";
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
};

const getStatus = callable<[], Status>("status");
const doStart = callable<[], { ok: boolean; msg: string; status?: Status }>("start");
const doStop = callable<[], { ok: boolean; msg: string; status?: Status }>("stop");
const getLogs = callable<[number], { ok: boolean; text: string }>("logs");

function Line({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px", padding: "2px 0" }}>
      <span style={{ opacity: 0.7 }}>{label}</span>
      <span style={{ fontWeight: 600, color: color ?? "#dcdedf" }}>{value}</span>
    </div>
  );
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
  const game = !!st?.game_running;

  return (
    <>
      <PanelSection title="Bejeweled 3 自动 bot">
        <PanelSectionRow>
          <div style={{ width: "100%" }}>
            <Line label="bot" value={running ? "● 运行中" : "○ 已停止"} color={running ? "#59bf40" : "#8b929a"} />
            <Line label="游戏" value={game ? "运行中" : "未运行"} color={game ? "#59bf40" : "#8b929a"} />
            <Line label="守护" value={st ? (st.daemon === "active" ? "已启用" : "未启用") : "…"} />
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
            <br />
            重启 Deck 后失效，需重新点一次「开启」。
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
