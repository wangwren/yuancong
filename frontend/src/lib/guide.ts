// AI 编程指南镜像的公共约定：工具子目录即分组，文件名编号即阅读顺序。
export const GUIDE_TOOLS = [
  { key: 'claude-code', label: 'Claude Code' },
  { key: 'codex', label: 'Codex' },
] as const;

export type GuideToolKey = (typeof GUIDE_TOOLS)[number]['key'];

// 官方阅读站对应页（canonical 用）；URL 形态与上游一致：无尾斜杠
export function officialUrl(id: string): string {
  return `https://coding.stormzhang.ai/${id}`;
}
