// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// 镜像教程详情页：/blog/claude-code/<slug>/ 与 /blog/codex/<slug>/。
// 两个 tab 列表页（.../claude-code/ 结尾即止）不匹配，因为 [^/]+ 要求至少一段路径
const MIRROR_DETAIL = /\/blog\/(claude-code|codex)\/[^/]+\/$/;

// https://astro.build/config
export default defineConfig({
  site: 'https://yuancong.ai',
  integrations: [
    sitemap({
      // 镜像的 92 篇详情页不进 sitemap：它们的 canonical 指向官方站，而 sitemap
      // 的语义是「请收录这些页面」——两个信号直接冲突。排除后 Google 仍能顺着
      // 列表页的站内链接爬到它们，访问不受任何影响。
      // 两个 tab 列表页是自有内容（章节导航 + 声明块，无 canonical），保留在内
      filter: (page) => !MIRROR_DETAIL.test(page),
    }),
  ],
  markdown: {
    shikiConfig: {
      themes: { light: 'github-light', dark: 'github-dark' },
      // 笔记里不少围栏块是中文要点，横向滚动阅读体验差；真代码换行也可接受
      wrap: true,
    },
  },
});
