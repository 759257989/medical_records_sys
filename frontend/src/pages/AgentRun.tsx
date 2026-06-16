// frontend/src/pages/AgentRun.tsx
//
// Chart-review Agent 页面：开跑 → 逐节点渲染进度 → 撞到低置信编码就弹审批面板 → 终稿。
// 全程消费后端 SSE 事件流（见 api/stream.ts 的 streamAgent）。
//
// 路由：/agent?id=<encounterId>（沿用 EncounterWorkspace 的 ?id= 约定）。
// 后端契约：
//   POST /agent/encounters/{id}/runs   {transcript}            → run_started / step / approval_required / done
//   POST /agent/runs/{runId}/approve   {approved: string[]}    → step / done（从断点恢复）
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../api/client";
import { streamAgent, type AgentEvent, type CodeHit } from "../api/stream";
import { useAuth } from "../auth/AuthContext";
import ApprovalPanel from "../components/ApprovalPanel";

// 节点机器名 → 给医生看的友好文案
const NODE_LABEL: Record<string, string> = {
  plan: "Planning review path",
  retrieve_history: "Retrieving prior history",
  retrieve_icd: "Searching ICD-10 candidates",
  draft: "Drafting SOAP note",
  self_critique: "Self-reviewing the draft",
  assign_codes: "Assigning ICD-10 codes",
  human_approval: "Awaiting clinician approval",
  finalize: "Finalizing note",
};

type TimelineItem = { node: string; detail: string };

// 把一条 step 事件压成一句话，挂到时间线上
function describeStep(ev: Extract<AgentEvent, { type: "step" }>): string {
  if (ev.n_candidates !== undefined) return `${ev.n_candidates} candidate code(s) found`;
  if (ev.n_history !== undefined) return `${ev.n_history} prior note(s) loaded`;
  if (ev.codes?.length) return `Codes: ${ev.codes.join(", ")}`;
  if (ev.revisions !== undefined && ev.revisions > 0) return `Revision #${ev.revisions}`;
  return "";
}

