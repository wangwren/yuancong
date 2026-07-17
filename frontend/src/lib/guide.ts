// AI 编程指南镜像的公共约定：工具子目录即分组，文件名编号即阅读顺序。
import type { CollectionEntry } from 'astro:content';
import chaptersData from '../content/guide/chapters.json';

export const GUIDE_TOOLS = [
  { key: 'claude-code', label: 'Claude Code' },
  { key: 'codex', label: 'Codex' },
] as const;

export type GuideToolKey = (typeof GUIDE_TOOLS)[number]['key'];

// 官方阅读站对应页（canonical 用）；URL 形态与上游一致：无尾斜杠
export function officialUrl(id: string): string {
  return `https://coding.stormzhang.ai/${id}`;
}

type Chapter = { title: string; slugs: string[] };

// 章节分组（官方阅读站侧栏同构，chapters.json 随同步产物走）：
// 章内只留已同步篇目、空章丢弃（试点期允许不齐）。
// 产物与映射对不上说明 content/guide 被手改——构建期就地报错，别带病上线
export function chapterGroups(tool: string, posts: CollectionEntry<'guide'>[]) {
  const toolChapters = (chaptersData as Record<string, Chapter[]>)[tool];
  if (!toolChapters) throw new Error(`chapters.json 缺少工具「${tool}」的章节映射，请重跑同步脚本`);
  const bySlug = new Map(posts.map((p) => [p.id.split('/')[1], p]));
  const mapped = new Set(toolChapters.flatMap((c) => c.slugs));
  const orphan = posts.filter((p) => !mapped.has(p.id.split('/')[1]));
  if (orphan.length > 0) {
    throw new Error(`篇目不在章节映射中（content/guide 勿手改，请重跑同步脚本）：${orphan.map((p) => p.id).join(', ')}`);
  }
  return toolChapters
    .map((c) => ({ title: c.title, items: c.slugs.filter((s) => bySlug.has(s)).map((s) => bySlug.get(s)!) }))
    .filter((c) => c.items.length > 0);
}
