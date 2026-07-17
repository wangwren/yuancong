"""主页冒烟测试：结构、深浅色切换与记忆、夜间自动深色。
用法：cd frontend && pnpm build && python3 tests/smoke.py
线上回归：TARGET_URL=https://yuancong.ai/ python3 tests/smoke.py（不起本地服务）
"""
from playwright.sync_api import sync_playwright
import socket, subprocess, time, os, re, json, urllib.parse, calendar

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

# 篇数/标签数从内容目录动态推导——小从的工作流是「扔 md 就推」，
# 写死数字会在每次发文后误报（2026-07-15 因新增测试文章实际踩中）
CONTENT = os.path.join(ROOT, 'src', 'content', 'blog')
def md_files(sub=''):
    base = os.path.join(CONTENT, sub) if sub else CONTENT
    return [os.path.join(dp, f) for dp, _, fs in os.walk(base) for f in fs if f.endswith('.md')]
def tag_count(tag, sub=''):
    # 只认单行不带引号的内联数组（tags: [A, B]）——与现有全部文章的写法一致；
    # 多行 YAML 列表或带引号写法会少算导致测试红（假失败可排查，非静默通过）
    n = 0
    for f in md_files(sub):
        m = re.search(r'^tags:\s*\[(.*?)\]', open(f, encoding='utf-8').read(), re.M)
        if m and tag in [t.strip() for t in m.group(1).split(',')]:
            n += 1
    return n
def read_minutes(path):
    # 与站点 reading-time 同公式的测试侧对拍实现：CJK/350 + 英文词/200，保底 1。
    # frontmatter 不计入（Astro 的 post.body 不含 frontmatter）
    body = re.sub(r'^---\n.*?\n---\n', '', open(path, encoding='utf-8').read(), flags=re.S)
    cjk = len(re.findall(r'[一-鿿]', body))
    latin = len(re.findall(r'[a-zA-Z0-9]+', body))
    return max(1, int(cjk / 350 + latin / 200 + 0.5))
def new_count(days=30):
    # 与 PostRow 同口径：pubDate（UTC 零点）距今 ≤ days 天；动态推导，不写死
    n = 0
    for f in md_files():
        m = re.search(r'^pubDate:\s*(\S+)', open(f, encoding='utf-8').read(), re.M)
        if m:
            ts = calendar.timegm(time.strptime(m.group(1), '%Y-%m-%d'))
            if 0 <= time.time() - ts <= days * 86400:
                n += 1
    return n
GUIDE = os.path.join(ROOT, 'src', 'content', 'guide')
def guide_files(tool):
    d = os.path.join(GUIDE, tool)
    return sorted(f for f in os.listdir(d) if f.endswith('.md')) if os.path.isdir(d) else []
def guide_chapter_count(tool):
    # 有已同步篇目的章数（chapters.json 是官方站侧栏快照，列表小节头与详情折叠章共用）
    meta = json.load(open(os.path.join(GUIDE, 'chapters.json'), encoding='utf-8'))[tool]
    slugs = {f[:-3] for f in guide_files(tool)}
    return sum(1 for c in meta if slugs & set(c['slugs']))
N_ALL = len(md_files())
N_INTERVIEW = len(md_files('面试小题'))
# 不用 4321：本地后台 dev server 常驻该端口，撞车时 preview 起不来，
# 测试会连上 dev server（源码）而非 dist 构建产物，静默测错目标
PORT = 4322
TARGET = os.environ.get('TARGET_URL')
URL = (TARGET.rstrip('/') + '/') if TARGET else f'http://localhost:{PORT}/'

def wait_port(port, timeout=20):
    # Astro 7 preview 监听 IPv6 [::1]，双栈探测防漏
    end = time.time() + timeout
    while time.time() < end:
        for fam, addr in ((socket.AF_INET6, '::1'), (socket.AF_INET, '127.0.0.1')):
            try:
                with socket.socket(fam) as s:
                    s.settimeout(0.5)
                    if s.connect_ex((addr, port)) == 0:
                        return
            except OSError:
                pass
        time.sleep(0.3)
    raise RuntimeError(f'preview server 未在 {timeout}s 内就绪（端口 {port}）')

