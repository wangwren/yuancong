"""毛毛虫/蝴蝶交互回归：点击 → 化蝶飞走 → 换卡重生 → 可再点，连测三轮。
每轮断言：重生后可见、蠕虫路径已绘制、位置贴着某张卡片边框、无残留动画、无 JS 报错。
用法：cd frontend && pnpm build && python3 tests/crawler.py
"""
from playwright.sync_api import sync_playwright
import socket, subprocess, time, os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
# 不用 4321：避免与本地后台 dev server 撞车后连上源码而非 dist 产物
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

def dist_to_rect_border(px, py, r):
    """点到矩形边框的距离（在边框上为 0）"""
    dx = max(r['x'] - px, 0, px - (r['x'] + r['width']))
    dy = max(r['y'] - py, 0, py - (r['y'] + r['height']))
    if dx == 0 and dy == 0:  # 点在矩形内：到最近边的距离
        return min(px - r['x'], (r['x'] + r['width']) - px,
                   py - r['y'], (r['y'] + r['height']) - py)
    return (dx * dx + dy * dy) ** .5

def assert_on_card(pg):
    box = pg.locator('.crawler').bounding_box()
    assert box, '毛毛虫应有布局盒'
    cx, cy = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    rects = pg.eval_on_selector_all(
        '.post .post-in',
        "els => els.map(e => { const r = e.getBoundingClientRect();"
        " return {x: r.x, y: r.y, width: r.width, height: r.height}; })")
    d = min(dist_to_rect_border(cx, cy, r) for r in rects)
    assert d < 40, f'毛毛虫离最近卡片边框 {d:.0f}px，应贴边（<40）'

srv = None
if not TARGET:
    srv = subprocess.Popen(['npx', 'astro', 'preview', '--port', str(PORT)], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_port(PORT)
try:
    with sync_playwright() as p:
        pg = p.chromium.launch().new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto(URL)
        pg.wait_for_selector('.crawler', state='attached', timeout=5000)

        for cycle in range(1, 4):
            # 蠕虫已绘制且可见
            pg.wait_for_function(
                "() => { const c = document.querySelector('.crawler');"
                " return c && getComputedStyle(c).visibility === 'visible'"
                " && c.querySelector('.worm')?.getAttribute('d')?.length > 10; }",
                timeout=15000)
            assert_on_card(pg)
            pg.locator('.crawler').click(force=True)  # 化蝶
            pg.wait_for_function(
                "document.querySelector('.crawler .bw') !== null", timeout=2000)
            # 飞走：进入 hidden（respawn 开始）
            pg.wait_for_function(
                "getComputedStyle(document.querySelector('.crawler')).visibility === 'hidden'",
                timeout=5000)
            # 重生：5-9s 后重新可见、变回蠕虫
            pg.wait_for_function(
                "() => { const c = document.querySelector('.crawler');"
                " return getComputedStyle(c).visibility === 'visible'"
                " && c.querySelector('.worm') !== null; }",
                timeout=12000)
            pg.wait_for_timeout(700)  # 等淡入结束
            anims = pg.evaluate("document.querySelector('.crawler').getAnimations().length")
            assert anims == 0, f'第 {cycle} 轮重生后残留 {anims} 个动画'
            print(f'cycle {cycle} OK')

        assert not errs, errs
        print('CRAWLER PASS x3')
finally:
    if srv:
        srv.terminate()