export default function AgentRun() {
  const { user, logout } = useAuth();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const encounterId = params.get("id");

  const [transcript, setTranscript] = useState("");
  const [running, setRunning] = useState(false);          // 流是否正在推进（用于禁用按钮）
  const [runId, setRunId] = useState("");                 // run_started 给的 id，审批时要用
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [approval, setApproval] = useState<{ codes: CodeHit[]; draft: string } | null>(null);
  const [finalNote, setFinalNote] = useState("");
  const [approvedCodes, setApprovedCodes] = useState<CodeHit[]>([]);
  const [error, setError] = useState("");

  // 进页面时若带了 ?id=，自动把该就诊的转录拉来预填
  useEffect(() => {
    if (!encounterId) return;
    api.get(`/encounters/${encounterId}`)
      .then((r) => setTranscript(r.data.transcript || ""))
      .catch(() => {});
  }, [encounterId]);

  // 所有 SSE 事件的统一处理（开跑与恢复共用）
  const handleEvent = (ev: AgentEvent) => {
    switch (ev.type) {
      case "run_started":
        setRunId(ev.run_id);
        break;
      case "step":
        setTimeline((t) => [...t, { node: ev.node, detail: describeStep(ev) }]);
        break;
      case "approval_required":
        // 撞到人审闸门：图已暂停（状态存进 Postgres），展示面板等医生决定
        setApproval({ codes: ev.low_confidence_codes, draft: ev.draft });
        setRunning(false);
        break;
      case "done":
        setApproval(null);            // 恢复跑完 → 收起审批面板
        setFinalNote(ev.final_note);  // 展示终稿，等医生手动点"返回编辑器"再回填
        setApprovedCodes(ev.approved_codes);
        setRunning(false);
        break;
      case "error":
        setError(ev.message);
        setRunning(false);
        break;
      // stream_end：流的收尾标记，无需处理
    }
  };

  // 开跑：清空上一轮，发起 /runs 流
  const run = async () => {
    if (!encounterId || !transcript.trim() || running) return;
    setRunning(true);
    setTimeline([]); setApproval(null); setFinalNote(""); setApprovedCodes([]);
    setError(""); setRunId("");
    try {
      await streamAgent(`/agent/encounters/${encounterId}/runs`, { transcript }, handleEvent);
    } catch (e) {
      setError((e as Error).message);
      setRunning(false);
    }
  };

  // 医生手动点击才返回工作台，并把 Copilot 终稿带回去填充 SOAP 编辑器
  const returnToEditor = () => {
    if (encounterId) nav(`/encounter?id=${encounterId}`, { state: { agentNote: finalNote } });
  };

  if (!encounterId) {
    return (
      <div className="page">
        <Topbar user={user} logout={logout} />
        <main className="content">
          <div className="card wide">
            <h2>Copilot Review</h2>
            <p className="hint">Open this page from an encounter to run the agent.</p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="page">
      <Topbar user={user} logout={logout} />
      <main className="workspace">
        {/* 左：转录 + 开跑 */}
        <section className="panel">
          <div className="panel-head"><h3>Transcript</h3></div>
          <textarea className="transcript" rows={18}
            placeholder="Paste the visit transcript…"
            value={transcript} onChange={(e) => setTranscript(e.target.value)} />
          <div className="row-between">
            <span className="muted">Multi-step review with human approval</span>
            <button className="primary" disabled={running || !transcript.trim()} onClick={run}>
              {running ? "Running…" : "Run Copilot Review"}
            </button>
          </div>
          {error && (
            <div className="notice error"><span className="ico">!</span><span>{error}</span></div>
          )}
        </section>

        {/* 中：Copilot 终稿 + 手动返回 + 低置信编码审批 */}
        <section className="panel">
          <div className="panel-head"><h3>Copilot Note</h3></div>

          {/* 审批闸门：暂停时出现，医生逐条勾选保留/驳回低置信编码 */}
          {approval && (
            <ApprovalPanel
              runId={runId}
              codes={approval.codes}
              draft={approval.draft}
              onEvent={handleEvent}
              onError={setError}
            />
          )}

          {!finalNote && !approval && (
            <p className="muted">Copilot note appears here once the review completes.</p>
          )}

          {finalNote && (
            <>
              <pre className="generated" style={{ whiteSpace: "pre-wrap" }}>{finalNote}</pre>
              <h4>Approved codes</h4>
              <ul className="icd-hits">
                {approvedCodes.map((c) => (
                  <li key={c.code}>
                    <code>{c.code}</code>
                    {c.low_confidence && <span className="badge">low</span>}
                  </li>
                ))}
              </ul>
              {/* 右下角：医生确认 → 回工作台并回填 SOAP（不点不跳转） */}
              <div className="row-between">
                <span className="muted">Confirm to fill the SOAP note in the editor</span>
                <button className="primary" onClick={returnToEditor}>Confirm</button>
              </div>
            </>
          )}
        </section>

        {/* 右：执行时间线（紧凑，靠右） */}
        <aside className="panel narrow">
          <div className="panel-head"><h3>Agent Timeline</h3></div>
          {timeline.length === 0 && <p className="muted">No steps yet.</p>}
          <ul className="versions">
            {timeline.map((item, i) => (
              <li key={i}>
                <strong>{NODE_LABEL[item.node] ?? item.node}</strong>
                {item.detail && <span className="vmeta">{item.detail}</span>}
              </li>
            ))}
          </ul>
        </aside>
      </main>
    </div>
  );
}

type TopbarUser = { first_name?: string; last_name?: string; role?: string } | null;

function Topbar({ user, logout }: { user: TopbarUser; logout: () => void }) {
  const nav = useNavigate();
  return (
    <header className="topbar">
      <img className="brand-logo" src="/mednotecopilot.png" alt="MedNote Copilot" onClick={() => nav("/")} />
      <button className="ghost" onClick={() => nav("/")}>Dashboard</button>
      <span className="user">
        {user?.first_name} {user?.last_name}
        <span className="role">{user?.role}</span>
      </span>
      <button className="ghost" onClick={logout}>Sign out</button>
    </header>
  );
}
