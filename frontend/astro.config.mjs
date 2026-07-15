// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  site: 'https://yuancong.ai',
  markdown: {
    shikiConfig: {
      themes: { light: 'github-light', dark: 'github-dark' },
      // 笔记里不少围栏块是中文要点，横向滚动阅读体验差；真代码换行也可接受
      wrap: true,
    },
  },
});
