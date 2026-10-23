#!/usr/bin/env python3
"""Build a JavaScript-free HTML/CSS site for www2.ninjal.ac.jp/lingfes/.

Runtime on the publishing server: none. Uses only the Python standard library
at build time (local or GitHub Actions); emits UTF-8 HTML and CSS only.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
DATA = ROOT / "data"
PUBLIC = ROOT / "public"
SLOTS = {
    "A": ("10:30〜12:00", "未完成研究・お悩み相談"),
    "B": ("12:30〜14:00", "研究室・プロジェクト・企画・出版社・書店"),
    "C": ("14:30〜16:00", "完成研究"),
}
ONSITE_BOOTH_NUMBERS = set(range(29, 37))


def h(v: object) -> str:
    return html.escape(str(v), quote=True)


def https_url(v: object, field: str) -> str:
    if not isinstance(v, str):
        raise ValueError(f"{field}: URL must be a string")
    if not v:
        return ""
    p = urlsplit(v)
    if p.scheme != "https" or not p.netloc or p.username or p.password:
        raise ValueError(f"{field}: URL must be absolute https, with no credentials")
    return v


def read_json(name: str) -> dict:
    obj = json.loads((DATA / name).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"{name}: expected a JSON object")
    return obj


def validate(site: dict, program: dict) -> list[dict]:
    for key in ("staff_application_url", "presentation_application_url", "pdf_submission_url", "participation_application_url", "contact_url"):
        https_url(site.get(key, ""), key)
    pres = program.get("presentations", [])
    if not isinstance(pres, list):
        raise ValueError("presentations must be a list")
    if len(pres) > 108:
        raise ValueError("Online presentations must be <=108")
    used: set[tuple[str, str]] = set()
    onsite_count = 0
    slot_counts = Counter()
    for i, p in enumerate(pres, 1):
        if not isinstance(p, dict):
            raise ValueError(f"Entry {i}: object expected")
        slot, booth = p.get("slot"), p.get("booth")
        if slot not in SLOTS:
            raise ValueError(f"Entry {i}: slot must be A/B/C")
        if not re.fullmatch(r"B(?:0[1-9]|[12][0-9]|3[0-6])", str(booth)):
            raise ValueError(f"Entry {i}: booth must be B01..B36")
        if (slot, booth) in used:
            raise ValueError(f"Entry {i}: duplicate (slot,booth) = {slot},{booth}")
        used.add((slot, booth))
        slot_counts[slot] += 1
        for key in ("title", "authors"):
            if not isinstance(p.get(key), str) or not p[key].strip():
                raise ValueError(f"Entry {i}: {key} is required")
        if len(str(p.get("summary", ""))) > 3000:
            raise ValueError(f"Entry {i}: excessively long summary")
        for key in ("pdf_url", "ovice_url"):
            https_url(p.get(key, ""), f"Entry {i} {key}")
        if p.get("onsite", False):
            onsite_count += 1
            if int(booth[1:]) not in ONSITE_BOOTH_NUMBERS:
                raise ValueError(f"Entry {i}: onsite presentation must be in B29..B36")
    if any(slot_counts[x] > 36 for x in SLOTS):
        raise ValueError("Maximum 36 online presentations in each slot")
    if onsite_count > 24:
        raise ValueError("Maximum 24 onsite-streamed presentations in total")
    return pres


def link_or_pending(label: str, url: str) -> str:
    if not url:
        return f'<span class="btn disabled" aria-disabled="true">{h(label)}：準備中</span>'
    return f'<a class="btn" href="{h(url)}" target="_blank" rel="noopener noreferrer">{h(label)} →</a>'


def header(title: str, description: str, active: str = "") -> str:
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{h(description)}"><title>{h(title)} | 言語学フェス2027</title>
<link rel="stylesheet" href="../assets/styles.css"></head><body>
<a href="#main" class="skip">本文へ移動</a>
<header><nav aria-label="主なリンク"><a href="../" class="brand">言語学フェス</a><div class="links"><a href="./">2027年の案内</a><a href="program.html">発表一覧</a><a href="map-a.html">ブース地図</a><a href="../2026/">過年度</a></div></nav></header>
<main id="main">'''


def footer() -> str:
    return '''</main><footer class="footer"><p>言語学フェス2027実行委員会（開催準備中）</p><p><a href="./">2027年の案内</a> ／ <a href="../">年度別記録</a></p>
<p class="small">公開に同意された情報のみ掲載します。個人情報・非公開PDF・申込名簿は収録しません。</p></footer></body></html>'''


def slot_nav(current: str = "") -> str:
    items = []
    for s, (time, topic) in SLOTS.items():
        current_attr = ' aria-current="page"' if current == s else ""
        items.append(f'<a href="map-{s.lower()}.html"{current_attr}>{s}｜{time}<span class="sr-only"> {h(topic)}</span></a>')
    return '<nav class="slot-nav" aria-label="時間帯別ブース地図">' + "".join(items) + '</nav>'


def make_map(slot: str, idx: dict[tuple[str, str], dict]) -> str:
    time, topic = SLOTS[slot]
    blocks = []
    for number in range(1, 37):
        booth = f"B{number:02d}"
        presentation = idx.get((slot, booth))
        is_onsite_zone = number in ONSITE_BOOTH_NUMBERS
        classes = "booth" + (" onsite" if is_onsite_zone else "") + (" not-assigned" if not presentation else "")
        if presentation:
            title = h(presentation["title"])
            href = f"program.html#{slot}-{booth}"
            subtitle = f'<span class="booth-title">{title}</span>'
            aria = f"{booth} {title}の発表詳細へ"
        else:
            href = f"program.html#slot-{slot}"
            subtitle = '<span class="booth-title">未登録</span>'
            aria = f"{booth} まだ発表は未登録・{slot}枠の一覧へ"
        blocks.append(f'<a class="{classes}" href="{href}" aria-label="{aria}"><strong>{booth}</strong>{subtitle}</a>')
    return f'''{header(f"{slot}枠のブース地図", "JavaScriptを使用しない時間帯別36ブース地図")}
<div class="page-hero"><span class="site-label">STATIC BOOTH MAP 2027 / {slot}</span><h1>{slot}枠｜{time}</h1><p class="lead">{h(topic)}：36ブースの配置図</p></div>
<div class="em"><strong>オンライン発表は36件×3回＝最大108件。</strong> この図は{slot}枠の36ブースです。時間帯の変更は下のリンクでページを移動します。JavaScriptは使用しません。</div>
{slot_nav(slot)}
<section><h2>ブース配置</h2><p>左2列は運営・交流スペース、右側は6列×6行の発表ブースです。<strong>右下のB29〜B36</strong>を国語研現地配信候補として表示しています（最終割当てではありません）。</p>
<div class="map-layout"><div class="map-admin"><div><strong>運営・管理</strong><small>受付・案内・技術支援</small></div><div><strong>自由交流</strong><small>雑談・相談・休憩</small></div></div>
<div class="booths" aria-label="{slot}枠のB01からB36">{''.join(blocks)}</div></div>
<div class="legend"><span><span class="dot"></span>通常ブース</span><span><span class="dot o"></span>右下：現地配信候補（8ブース）</span></div>
<p class="muted-note">各ブースをクリックすると、この時間帯の発表プログラムに移動します。未採択・未登録のブースは時間帯の一覧へ移動します。</p></section>
<section><h2>発表資料とoVice</h2><p>採択された発表の題名・発表者・公開許諾済みPDF・oViceのリンクはプログラムに掲載します。公開資料がまだない場合も、会場位置はブース番号で確認できます。</p>
<p><a class="btn" href="program.html#slot-{slot}">{slot}枠の発表一覧へ →</a>　<a href="./">開催概要へ戻る</a></p></section>
{footer()}'''


def make_program(presentations: list[dict]) -> str:
    groups: dict[str, list[dict]] = {s:[] for s in SLOTS}
    for p in presentations:
        groups[p["slot"]].append(p)
    out = [header("発表プログラム・資料", "3時間帯の発表一覧と公開許諾された資料のリンク")]
    out.append('''<div class="page-hero"><span class="site-label">ONLINE PROGRAM 2027</span><h1>発表プログラム・資料</h1>
<p class="lead">3回の発表時間帯別に題名・発表者・ブースを掲載します。検索する場合はブラウザの「ページ内検索」（Ctrl+F、MacはCommand+F）をご利用ください。</p></div>
<div class="em"><strong>oViceオンライン発表：36件 × 3回 ＝ 最大108件</strong>。個別サムネイルは不要です。公開資料は発表者の許諾範囲に限ります。</div>
<nav class="slot-nav" aria-label="発表一覧の時間帯"><a href="#slot-A">A｜10:30〜12:00</a><a href="#slot-B">B｜12:30〜14:00</a><a href="#slot-C">C｜14:30〜16:00</a></nav>''')
    for slot,(time, topic) in SLOTS.items():
        arr = sorted(groups[slot],key=lambda p:int(p["booth"][1:]))
        out.append(f'<section id="slot-{slot}"><h2>{slot}｜{time}（{h(topic)}）</h2><p class="small">登録済み：{len(arr)}件／上限36件　<a href="map-{slot.lower()}.html">{slot}枠の36ブース地図</a></p>')
        if not arr:
            out.append('<div class="panel"><p>採択された発表はまだ登録されていません。プログラム確定後、こちらに掲載します。</p></div>')
        else:
            out.append('<div class="program-table"><table><thead><tr><th>ブース</th><th>発表情報</th></tr></thead><tbody>')
            for p in arr:
                booth = p["booth"]
                onsite = ' <span class="pill">国語研現地配信</span>' if p.get('onsite',False) else ''
                title=h(p['title']);authors=h(p['authors']);summary=h(p.get('summary',''))
                extra=f'<p class="program-abstract">{summary}</p>' if summary else ''
                links=[]
                for name,key in (("PDF","pdf_url"),("oVice","ovice_url")):
                    v=p.get(key,'')
                    if v:
                        links.append(f'<a href="{h(v)}" target="_blank" rel="noopener noreferrer">{name}を開く</a>')
                related=(f'<p class="program-link-row">{" ／ ".join(links)}</p>' if links else '<p class="small">資料リンク：準備中／非公開</p>')
                out.append(f'<tr id="{slot}-{booth}"><td><a href="map-{slot.lower()}.html">{booth}</a></td><td><strong>{title}</strong>{onsite}<div class="program-author">{authors}</div>{extra}{related}</td></tr>')
            out.append('</tbody></table></div>')
        out.append('</section>')
    out.append('''<section><h2>公開資料について</h2><p>応募時PDFは非公開で受領します。採択後、公開に同意した資料のみ外部リンクを掲載します。公開許諾がないPDFはプログラムに載せません。</p>
<p>当サイトはHTMLとCSSの静的ページです。JavaScriptや検索API、ログイン機能は使用していません。</p></section>''')
    out.append(footer())
    return '\n'.join(out)




def make_archive() -> None:
    """Generate static historical title pages from GitHub-editable JSON."""
    raw = read_json('archive_titles_2021-2026.json')
    years=raw.get('years',{})
    if set(years)!={str(x) for x in range(2021,2027)}:
        raise ValueError('Exactly years 2021-2026 must be present')
    for y in range(2021,2027):
        d=years[str(y)]
        entries=d.get('presentations',[])
        if not entries:
            raise ValueError(f'{y}: empty archive')
        ids=set(); groups={'A':[],'B':[],'C':[]}
        for e in entries:
            name=e.get('title')
            pid=e.get('id')
            slot=e.get('slot')
            if not isinstance(name,str) or not name.strip() or not isinstance(pid,str) or pid in ids or slot not in groups:
                raise ValueError(f'Invalid archive entry in {y}: {e!r}')
            ids.add(pid); groups[slot].append(e)
        source=https_url(d.get('source_url',''),f'{y} source_url')
        if not source: raise ValueError(f'{y}: missing source')
        document=[f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="言語学フェス{y}の公開プログラムにある発表タイトルの保存記録"><title>言語学フェス{y} 発表タイトル一覧</title><link rel="stylesheet" href="../assets/styles.css"></head><body><a href="#main" class="skip">本文へ移動</a><header><nav aria-label="年度別ナビゲーション"><a class="brand" href="../">言語学フェス</a><div class="links"><a href="../#archive">年度別アーカイブ</a><a href="../2027/">2027年</a></div></nav></header><main id="main"><div class="page-hero"><span class="site-label">ARCHIVE {y}</span><h1>言語学フェス{y}</h1><p class="lead">公開プログラムから記録した発表タイトル：{len(entries)}件</p></div><p class="muted-note">原典：<a href="{h(source)}" target="_blank" rel="noopener noreferrer">{y}年の公開プログラムを見る</a>。発表番号と題名のみを転記しています。著者・所属・PDFは掲載していません。転記表記は最終照合前です。</p>"""]
        if y==2021:
            document.append('<p class="small">注記：公開プログラムで確認できた題名は42件です。別の開催報告で言及された44件との差分は未確認です。</p>')
        for slot,items in groups.items():
            if not items: continue
            document.append(f'<section id="slot-{slot}"><h2>コアタイム{slot}（{len(items)}件）</h2><div class="program-table"><table><thead><tr><th style="width:105px">発表番号</th><th>発表タイトル</th></tr></thead><tbody>')
            for entry in items:
                document.append(f'<tr><td>{h(entry["id"])}</td><td>{h(entry["title"])}</td></tr>')
            document.append('</tbody></table></div></section>')
        document.append('<section><h2>出典・保存方針</h2><p>題名を記録した最小限の書誌的アーカイブです。公開プログラム以外からの推測による発表情報の補完はしていません。題名の修正はGitHubのデータファイルを更新し、静的HTMLを再生成して反映します。</p><p><a href="../#archive">他の年度を見る</a></p></section></main><footer class="footer"><strong>言語学フェス 年度別アーカイブ</strong><p>元の開催サイトも引き続き出典として参照してください。</p></footer></body></html>')
        output=PUBLIC/str(y)/'index.html'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text('\n'.join(document),encoding='utf-8')

