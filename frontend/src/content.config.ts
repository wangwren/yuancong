import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const blog = defineCollection({
  // id 只取文件名（去掉系列目录前缀），文章移入系列子目录后 URL /blog/<id>/ 不变；
  // 文件名跨目录重复会导致 id 相撞，由 blog/[slug].astro 构建时校验兜底
  loader: glob({
    pattern: '**/*.md',
    base: './src/content/blog',
    generateId: ({ entry }) => entry.split('/').pop()!.replace(/\.md$/, ''),
  }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    pubDate: z.coerce.date(),
    tags: z.array(z.string()).default([]),
  }),
});

const guide = defineCollection({
  // AI 编程指南镜像（同步脚本生成，勿手改）。id 保留目录层级：<tool>/<slug>
  loader: glob({ pattern: '**/*.md', base: './src/content/guide' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
  }),
});

export const collections = { blog, guide };
