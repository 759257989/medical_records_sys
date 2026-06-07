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

  if (res.status === 401) {        // fetch 不走 axios 拦截器，手动处理会话过期
    localStorage.removeItem("token");
    location.href = "/login";
    return;
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