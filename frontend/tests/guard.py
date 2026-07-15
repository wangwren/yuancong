"""守门测试：公开内容不得含隐私词、第三方图床外链、未迁移的相对图链。
用法：cd frontend && python3 tests/guard.py（建议 pnpm build 后跑，连 dist/ 一起扫）
隐私词清单在仓库根 .privacy-terms.txt（本地私有，不进 git）；缺失则跳过该项并告警。
"""
import pathlib, sys

FRONTEND = pathlib.Path(__file__).resolve().parent.parent
REPO = FRONTEND.parent
SCAN_DIRS = [FRONTEND / 'src', FRONTEND / 'public', FRONTEND / 'dist']
TEXT_EXT = {'.md', '.astro', '.ts', '.js', '.mjs', '.css', '.html', '.xml',
            '.json', '.jsonc', '.txt', '.svg'}

terms_file = REPO / '.privacy-terms.txt'
terms = []
if terms_file.exists():
    terms = [t.strip() for t in terms_file.read_text(encoding='utf-8').splitlines() if t.strip()]
else:
    print('警告：未找到 .privacy-terms.txt，隐私词扫描跳过')

bad = []
for d in SCAN_DIRS:
    if not d.exists():
        continue
    for p in d.rglob('*'):
        if not p.is_file():
            continue
        hit_name = [t for t in terms if t in p.name]
        for t in hit_name:
            bad.append(f'文件名含隐私词「{t}」: {p}')
        if p.suffix.lower() not in TEXT_EXT:
            continue
        body = p.read_text(encoding='utf-8', errors='ignore')
        for t in terms:
            if t in body:
                bad.append(f'隐私词「{t}」: {p}')
        if 'fynotefile' in body:
            bad.append(f'第三方图床外链: {p}')
        if p.suffix == '.md' and '](media/' in body:
            bad.append(f'相对图链未迁移: {p}')

if not (FRONTEND / 'dist').exists():
    print('提示：dist/ 不存在，建议先 pnpm build 再跑守门')
if bad:
    print('\n'.join(bad))
    sys.exit(1)
print(f'守门通过：隐私词 {len(terms)} 条、图床外链、相对图链零命中')
