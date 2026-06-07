// frontend/src/lib/soap.ts
// 把模型输出的一长段带 ###标记### 的文本，切分成 S/O/A/P 四段（外加可能的 insufficient）。

export type Soap = {
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  insufficient?: string; // 转录无临床内容时模型会用这个段
};

export const EMPTY_SOAP: Soap = { subjective: "", objective: "", assessment: "", plan: "" };

export function parseSoap(text: string): Soap {
  const result: Soap = { ...EMPTY_SOAP };
  // 匹配所有 ###XXX### 标记及其位置
  const re = /###(SUBJECTIVE|OBJECTIVE|ASSESSMENT|PLAN|INSUFFICIENT)###/g;
  const matches = [...text.matchAll(re)];

  for (let i = 0; i < matches.length; i++) {
    const name = matches[i][1].toLowerCase();
    const start = matches[i].index! + matches[i][0].length;     // 本标记内容的起点
    const end = i + 1 < matches.length ? matches[i + 1].index! : text.length; // 到下一个标记前
    const content = text.slice(start, end).trim();
    if (name === "insufficient") result.insufficient = content;
    else (result as Record<string, string>)[name] = content;
  }
  return result;
}