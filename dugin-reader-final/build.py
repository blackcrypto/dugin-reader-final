#!/usr/bin/env python3
"""Assemble the Clare-style reader for Dugin, *The Metaphysics of the Good News*.

Inputs : instalment HTML files + Restorations supplement + Golovin supplement
Output : site/index.html, site/style.css, site/vercel.json

Re-run after adding the missing instalments (Ch_XIV-XVII, Ch_XXVI-XXVII) to SRC:
they will be picked up automatically and their placeholders dropped.
"""
import re, os, json, html, pathlib, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "/mnt/project"
OUT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "/home/claude/site")
OUT.mkdir(parents=True, exist_ok=True)

# Canonical reading order of instalment groups. (file stem, present?)
ORDER = [
    "Ch_I-IV", "Ch_V-VII", "Ch_VIII-IX", "Ch_X-XI", "Ch_XII-XIII",
    "Ch_XIV-XVII",          # Part III — may be missing
    "Ch_XVIII-XXI", "Ch_XXII-XXIII", "Ch_XXIV-XXV",
    "Ch_XXVI-XXVII",        # may be missing
    "Ch_XXVIII-XXIX",
    "Ch_XXX-XXXII", "Ch_XXXIII-XXXIV", "Ch_XXXV-XXXVI", "Ch_XXXVII-XXXVIII",
    "Ch_XXXIX-XL", "Ch_XLI",
    "Ch_XLII-XLIII", "Ch_XLIV-XLV", "Ch_XLVI", "Ch_XLVII-XLVIII",
    "Ch_XLIX-L", "Ch_LI-LIII", "Ch_LIV-LVI",
]
MISSING_INFO = {
    "Ch_XIV-XVII": ("XIV–XVII",
        "Part III · The Metaphysical Aspect of the Most Holy Theotokos",
        "Chapters XIV–XVII (Part III entire: “Head of the Angels”; “The All-Immaculate and Barbelo”; "
        "“The Virgin Mary and Spiritual Realisation”; “He Brought Me to the Banqueting House”). "
        "The delivered instalment file Dugin_Good_News_Ch_XIV-XVII.html was not among the uploads of "
        "14 August 2026. Re-add the file and re-run the build, or commission a retranslation."),
    "Ch_XXVI-XXVII": ("XXVI–XXVII", None,
        "Chapters XXVI–XXVII (“The Sacrament of Marriage: the Soteriological Function of Woman”; "
        "“The Monastic Path and the Transcendence of Love”). The delivered instalment file "
        "Dugin_Good_News_Ch_XXVI-XXVII.html was not among the uploads of 14 August 2026. "
        "Re-add the file and re-run the build, or commission a retranslation."),
}

RX_SECTION   = re.compile(r'<section class="chapter"[^>]*>(.*?)</section>', re.S)
RX_TOKENS    = re.compile(r'(<p class="partline">.*?</p>|<section class="chapter"[^>]*>.*?</section>)', re.S)
RX_APPARATUS = re.compile(r'<div class="apparatus">(.*?)</div>\s*(?=</div>|</body>)', re.S)
RX_EYEBROW   = re.compile(r'<p class="eyebrow">(.*?)</p>', re.S)
RX_H2        = re.compile(r'<h2>(.*?)</h2>', re.S)
RX_RUTITLE   = re.compile(r'<p class="ru-title">(.*?)</p>', re.S)
RX_ROMAN     = re.compile(r'Chapter\s+([IVXL]+)')

def strip_tags(s): return re.sub(r'<[^>]+>', '', s).strip()

