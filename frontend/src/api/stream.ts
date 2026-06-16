// frontend/src/api/stream.ts
// 消费后端 SSE“事件流”。每帧是 {type, ...}：
//   {type:"text", content}  正文增量
//   {type:"tool", label}    工具被调用提示
//   {type:"error", message} 出错
//   {type:"done"}           结束

type StreamHandlers = {
  onText: (fullText: string) => void;     // 传累积全文
  onTool?: (label: string) => void;       // 工具调用提示
};

export async function streamSoap(
  encounterId: string,
  transcript: string,
  handlers: StreamHandlers,
): Promise<void> {
  const token = localStorage.getItem("token");

  const res = await fetch(`/api/encounters/${encounterId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ transcript }),
  });

  if (res.status === 401) {        // fetch bypasses the axios interceptor, so mirror the same logic here
    // Same as the interceptor: no hard redirect — broadcast the event so AuthContext shows the
    // in-place re-login modal, preserving the transcript/draft the provider is editing.
    localStorage.removeItem("token");
    window.dispatchEvent(new CustomEvent("session-expired"));
    throw new Error("Your session has expired. Please sign in again.");
  }
  if (!res.ok || !res.body) throw new Error(`generate failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";   // 残片留到下次

    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      const ev = JSON.parse(line.slice(5).trim());
      if (ev.type === "error") throw new Error(ev.message);
      if (ev.type === "tool") handlers.onTool?.(ev.label);
      if (ev.type === "text") { full += ev.content; handlers.onText(full); }
      // ev.type === "done" 时循环自然结束
    }
  }
}

// ── Agent 事件流 ────────────────────────────────────────────────────────────────
// chart-review agent 的 SSE 比上面的 SOAP 流复杂：节点进度、审批闸门、终稿都走同一条流。
// 这里只负责"把字节流切成一个个 JSON 事件并回调"，具体怎么渲染由页面决定。
export type CodeHit = { code: string; confidence: number | null; low_confidence: boolean };

export type AgentEvent =
  | { type: "run_started"; run_id: string }
  | {
      type: "step";
      node: string;
      updated: string[];
      n_candidates?: number;
      n_history?: number;
      revisions?: number;
      codes?: string[];
    }
  | { type: "approval_required"; low_confidence_codes: CodeHit[]; draft: string }
  | { type: "done"; final_note: string; approved_codes: CodeHit[] }
  | { type: "error"; message: string }
  | { type: "stream_end" };

// POST 一个 JSON body，逐事件回调。开跑(/runs)与恢复(/runs/{id}/approve)共用这一个函数。
export async function streamAgent(
  path: string,                                   // 形如 "/agent/encounters/<id>/runs"
  body: unknown,
  onEvent: (ev: AgentEvent) => void,
): Promise<void> {
  const token = localStorage.getItem("token");

  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });

  if (res.status === 401) {                       // 与 axios 拦截器保持一致：就地重登，不硬跳转
    localStorage.removeItem("token");
    window.dispatchEvent(new CustomEvent("session-expired"));
    throw new Error("Your session has expired. Please sign in again.");
  }
  if (!res.ok || !res.body) throw new Error(`agent run failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";                  // 半截帧留到下一轮再拼

    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      const ev = JSON.parse(line.slice(5).trim()) as AgentEvent;
      onEvent(ev);                                // error / approval 等业务判断交给页面
    }
  }
}