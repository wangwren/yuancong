// 阅读时长：中文按字（CJK 逐字）、英文按词，350 字/分 + 200 词/分，保底 1 分钟。
// 详情页 meta 行与列表行共用，公式只此一处。
export function readingMinutes(md: string): number {
  // 正文插图（<figure> 里的内联 SVG）只算图上的文字，标签和属性里的坐标、类名不算
  const raw = md.replace(/<figure[\s\S]*?<\/figure>/g, (fig) => fig.replace(/<[^>]+>/g, ' '));
  const cjk = (raw.match(/[一-鿿]/g) ?? []).length;
  const latinWords = (raw.match(/[a-zA-Z0-9]+/g) ?? []).length;
  return Math.max(1, Math.round(cjk / 350 + latinWords / 200));
}