def parse_group(path):
    t = open(path, encoding="utf-8").read()
    body = t.split("</header>", 1)[1] if "</header>" in t else t
    m = RX_APPARATUS.search(body)
    apparatus = m.group(1).strip() if m else ""
    body_wo_app = body[:m.start()] if m else body
    items = []
    for tok in RX_TOKENS.findall(body_wo_app):
        if tok.startswith('<p class="partline">'):
            items.append(("part", strip_tags(tok)))
        else:
            inner = RX_SECTION.match(tok).group(1)
            eb  = RX_EYEBROW.search(inner)
            h2  = RX_H2.search(inner)
            ru  = RX_RUTITLE.search(inner)
            rom = RX_ROMAN.search(eb.group(1)) if eb else None
            items.append(("chapter", {
                "roman": rom.group(1) if rom else "",
                "eyebrow": eb.group(1).strip() if eb else "",
                "title": h2.group(1).strip() if h2 else "",
                "title_plain": strip_tags(h2.group(1)) if h2 else "",
                "ru": ru.group(1).strip() if ru else "",
                "html": inner,
            }))
    return items, apparatus

# ---------- Restorations ----------
def slice_between(t, start_pat, end_pat):
    s = re.search(start_pat, t, re.S); assert s, start_pat
    e = re.search(end_pat, t[s.end():], re.S); assert e, end_pat
    return t[s.end(): s.end() + e.start()]

rest = open(os.path.join(SRC, "Dugin_Good_News_Restorations_XXXII_LIV.html"), encoding="utf-8").read()
xxxii_paras = slice_between(rest, r'<p class="ru-title">Православное время</p>', r'<p class="divider">').strip()
liv_paras   = slice_between(rest, r'<p class="ru-title">Свидетельство о православной метафизике</p>', r'<div class="apparatus">').strip()
assert xxxii_paras.count("<p") == 14 and "The Word of God" in xxxii_paras, "XXXII splice sanity"
assert liv_paras.count("<p") == 4 and "vortex of the light of Tabor" in liv_paras, "LIV splice sanity"

rest_app = re.search(r'<div class="apparatus">(.*?)</div>', rest, re.S).group(1)
h3_blocks = {}
for m in re.finditer(r'<h3>(.*?)</h3>(.*?)(?=<h3>|\Z)', rest_app, re.S):
    h3_blocks[strip_tags(m.group(1))] = re.findall(r'<p>.*?</p>', m.group(2), re.S)

def leadin(ps, lead):
    out = []
    for p in ps:
        if "<strong>" in p:
            out.append(p.replace("<p><strong>", f"<p><strong>{lead} — ", 1))
        else:
            out.append(p.replace("<p>", f"<p><strong>{lead}.</strong> ", 1))
    return out

prov = h3_blocks["The restorations and their source"]
APP_EXTRA = {
    "Ch_XIV-XVII": [
        "<p><strong>Restoration (15 Aug 2026) — note markers.</strong> This instalment was "
        "translated from litresp, which strips Dugin\u2019s footnote markers; it was delivered, "
        "and disclosed, marker-less. Markers 89\u2013116 have now been restored from the "
        "studfile transcription (pages 14\u201317), which preserves them: XIV carries "
        "89\u201397, XV only 98, XVI a dense 99\u2013113, XVII 114\u2013116 (the three Song "
        "of Songs citations). All twenty-eight were anchored to their exact positions against "
        "the Russian; continuity 88 \u2192 89\u2026116 \u2192 117 across Parts II\u2013IV "
        "is now closed, and the edition\u2019s marker convention holds without exception.</p>"],
    "Ch_XXX-XXXII":
        leadin([prov[0], prov[2]], "Restoration (14 Aug 2026)")
        + leadin(h3_blocks["Chapter XXXII — markers"], "Chapter XXXII markers")
        + leadin(h3_blocks["Chapter XXXII — flags"], "Restoration"),
    "Ch_LIV-LVI":
        leadin([prov[1]], "Restoration (14 Aug 2026)")
        + leadin(h3_blocks["Chapter LIV — flags"], "Restoration"),
    "Ch_XXXV-XXXVI":
        leadin(h3_blocks["The rune glyph: final verdict"], "Restoration (14 Aug 2026)"),
}