def build() -> None:
    site = read_json('site-2027.json')
    data = read_json('program-2027.json')
    pres = validate(site, data)
    idx={(p['slot'],p['booth']):p for p in pres}
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    (PUBLIC/'assets').mkdir(parents=True, exist_ok=True)
    (PUBLIC/'2026').mkdir(parents=True, exist_ok=True)
    (PUBLIC/'2027').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE/'assets/styles.css', PUBLIC/'assets/styles.css')
    shutil.copyfile(SOURCE/'index.html', PUBLIC/'index.html')
    shutil.copyfile(SOURCE/'2026/index.html', PUBLIC/'2026/index.html')
    template=(SOURCE/'2027/index.html').read_text(encoding='utf-8')
    mapping={
        '{{PRESENTATION_LINK}}':link_or_pending('発表申込',site.get('presentation_application_url','')),
        '{{PDF_LINK}}':link_or_pending('PDF提出',site.get('pdf_submission_url','')),
        '{{STAFF_LINK}}':link_or_pending('スタッフ応募',site.get('staff_application_url','')),
        '{{PARTICIPATION_LINK}}':link_or_pending('参加申込',site.get('participation_application_url','')),
    }
    for token,content in mapping.items():
        if token not in template:
            raise ValueError(f'Missing placeholder in src/2027/index.html: {token}')
        template=template.replace(token,content)
    (PUBLIC/'2027/index.html').write_text(template,encoding='utf-8')
    (PUBLIC/'2027/program.html').write_text(make_program(pres),encoding='utf-8')
    for slot in SLOTS:
        (PUBLIC/f'2027/map-{slot.lower()}.html').write_text(make_map(slot,idx),encoding='utf-8')
    (PUBLIC/'.nojekyll').write_bytes(b'')
    make_archive()
    # Server is intentionally non-programmable: only plain HTML/CSS published.
    assert_no_scripts()
    print(f'Built {len(list(PUBLIC.rglob("*.html")))} static HTML pages, {len(pres)} program entries; no JavaScript.')


def assert_no_scripts() -> None:
    for p in PUBLIC.rglob('*'):
        if p.is_file() and p.suffix not in ('', '.html', '.css'):
            raise ValueError(f'Disallowed publishing extension: {p}')
        if p.suffix == '.html':
            s=p.read_text(encoding='utf-8')
            if re.search(r'<\s*script\b|\bon\w+\s*=|javascript\s*:',s,re.I):
                raise ValueError(f'HTML contains scripting features: {p}')
            if '{{' in s:
                raise ValueError(f'Unresolved template placeholder: {p}')
    if any(PUBLIC.rglob('*.js')):
        raise ValueError('JavaScript files must not be published')

if __name__ == '__main__':
    build()
