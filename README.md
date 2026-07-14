# yuancong.ai

小从的个人站：主页 + 博客（P2）+ 小工具（P3）。

- 前端：`frontend/`，Astro 纯静态构建，零运行时依赖，部署于 Cloudflare Workers（静态资源模式）
- 交互全部为原生 CSS/JS：打字机标题、随访客本地时间变化的天空、深浅色主题、点击撒花、贴着卡片边框爬行的尺蠖毛毛虫（点它有惊喜）

## 本地开发

环境要求：Node ≥ 22.12、pnpm。首次使用先装依赖：

```bash
cd frontend
pnpm install
```

### 启动本地预览

```bash
cd frontend
pnpm dev
```

浏览器打开 http://localhost:4321 。改代码或文章，保存即自动刷新。

注意：Astro 7 的 dev server 是守护进程，命令执行完就转入后台运行，关掉终端也不影响。管理命令：

```bash
pnpm astro dev status   # 查看是否在运行
pnpm astro dev stop     # 停止
```

### 验证

```bash
cd frontend
pnpm build                 # 构建（Astro 7 对无效 HTML 直接报错，构建即校验）
pnpm astro check           # TypeScript / 组件类型检查
python3 tests/smoke.py     # 整页冒烟回归（需先 build；依赖本机 python3 + playwright）
python3 tests/crawler.py   # 毛毛虫交互三轮循环回归（同上）
```