# ---------- Golovin ----------
gol = open(os.path.join(SRC, "Golovin_Review_Metaphysics_Good_News.html"), encoding="utf-8").read()
gol_sec = RX_SECTION.search(gol).group(1)
gol_app = RX_APPARATUS.search(gol).group(1).strip()

# ---------- Assemble ----------
toc, groups_html = [], []
seen_parts = set()

def chapter_id(roman): return f"ch-{roman}"

for stem in ORDER:
    fname = os.path.join(SRC, f"Dugin_Good_News_{stem}.html")
    if not os.path.exists(fname):
        rng, partline, msg = MISSING_INFO[stem]
        block = ""
        if partline:
            block += f'<p class="partline" id="part-{len(seen_parts)+1}">{html.escape(partline)}<br><span class="prov">(part title provisional)</span></p>\n'
            toc.append(("part", partline + " (provisional)", None)); seen_parts.add(partline)
        block += (f'<section class="group missing" id="gap-{stem}"><div class="main">'
                  f'<p class="eyebrow">Chapters {rng}</p>'
                  f'<div class="gap"><p>{html.escape(msg)}</p></div></div></section>')
        groups_html.append(block)
        toc.append(("gap", f"Chapters {rng} — instalment pending", f"gap-{stem}"))
        continue

    items, apparatus = parse_group(fname)
    if stem == "Ch_XXX-XXXII":
        for kind, ch in items:
            if kind == "chapter" and ch["roman"] == "XXXII":
                ch["html"] = (f'<p class="eyebrow">{ch["eyebrow"]}</p><h2>{ch["title"]}</h2>'
                              f'<p class="ru-title">{ch["ru"]}</p>\n{xxxii_paras}')
    if stem == "Ch_LIV-LVI":
        for kind, ch in items:
            if kind == "chapter" and ch["roman"] == "LIV":
                ch["html"] = (f'<p class="eyebrow">{ch["eyebrow"]}</p><h2>{ch["title"]}</h2>'
                              f'<p class="ru-title">{ch["ru"]}</p>\n{liv_paras}')
    if stem in APP_EXTRA:
        apparatus += "\n" + "\n".join(APP_EXTRA[stem])

    main_parts, pre = [], []
    for kind, val in items:
        if kind == "part":
            pre.append(f'<p class="partline">{val}</p>')
            toc.append(("part", val, None)); seen_parts.add(val)
        else:
            cid = chapter_id(val["roman"])
            main_parts.append(f'<section class="chapter" id="{cid}">{val["html"]}</section>')
            toc.append(("ch", f'{val["roman"]} · {val["title_plain"]}', cid))
    rail = (f'<aside class="rail"><div class="rail-inner"><h3>Apparatus · Chapters '
            f'{stem.replace("Ch_","").replace("-","–")}</h3>{apparatus}</div></aside>')
    groups_html.append("\n".join(pre) +
        f'\n<section class="group" id="g-{stem}"><div class="main">' +
        "\n".join(main_parts) + f'</div>{rail}</section>')

# Golovin supplement
toc.append(("part", "Supplement", None))
toc.append(("ch", "Golovin · Review of The Metaphysics of the Good News", "supp-golovin"))
groups_html.append(
    '<p class="partline">Supplement</p>'
    '<section class="group" id="g-golovin"><div class="main">'
    '<section class="chapter" id="supp-golovin">'
    '<p class="eyebrow">Supplement · Contemporary Review</p>'
    '<h2>Evgeny Golovin,<br>Review of <em>The Metaphysics of the Good News</em></h2>'
    '<p class="ru-title">Рецензия на книгу А. Дугина «Метафизика Благой Вести» (1996; Golovin Foundation archive)</p>'
    + gol_sec + '</section></div>'
    '<aside class="rail"><div class="rail-inner"><h3>Apparatus · Golovin Review</h3>'
    + gol_app + '</div></aside></section>')

toc_html = ['<nav id="toc" aria-label="Contents"><div class="toc-head">Contents'
            '<button id="toc-close" aria-label="Close contents">×</button></div><ol>']
