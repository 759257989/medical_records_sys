// frontend/src/components/ApprovalPanel.tsx
//
// 人审闸门面板：图在 human_approval 节点 interrupt() 暂停后，前端拿到低置信编码列表，
// 让医生逐条勾选"保留/驳回"。提交时调 /approve，服务端 Command(resume=...) 从断点恢复，
// 接着把剩余的 step / done 事件继续推过来 —— 这里用 onEvent 把它们转交给父组件渲染。
import { useState } from "react";
import { streamAgent, type AgentEvent, type CodeHit } from "../api/stream";

type Props = {
  runId: string;                       // run_started 给的 id，恢复时定位 Postgres 里的 checkpoint
  codes: CodeHit[];                    // 待审的低置信编码
  draft: string;                       // 当前草稿（供医生对照判断）
  onEvent: (ev: AgentEvent) => void;   // 把恢复后的事件回传给父组件（继续画时间线 / 终稿）
  onError: (message: string) => void;  // 网络/流错误上报
};

export default function ApprovalPanel({ runId, codes, draft, onEvent, onError }: Props) {
  // 默认全部保留；医生取消勾选的即视为驳回
  const [keep, setKeep] = useState<Set<string>>(() => new Set(codes.map((c) => c.code)));
  const [submitting, setSubmitting] = useState(false);

  const toggle = (code: string) =>
    setKeep((s) => {
      const next = new Set(s);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  // 医生勾选要保留的编码，提交后服务端 Command(resume) 接着跑完，再继续读 SSE
  const submit = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      await streamAgent(`/agent/runs/${runId}/approve`, { approved: [...keep] }, onEvent);
    } catch (e) {
      onError((e as Error).message);
      setSubmitting(false);   // 失败时让医生能重试；成功时父组件会卸载本面板
    }
  };

  return (
    <div className="notice warning" style={{ display: "block" }}>
      <p><strong>Review low-confidence codes</strong></p>
      <p className="muted">Uncheck any code that should not be included, then continue.</p>

      <ul className="icd-hits">
        {codes.map((c) => (
          <li key={c.code} onClick={() => toggle(c.code)} title="Click to keep / drop">
            <input type="checkbox" readOnly checked={keep.has(c.code)} />
            <code>{c.code}</code>
            <span className="desc">{c.description || "—"}</span>
          </li>
        ))}
      </ul>

      {draft && (
        <details>
          <summary className="muted">View draft</summary>
          <pre className="generated" style={{ whiteSpace: "pre-wrap" }}>{draft}</pre>
        </details>
      )}

      <button className="primary" disabled={submitting} onClick={submit}>
        {submitting ? "Resuming…" : "Approve & Continue"}
      </button>
    </div>
  );
}
