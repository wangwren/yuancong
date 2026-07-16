import type { CollectionEntry } from 'astro:content';

// 系列 = content/blog/ 下的一级子目录，目录名即显示名（约定优于配置：
// 建目录扔文章即可成系列，中文目录名进 URL 时正常转码）。
// 零散文章直接放 blog/ 根，不属于任何系列。

// 从文件路径推导所属系列（目录名）；根目录零散文章返回 null
export function seriesOf(post: CollectionEntry<'blog'>): string | null {
  const m = (post.filePath ?? '').match(/content\/blog\/([^/]+)\//);
  return m ? m[1] : null;
}