for kind, label, target in toc:
    if kind == "part":
        toc_html.append(f'<li class="toc-part">{label}</li>')
    elif kind == "gap":
        toc_html.append(f'<li class="toc-gap"><a href="#{target}">{label}</a></li>')
    else:
        toc_html.append(f'<li><a href="#{target}">{label}</a></li>')
toc_html.append("</ol></nav>")

page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aleksandr Dugin · The Metaphysics of the Good News — Reader Edition</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Cormorant+SC:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css">
</head>
<body>
<div id="topbar">
  <button id="toc-open">Contents</button>
  <span class="tb-title">The Metaphysics of the Good&nbsp;News</span>
  <span class="tb-tools"><button id="focus-btn" title="Hide the apparatus rail">Focus</button><button id="theme-btn" title="Theme: auto / light / dark">Theme</button></span>
</div>
{''.join(toc_html)}
<div id="scrim"></div>
<main>
<header class="book">
  <p class="author">Aleksandr Dugin</p>
  <h1>The Metaphysics of the Good&nbsp;News</h1>
  <p class="subtitle">(Orthodox Esotericism)</p>
  <p class="imprint">Moscow: Arktogeia, 1996 · Volume II of the “Absolute Homeland” cycle</p>
  <p class="imprint">Translated from the Russian · Reader edition, assembled 14 August 2026</p>
  <p class="ed-note">A literary translation with a critical apparatus. Dugin’s note markers
  (<sup class="src">n</sup>) are preserved in the text; the notes’ contents are not reproduced
  in this edition. The apparatus beside each chapter group records translator decisions and
  the author’s factual errors, which are rendered as written and flagged rather than silently
  corrected. Two instalments (Chapters XIV–XVII and XXVI–XXVII) are pending and marked in place.</p>
</header>
{chr(10).join(groups_html)}
<footer><p class="divider">✛ ✛ ✛</p>
<p class="colophon">Set in EB Garamond and Cormorant SC · parchment, ink, porphyry, gold</p></footer>
</main>
<script>
(function(){{
  var root=document.documentElement, KEY='dugin-reader';
  var st={{}}; try{{st=JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{}}
  function save(){{try{{localStorage.setItem(KEY,JSON.stringify(st))}}catch(e){{}}}}
  function applyTheme(){{root.setAttribute('data-theme',st.theme||'auto');
    document.getElementById('theme-btn').textContent='Theme: '+(st.theme||'auto');}}
  function applyFocus(){{document.body.classList.toggle('focus',!!st.focus);
    document.getElementById('focus-btn').textContent=st.focus?'Show apparatus':'Focus';}}
  document.getElementById('theme-btn').onclick=function(){{
    st.theme={{auto:'light',light:'dark',dark:'auto'}}[st.theme||'auto'];save();applyTheme();}};
  document.getElementById('focus-btn').onclick=function(){{st.focus=!st.focus;save();applyFocus();}};
  var toc=document.getElementById('toc'),scrim=document.getElementById('scrim');
  function openToc(o){{toc.classList.toggle('open',o);scrim.classList.toggle('show',o);}}
  document.getElementById('toc-open').onclick=function(){{openToc(true)}};
  document.getElementById('toc-close').onclick=function(){{openToc(false)}};
  scrim.onclick=function(){{openToc(false)}};
  toc.addEventListener('click',function(e){{if(e.target.tagName==='A')openToc(false)}});
  applyTheme();applyFocus();
}})();
</script>
</body>
</html>"""

open(OUT/"index.html","w",encoding="utf-8").write(page)
open(OUT/"vercel.json","w").write(json.dumps({"cleanUrls": True}, indent=2))
print("chapters:", page.count('<section class="chapter"'),
      "| groups:", page.count('<section class="group'),
      "| rails:", page.count('class="rail"'),
      "| gaps:", page.count('class="gap"'),
      "| bytes:", len(page.encode()))
