// frontend/src/api/stream.ts
// 用 fetch + ReadableStream 消费后端的 SSE 流。
// 为什么不用我们已有的 axios（client.ts）？因为浏览器里的 axios 不擅长“边下边读”响应体，
// 而 fetch 的 res.body.getReader() 天生支持流式读取。所以这里单独写一个。

export async function streamSoap(
  encounterId: string,
  transcript: string,
  onText: (fullText: string) => void,   // 每收到新内容就回调一次（传累积全文）
): Promise<void> {
  const token = localStorage.getItem("token");

  const res = await fetch(`/api/encounters/${encounterId}/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,   // 手动带 token（fetch 不走 axios 拦截器）
    },
    body: JSON.stringify({ transcript }),
  });

  // 因为绕过了 axios 拦截器，这里要自己处理 401（会话过期）
  if (res.status === 401) {
    localStorage.removeItem("token");
    location.href = "/login";
    return;
  }
  if (!res.ok || !res.body) throw new Error(`generate failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";   // 存放还没凑齐成完整帧的残片
  let full = "";     // 累积的全文

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");   // SSE 帧以空行分隔
    buffer = frames.pop() ?? "";           // 最后一段可能不完整，留到下次

    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      const payload = JSON.parse(line.slice(5).trim());
      if (payload.error) throw new Error(payload.error);
      if (payload.t) {
        full += payload.t;
        onText(full);    // 把累积全文交给页面去解析渲染
      }
      // payload.done 时自然走到流结束
    }
  }
}