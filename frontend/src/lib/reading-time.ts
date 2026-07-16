// 阅读时长：中文按字（CJK 逐字）、英文按词，350 字/分 + 200 词/分，保底 1 分钟。
// 详情页 meta 行与列表行共用，公式只此一处。
export function readingMinutes(raw: string): number {
  const cjk = (raw.match(/[一-鿿]/g) ?? []).length;
  const latinWords = (raw.match(/[a-zA-Z0-9]+/g) ?? []).length;
  return Math.max(1, Math.round(cjk / 350 + latinWords / 200));
}