srv = None
if not TARGET:
    srv = subprocess.Popen(['npx', 'astro', 'preview', '--port', str(PORT)], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_port(PORT)
try:
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # --- 主流程：固定浅色起点，验证切换 + 记忆 ---
        pg = browser.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        # init script 每次导航都会执行，只在无记忆时种入起点，避免盖掉页面自己存的值
        pg.add_init_script(
            "if (!localStorage.getItem('theme')) localStorage.setItem('theme','light');")
        pg.goto(URL)
        assert pg.locator('h1 .me').inner_text() == '小从'
        assert pg.locator('.nav-soon').count() == 2, 'SOON 只剩 Tools/About'
        assert pg.locator('nav a.nav-link[href="/blog/"]').count() == 1, '导航 Blog 应可点'
        assert pg.locator('nav a.action[href="/rss.xml"]').count() == 1, '导航应有 RSS 入口'
        assert pg.locator('.post').count() >= 3, '文章卡片应至少 3 张'
        assert pg.locator('a.post[href^="/blog/"]').count() == 4, '主页 4 张卡片应为博客链接'
        assert pg.locator('a.more[href="/blog/"]').count() == 1, '「全部文章」应指向列表页'
        assert pg.locator('a[href="https://github.com/wangwren"]').count() == 1
        assert pg.locator('a[href="https://x.com/debug_dog61749"]').count() == 1
        assert pg.locator('a[href^="mailto:"]').count() == 0, '邮箱入口已撤，不应再有 mailto 链接'
        assert pg.locator('.contact .pill').count() == 3, '联系区应有三枚胶囊按钮'

        # --- 公众号二维码弹层：默认隐藏，悬停可见 ---
        # 悬停前先等联系区入场动画播完（播完后组件脚本摘掉 rise 类，确定性信号）。
        # 动画中悬停有两个坑：元素还在位移中，归位时会从鼠标底下滑走导致 hover 丢失；
        # 且 opacity/transform 动画播放期间容器是层叠上下文，弹层层级不是最终状态
        pg.wait_for_function(
            "!document.querySelector('.contact').classList.contains('rise')",
            timeout=5000)
        vis = pg.locator('.qr-pop').evaluate("e => getComputedStyle(e).visibility")
        assert vis == 'hidden', f'二维码弹层默认应隐藏，实际 {vis}'
        pg.locator('.wechat').hover()
        pg.wait_for_function(
            "getComputedStyle(document.querySelector('.qr-pop')).visibility === 'visible'",
            timeout=2000)
        # 层级：弹层必须盖过毛毛虫（z 30）与文章卡片（.writing z 1）。
        # 用注入样式表把毛毛虫钉到弹层中心（步态脚本每帧改内联样式，只有
        # 样式表 !important 盖得住），再取重叠点最顶层元素判定
        verdict = pg.evaluate("""
          (() => {
            const pop = document.querySelector('.qr-pop').getBoundingClientRect();
            const px = pop.x + pop.width / 2, py = pop.y + 20;
            const st = document.createElement('style');
            st.textContent = `.crawler{left:${px + scrollX}px !important;top:${py + scrollY}px !important;}`;
            document.head.appendChild(st);
            return new Promise(r => setTimeout(() => {
              const cr = document.querySelector('.crawler').getBoundingClientRect();
              const inside = px >= cr.x && px <= cr.x + cr.width && py >= cr.y && py <= cr.y + cr.height;
              const el = document.elementFromPoint(px, py);
              const popTop = !el || !el.closest('.crawler');
              const edge = document.elementFromPoint(pop.x + pop.width / 2, pop.y + 4);
              const edgeOk = edge && edge.closest('.qr-pop') !== null;
              st.remove();
              r({ inside, popTop, edgeOk });
            }, 250));
          })()
        """)
        assert verdict['inside'], '毛毛虫未成功钉到弹层中心（测试前置失败）'
        assert verdict['popTop'], '二维码弹层应盖过毛毛虫'
        assert verdict['edgeOk'], '弹层顶边被其他内容（如文章卡片）盖住'
        pg.mouse.move(10, 10)  # 移开，弹层收回
        pg.wait_for_function(
            "getComputedStyle(document.querySelector('.qr-pop')).visibility === 'hidden'",
            timeout=2000)
        assert 'dark' not in pg.evaluate("document.documentElement.className")
        pg.click('#mode')
        assert 'dark' in pg.evaluate("document.documentElement.className")
        pg.reload()
        assert 'dark' in pg.evaluate("document.documentElement.className"), '深色记忆失效'
        # 画布防闪对拍：BaseLayout 内联的 html 背景必须与 token --a-bg 一致（双主题各验一次），
        # 内联色写死是为了跨页导航首帧不闪白，token 改色时这里会红提醒同步
        canvas_probe = ("() => { const d = document.createElement('div');"
                        " d.style.background = 'var(--a-bg)'; document.body.append(d);"
                        " const r = [getComputedStyle(d).backgroundColor,"
                        " getComputedStyle(document.documentElement).backgroundColor];"
                        " d.remove(); return r; }")
        got = pg.evaluate(canvas_probe)
        assert got[0] == got[1], f'深色画布内联色与 --a-bg 漂移：{got}'
        pg.click('#mode')
        assert 'dark' not in pg.evaluate("document.documentElement.className")
        got = pg.evaluate(canvas_probe)
        assert got[0] == got[1], f'浅色画布内联色与 --a-bg 漂移：{got}'

        # --- 天空带：结构与星星显隐 ---
        assert pg.locator('.cloud').count() == 3
        assert pg.locator('.star').count() == 13
        star_op = pg.locator('.star').first.evaluate("e => getComputedStyle(e).opacity")
        assert star_op == '0', f'浅色下星星应隐藏，实际 opacity={star_op}'
        pg.click('#mode')  # 进深色
        pg.wait_for_timeout(100)
        star_op = pg.locator('.star').first.evaluate("e => getComputedStyle(e).opacity")
        assert float(star_op) > 0, f'深色下星星应可见，实际 opacity={star_op}'
        pg.click('#mode')  # 回浅色

        # --- 天色相位：晨昏时段给 body 打类 ---
        for hour, expect_cls in ((6, 'sky-dawn'), (18, 'sky-dusk'), (12, None)):
            pg3 = browser.new_page()
            pg3.add_init_script(
                "Date.prototype.getHours = function(){ return %d; };" % hour)
            pg3.goto(URL)
            body_cls = pg3.evaluate("document.body.className")
            if expect_cls:
                assert expect_cls in body_cls, f'hour={hour} 期望 {expect_cls}，实际 "{body_cls}"'
            else:
                assert 'sky-' not in body_cls, f'hour={hour} 不应有相位类，实际 "{body_cls}"'
            pg3.close()

        # --- 深色 + 晚霞时段并存：深色必须赢，天空用暗夜配色（回归：紫天白云 bug） ---
        pg3d = browser.new_page()
        pg3d.add_init_script("localStorage.setItem('theme','dark');"
                             "Date.prototype.getHours = function(){ return 18; };")
        pg3d.goto(URL)
        assert 'sky-dusk' in pg3d.evaluate("document.body.className")
        # 借浏览器把变量解析成规范 rgb 再比：构建压缩会把 hsl() 改写成 hex，直接比字符串会误报
        sky = pg3d.evaluate("""
          (() => {
            const el = document.createElement('span');
            el.style.color = 'var(--a-sky)';
            document.body.appendChild(el);
            const c = getComputedStyle(el).color;
            el.remove();
            return c;
          })()
        """)
        assert sky == 'rgb(21, 31, 55)', f'深色下 --a-sky 应为暗夜色 hsl(223 45% 15%)，实际 {sky}'
        pg3d.close()

        # --- 夜间自动深色（无记忆时按访客本地小时） ---
        for hour, expect_dark in ((22, True), (10, False)):
            pg2 = browser.new_page()
            pg2.add_init_script(
                "Date.prototype.getHours = function(){ return %d; };" % hour)
            pg2.goto(URL)
            got = 'dark' in pg2.evaluate("document.documentElement.className")
            assert got == expect_dark, f'hour={hour} 期望 dark={expect_dark} 实际 {got}'
            pg2.close()

        # --- 记忆优先于时段：夜间 + 已存浅色偏好 → 保持浅色 ---
        pgL = browser.new_page()
        pgL.add_init_script("localStorage.setItem('theme','light');"
                            "Date.prototype.getHours = function(){ return 22; };")
        pgL.goto(URL)
        assert 'dark' not in pgL.evaluate("document.documentElement.className"), \
            '存了浅色偏好时夜间不应自动深色'
        pgL.close()

        # --- wordmark 防跳变：字体晚到时整页回退、绝不中途换字（font-display: optional + preload）---
        # 回归 2026-07-17 修复：swap 语义下字体在首帧后到达会中途换字，字宽跳约 7px，跨页导航肉眼可见
        pgF = browser.new_page()
        def _delay_font(route):
            time.sleep(0.6)
            route.continue_()
        pgF.route('**/fonts/*.woff2', _delay_font)
        pgF.goto(URL + 'blog/')
        assert pgF.locator('head link[rel="preload"][as="font"]').count() == 1, '字体 preload 应存在'
        pgF.wait_for_timeout(150)   # 过掉 optional 的 ~100ms 阻塞期，此刻是回退字体
        w_early = pgF.evaluate("document.querySelector('.wordmark').offsetWidth")
        pgF.wait_for_timeout(900)   # 字体早已到达——optional 不得再换
        w_late = pgF.evaluate("document.querySelector('.wordmark').offsetWidth")
        assert w_early == w_late, f'字体晚到不得中途换字（宽度 {w_early} → {w_late}）'
        pgF.close()

        # --- 404 页：错误路径返回站内 404 页而非裸错误 ---
        pg404 = browser.new_page()
        pg404.goto(URL + 'no-such-page/')
        assert '这一页不存在' in pg404.content(), '404 页未生效'
        pg404.close()

        # --- 打字机 + 撒花 ---
        pg4 = browser.new_page()
        pg4.on('pageerror', lambda e: errs.append(str(e)))
        pg4.goto(URL)
        pg4.wait_for_function(
            "document.querySelectorAll('#typing .ch.on').length"
            " === document.querySelectorAll('#typing .ch').length", timeout=8000)
        pg4.mouse.click(640, 300)  # hero 简介行附近，确保落在 body 内容区内
        assert pg4.locator('.bit').count() > 0, '点击空白应产生撒花粒子'
        pg4.wait_for_function("document.querySelectorAll('.bit').length === 0",
                              timeout=3000)  # 粒子自清理
        pg4.close()

        # --- reduced-motion：标题全亮无光标，点击不撒花 ---
        pg5 = browser.new_page()
        pg5.emulate_media(reduced_motion='reduce')
        pg5.goto(URL)
        assert pg5.evaluate(
            "getComputedStyle(document.querySelector('#typing .ch')).opacity") == '1'
        assert pg5.locator('.type-caret').count() == 0
        pg5.mouse.click(640, 300)
        pg5.wait_for_timeout(300)
        assert pg5.locator('.bit').count() == 0
        # 毛毛虫：静止拱起姿势仍可点，点击后淡出（替代飞行）进入重生流程
        pg5.wait_for_function(
            "() => { const c = document.querySelector('.crawler');"
            " return c && c.querySelector('.worm')?.getAttribute('d')?.length > 10; }",
            timeout=5000)
        pg5.locator('.crawler').click(force=True)
        pg5.wait_for_function(
            "getComputedStyle(document.querySelector('.crawler')).visibility === 'hidden'",
            timeout=3000)
        pg5.close()

        # --- P2 博客：详情页 ---
        pg.goto(URL + 'blog/mysql-interview-notes/')
        assert pg.locator('article h1').inner_text().strip() == 'MySQL 面试笔记'
        exp_min = read_minutes(os.path.join(CONTENT, '面试小题', 'mysql-interview-notes.md'))
        got_min = pg.locator('.post-head .stat').inner_text()
        assert got_min == f'{exp_min} min read', f'详情页时长应 {exp_min} min read，实际 {got_min}'
        assert pg.locator('.prose .astro-code').count() >= 5, '应有 Shiki 代码块（该篇原文 10 个）'
        # TOC 断点 1440px：默认 1280 视口下 details 被脚本收起（此处验证收起态），
        # 展开态必须在宽视口页面上验证——count() 数 DOM 不分辨 details 开合，光数数会退化成假断言
        assert pg.locator('details.toc:not([open])').count() == 1, '窄屏 TOC 应默认收起为顶部条'
        pgT = browser.new_page(viewport={'width': 1680, 'height': 1000})
        pgT.add_init_script(
            "if (!localStorage.getItem('theme')) localStorage.setItem('theme','light');")
        pgT.goto(URL + 'blog/mysql-interview-notes/')
        assert pgT.locator('details.toc[open]').count() == 1, '宽屏（≥1440px）TOC 应默认展开'
        assert pgT.locator('.toc nav a').count() >= 15, 'TOC 条目应与 26 小节同量级'
        assert pgT.locator('.toc nav a').first.is_visible(), 'TOC 条目应真实可见'
        pgT.close()
        light_bg = pg.locator('.prose .astro-code').first.evaluate(
            'el => getComputedStyle(el).backgroundColor')
        pg.locator('#mode').click()
        dark_bg = pg.locator('.prose .astro-code').first.evaluate(
            'el => getComputedStyle(el).backgroundColor')
        assert light_bg != dark_bg, '代码块应随主题双色切换'
        pg.locator('#mode').click()  # 切回浅色，不污染后续断言
        # 带图文章：图链应全指向 R2 自定义域且真实可达
        pg.goto(URL + 'blog/scenario-full-gc-tuning/')
        srcs = pg.locator('.prose img').evaluate_all('els => els.map(e => e.src)')
        assert srcs and all(s.startswith('https://img.yuancong.ai/') for s in srcs), srcs
        assert pg.request.get(srcs[0]).status == 200, 'R2 图片应可达'

        # --- P2 博客：列表页与标签筛选 ---
        pg.goto(URL + 'blog/')
        assert pg.locator('.blog-head h1').inner_text().strip() == 'Blog', '页头应为 Blog'
        assert pg.locator('.blog-head p').count() == 0, '介绍句应已删除'
        assert pg.locator('.posts .stat').count() == N_ALL, '每行应有阅读时长'
        t0 = pg.locator('.posts time').first.inner_text()
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', t0), f'列表日期应精确到天，实际 {t0}'
        n_new = new_count()
        assert pg.locator('.posts .new').count() == n_new, f'NEW 徽章应 {n_new} 枚（30 天内文章数）'
        xs = pg.locator('a.post').evaluate_all('els => els.map(e => e.getBoundingClientRect().x)')
        assert len(set(xs)) == 1, f'列表应单列（行左缘全对齐），实际 x 集合 {sorted(set(xs))}'
        assert pg.locator('a.post').count() == N_ALL, f'列表页应有 {N_ALL} 篇'
        pg.locator('.tagbar .pill[data-tag="场景题"]').click()
        n_scene = tag_count('场景题')
        assert pg.locator('a.post:not(.hide)').count() == n_scene, f'场景题筛选应剩 {n_scene} 篇'
        assert '场景题' in urllib.parse.unquote(pg.url), '筛选应同步到 hash'
        pg.locator('.tagbar .pill[data-tag="全部"]').click()
        assert pg.locator('a.post:not(.hide)').count() == N_ALL, '取消筛选应恢复全量'
        # 用新页面验证「直达」：若复用 pg，浏览器把仅 hash 不同的 goto 当同文档导航
        # （不重新执行脚本），并非真实直达场景，会误报
        pgH = browser.new_page()
        pgH.goto(URL + 'blog/#Java')
        n_java = tag_count('Java')
        assert pgH.locator('a.post:not(.hide)').count() == n_java, f'hash 直达 Java 应只显 {n_java} 篇'
        pgH.close()
        # 卡片点进详情
        pg.goto(URL + 'blog/')
        pg.locator('a.post').first.click()
        pg.wait_for_url('**/blog/**')
        assert pg.locator('.post-head h1').count() == 1, '卡片应能点进详情页'

        # --- P2 博客：系列（物理目录 = 系列，目录名即显示名，中文路径正常转码） ---
        pg.goto(URL + 'blog/')
        bar = pg.locator('.series-bar a')
        assert bar.count() >= 2, '列表页应有系列导航（全部文章 + 至少一个系列）'
        assert bar.first.inner_text() == '全部文章'
        assert pg.locator('.series-bar a[aria-current="page"]').inner_text() == '全部文章'
        pg.goto(URL + 'blog/' + urllib.parse.quote('面试小题') + '/')
        assert pg.locator('a.post').count() == N_INTERVIEW, f'面试小题系列页应 {N_INTERVIEW} 篇'
        assert pg.locator('.series-bar a[aria-current="page"]').inner_text() == '面试小题'
        pg.locator('.tagbar .pill[data-tag="场景题"]').click()
        n_scene_s = tag_count('场景题', '面试小题')
        assert pg.locator('a.post:not(.hide)').count() == n_scene_s, '系列页内标签筛选应照常工作'
        pg.goto(URL + 'blog/mysql-index/')
        assert pg.locator('.series li').count() == N_INTERVIEW, f'详情页系列卡应列全同系列 {N_INTERVIEW} 篇'
        assert pg.locator('.series [aria-current="page"]').inner_text().strip() == 'MySQL 索引相关', \
            '系列卡应高亮当前篇'
        assert pg.locator('.series li a').count() == N_INTERVIEW - 1, '系列卡除当前篇外应是链接'

        # --- 详情页：TOC 阅读位置联动（scrollspy） ---
        assert pg.locator('.toc a.now').count() == 0, '未滚动时（标题区）不应有高亮项'
        last_slug = pg.locator('.toc nav a').last.get_attribute('href').split('#')[1]
        pg.evaluate(
            "slug => document.getElementById(decodeURIComponent(slug))"
            ".scrollIntoView({behavior:'instant'})", last_slug)
        pg.wait_for_function(
            "document.querySelector('.toc a.now')?.getAttribute('href')?.endsWith("
            f"'#{last_slug}')", timeout=3000)
        pg.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
        pg.wait_for_function("!document.querySelector('.toc a.now')", timeout=3000)

        # --- Guide 镜像：系列栏 tab 与列表页 ---
        pg.goto(URL + 'blog/')
        for tool, label in (('claude-code', 'Claude Code'), ('codex', 'Codex')):
            assert pg.locator(f'.series-bar a[href="/blog/{tool}/"]').count() == 1, f'{label} tab 应在系列栏'
        for tool, label in (('claude-code', 'Claude Code'), ('codex', 'Codex')):
            gfiles = guide_files(tool)
            if not gfiles:
                continue
            pg.goto(URL + f'blog/{tool}/')
            assert pg.locator('.series-bar a[aria-current="page"]').inner_text() == label
            assert pg.locator('.rows .row').count() == len(gfiles), f'{label} 应 {len(gfiles)} 篇'
            n_chap_l = guide_chapter_count(tool)
            assert pg.locator('.rows details.chap-group').count() == n_chap_l, f'列表页章节组应 {n_chap_l} 个'
            assert pg.locator('.rows details.chap-group[open]').count() == 0, '列表章节应默认全收起'
            pg.locator('.rows .chap-head').first.click()  # 展开第一章，再验行序与可点入
            assert pg.locator('.rows details.chap-group[open]').count() == 1, '点击章节头应展开'
            # 开合有高度过渡动画，行内容随 content-visibility 渐次可渲染——等可见再读
            pg.locator('.rows .row .t').first.wait_for(state='visible')
            first_t = pg.locator('.rows .row .t').first.inner_text()
            assert first_t.startswith(gfiles[0][:2]), f'应按编号正序，首行 {first_t}'
            notice = pg.locator('.notice').inner_text()
            assert 'stormzhang' in notice and 'MIT' in notice, '来源声明块应含作者与协议'
            pg.locator('.rows .row').first.click()
            pg.wait_for_url(f'**/blog/{tool}/**')
            assert pg.locator('.post-head .src').count() == 1, '行应能点进镜像详情'

        # --- Guide 镜像：详情页、canonical 双向硬边界 ---
        for tool in ('claude-code', 'codex'):
            gfiles = guide_files(tool)
            if not gfiles:
                continue  # 该工具未同步时跳过（试点期允许不齐）
            slug = gfiles[0][:-3]
            pg.goto(URL + f'blog/{tool}/{slug}/')
            canon = pg.locator('head link[rel="canonical"]').get_attribute('href')
            assert canon == f'https://coding.stormzhang.ai/{tool}/{slug}', f'canonical 应指官方站，实际 {canon}'
            assert pg.locator('.post-head .sub').count() == 1, '副题应渲染'
            assert 'stormzhang' in pg.locator('.post-head .src').inner_text(), '镜像声明行应存在'
            if len(gfiles) > 1:  # 单篇工具（如试点期 codex）首篇即末篇，本就无「下一篇」，非缺陷
                assert pg.locator('.pager a').count() >= 1, '首篇应至少有「下一篇」'
            # 系列导航按章分组（官方站同构，数据 chapters.json）：只展开当前篇所在章
            n_chap = guide_chapter_count(tool)
            assert pg.locator('.series details.chap').count() == n_chap, f'章节组应 {n_chap} 个'
            assert pg.locator('.series li').count() == len(gfiles), '章节导航应列全同工具篇目'
            assert pg.locator('.series details[open]').count() == 1, '默认应只展开当前篇所在章'
            assert pg.locator('.series details[open] [aria-current="page"]').count() == 1, \
                '当前篇应高亮且在展开章内'
        # canonical 硬边界：博客与主页永不带 canonical（小从明确要求，防误伤自有内容）
        for path in ('', 'blog/', 'blog/mysql-interview-notes/', 'blog/claude-code/', 'blog/codex/'):
            pg.goto(URL + path)
            n = pg.locator('head link[rel="canonical"]').count()
            assert n == 0, f'/{path} 不应有 canonical，实际 {n} 个'
        # 镜像正文 R2 图可达（取第一篇含图的已同步文章）
        img_page = None
        for tool in ('claude-code', 'codex'):
            for f in guide_files(tool):
                if 'img.yuancong.ai/guide' in open(os.path.join(GUIDE, tool, f), encoding='utf-8').read():
                    img_page = f'blog/{tool}/{f[:-3]}/'
                    break
            if img_page:
                break
        if img_page:
            pg.goto(URL + img_page)
            gsrcs = pg.locator('.prose img').evaluate_all('els => els.map(e => e.src)')
            assert gsrcs and all('img.yuancong.ai/guide/' in s for s in gsrcs), gsrcs
            assert pg.request.get(gsrcs[0]).status == 200, '镜像 R2 图应可达'

        # --- P2：RSS ---
        resp = pg.request.get(URL + 'rss.xml')
        assert resp.status == 200, f'rss.xml 应 200，实际 {resp.status}'
        xml = resp.text()
        assert xml.count('<item>') == N_ALL, f'RSS 应含 {N_ALL} 篇，实际 {xml.count("<item>")}'
        assert '/blog/mysql-interview-notes/' in xml, 'RSS 链接应指向详情页'
        assert '<language>zh-cn</language>' in xml

        assert not errs, errs
        print('SMOKE PASS')
finally:
    if srv:
        srv.terminate()
