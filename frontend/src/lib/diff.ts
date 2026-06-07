// frontend/src/lib/diff.ts
// 词级 diff：基于最长公共子序列（LCS）。同 git/GitHub 高亮的原理。
// 输出一串片段，每段标注 same/add/del，前端按颜色渲染即可。

export type DiffPart = { value: string; type: "same" | "add" | "del" };

// 切成「词 + 空白」的 token（保留空白片段，渲染时才能还原原排版/换行）
function tokenize(s: string): string[] {
  return s.length ? s.split(/(\s+)/).filter((t) => t.length > 0) : [];
}

export function diffWords(oldText: string, newText: string): DiffPart[] {
  const a = tokenize(oldText);
  const b = tokenize(newText);
  const n = a.length, m = b.length;

  // dp[i][j] = a[i:] 与 b[j:] 的 LCS 长度（从后往前填表）
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  // 顺着 dp 回溯，产出片段；相邻同类型片段合并，渲染更干净
  const parts: DiffPart[] = [];
  const push = (type: DiffPart["type"], value: string) => {
    const last = parts[parts.length - 1];
    if (last && last.type === type) last.value += value;
    else parts.push({ type, value });
  };

  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { push("same", a[i]); i++; j++; }          // 共同：未改
    else if (dp[i + 1][j] >= dp[i][j + 1]) { push("del", a[i]); i++; }  // 旧有新无：删除
    else { push("add", b[j]); j++; }                              // 新有旧无：新增
  }
  while (i < n) { push("del", a[i]); i++; }   // 旧序列剩余 = 全是删除
  while (j < m) { push("add", b[j]); j++; }   // 新序列剩余 = 全是新增
  return parts;
}