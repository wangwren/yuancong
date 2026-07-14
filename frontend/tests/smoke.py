"""主页冒烟测试：结构、深浅色切换与记忆、夜间自动深色。
用法：cd frontend && pnpm build && python3 tests/smoke.py
"""
from playwright.sync_api import sync_playwright
import subprocess, time, os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
URL = 'http://localhost:4321/'

srv = subprocess.Popen(['npx', 'astro', 'preview', '--port', '4321'], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)
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
        assert pg.locator('.nav-soon').count() == 3
        assert pg.locator('.post').count() >= 3, '文章卡片应至少 3 张'
        assert pg.locator('.post a').count() == 0, 'P1 卡片不应含链接'
        assert pg.locator('a[href="https://github.com/wangwren"]').count() == 1
        assert pg.locator('a[href="https://x.com/debug_dog61749"]').count() == 1
        assert pg.locator('a[href="mailto:hi@yuancong.ai"]').count() == 1

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
        pg.click('#mode')
        assert 'dark' not in pg.evaluate("document.documentElement.className")

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
        sky = pg3d.evaluate(
            "getComputedStyle(document.body).getPropertyValue('--a-sky').trim()")
        assert 'sky-dusk' in pg3d.evaluate("document.body.className")
        assert sky == 'hsl(223 45% 15%)', f'深色下 --a-sky 应为暗夜色，实际 {sky}'
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

        assert not errs, errs
        print('SMOKE PASS')
finally:
    srv.terminate()
