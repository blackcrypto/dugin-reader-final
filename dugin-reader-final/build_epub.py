#!/usr/bin/env python3
"""build_epub.py — the EPUB 3 edition of the reader (Dugin, *The Metaphysics of the Good News*).

usage: python3 build_epub.py [--no-check] [--out metaphysics-of-the-good-news.epub]

Generated, never hand-edited, from the reader's own output: it reads `index.html` (what `build.py` wrote) and
transforms it into EPUB 3 XHTML, so the EPUB can never say anything the reader does not say. Built on the pattern
of the Aizu Boshin Senshi EPUB (`scripts/build_epub.py` there).

Structure: title page · about this edition · the fifty-six chapters, one file each, the part line standing above
the first chapter of its part · the apparatus of each chapter group, which the reader sets in the margin rail,
as a section of its own after the group's last chapter (where the reader itself puts it on a narrow screen) ·
the Golovin supplement and its apparatus · colophon. The table of contents is nested by part. Dugin's note
markers stay as superscripts; the source notes whose content the apparatus gives become EPUB 3 pop-up notes
(epub:type="footnote", reached by an epub:type="noteref" link, with a back-link) and stay in the apparatus too.
Each chapter ends with a link to its group's apparatus, and each apparatus links back to its chapters.

Type: subsets of the reader's own faces, EB Garamond and Cormorant SC (SIL OFL 1.1), as static TrueType, plus
one-glyph subsets of Noto Sans Runic and Noto Sans Symbols 2 for the two characters those faces lack; the build
fails unless every character of the book is covered by the face it is set in. No colours and no fixed sizes:
the reading app sets the body size and the page.

Checks before writing: the text of every chapter and every apparatus is the reader's text, character for
character; every link resolves; every note resolves both ways; every document is well-formed XML.
Validation: epubcheck, zero errors and zero warnings (the script fails otherwise).

Font sources are fetched once into ../fonts-src/ (not committed); see FONT_GET.
"""
import datetime
import html
import io
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
READER = ROOT / "index.html"
FONTS = ROOT.parent / "fonts-src"
OUT_DEFAULT = ROOT / "metaphysics-of-the-good-news.epub"

XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
BOOK_ID = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:dugin-reader:metaphysics-of-the-good-news:en"))
TITLE = "The Metaphysics of the Good News"
SUBTITLE = "Orthodox Esotericism"

VOID = {"br", "hr", "img", "meta", "link", "input", "wbr"}

# the reader's edition note still carries this sentence from before the two instalments arrived; it is dropped
# here only when the reader in fact has every chapter and no gap placeholder (checked in main)
STALE = "Two instalments (Chapters XIV–XVII and XXVI–XXVII) are pending and marked in place."

FONT_GET = """mkdir -p ../fonts-src && cd ../fonts-src && B=https://raw.githubusercontent.com/google/fonts/main/ofl && \\
  curl -sSL -o 'EBGaramond[wght].ttf' "$B/ebgaramond/EBGaramond%5Bwght%5D.ttf" && \\
  curl -sSL -o 'EBGaramond-Italic[wght].ttf' "$B/ebgaramond/EBGaramond-Italic%5Bwght%5D.ttf" && \\
  curl -sSL -o CormorantSC-Regular.ttf "$B/cormorantsc/CormorantSC-Regular.ttf" && \\
  curl -sSL -o CormorantSC-SemiBold.ttf "$B/cormorantsc/CormorantSC-SemiBold.ttf" && \\
  curl -sSL -o NotoSansRunic-Regular.ttf "$B/notosansrunic/NotoSansRunic-Regular.ttf" && \\
  curl -sSL -o NotoSansSymbols2-Regular.ttf "$B/notosanssymbols2/NotoSansSymbols2-Regular.ttf\""""

# (file in the EPUB, source file, wght instance or None, CSS family, CSS weight, CSS style)
FACES = [
    ("gn-serif-regular.ttf", "EBGaramond[wght].ttf", 400, "GN Serif", "normal", "normal"),
    ("gn-serif-italic.ttf", "EBGaramond-Italic[wght].ttf", 400, "GN Serif", "normal", "italic"),
    ("gn-serif-semibold.ttf", "EBGaramond[wght].ttf", 600, "GN Serif", "bold", "normal"),
    ("gn-sc-regular.ttf", "CormorantSC-Regular.ttf", None, "GN SC", "normal", "normal"),
    ("gn-sc-semibold.ttf", "CormorantSC-SemiBold.ttf", None, "GN SC", "bold", "normal"),
    ("gn-runic.ttf", "NotoSansRunic-Regular.ttf", None, "GN Runic", "normal", "normal"),
    ("gn-symbols.ttf", "NotoSansSymbols2-Regular.ttf", None, "GN Symbols", "normal", "normal"),
]
FALLBACK_FACES = ("gn-runic.ttf", "gn-symbols.ttf")


def esc(s):
    return html.escape(s, quote=False)


def attr(s):
    return html.escape(s, quote=True)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


# ----------------------------------------------------------------------------------------
# a small DOM from the reader's HTML (the reader writes well-formed, lower-case, quoted HTML)
# ----------------------------------------------------------------------------------------

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs or {}), [], parent

    def cls(self):
        return (self.attrs.get("class") or "").split()

    def text(self, br=""):
        return "".join(c if isinstance(c, str) else (br if c.tag == "br" else c.text(br)) for c in self.children)

    def find_all(self, pred, out=None):
        out = [] if out is None else out
        for c in self.children:
            if isinstance(c, Node):
                if pred(c):
                    out.append(c)
                c.find_all(pred, out)
        return out

    def find(self, pred):
        r = self.find_all(pred)
        return r[0] if r else None

    def kids(self, pred=lambda x: True):
        return [c for c in self.children if isinstance(c, Node) and pred(c)]


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(h):
    tb = TreeBuilder()
    tb.feed(h)
    tb.close()
    return tb.root


def serialize(n, out):
    if isinstance(n, str):
        out.append(esc(n))
        return
    if n.tag == "#root":
        for c in n.children:
            serialize(c, out)
        return
    a = "".join(f' {k}="{attr(v)}"' for k, v in n.attrs.items() if v is not None)
    if n.tag in VOID:
        out.append(f"<{n.tag}{a}/>")
        return
    out.append(f"<{n.tag}{a}>")
    for c in n.children:
        serialize(c, out)
    out.append(f"</{n.tag}>")


def to_xhtml(n):
    out = []
    serialize(n, out)
    return "".join(out)


def inner_xhtml(n):
    return "".join(to_xhtml(c) for c in n.children)


def has(tag, cls=None):
    return lambda x: x.tag == tag and (cls is None or cls in x.cls())


# ----------------------------------------------------------------------------------------
# reading the reader
# ----------------------------------------------------------------------------------------

class Chapter:
    def __init__(self, node, gid):
        self.node, self.gid, self.id = node, gid, node.attrs["id"]
        self.roman = self.id[3:] if self.id.startswith("ch-") else ""
        self.part = None            # the part line that stands above this chapter, if it opens a part
        self.part_id = None
        self.notes = []             # [(number, content nodes)] of the source notes marked in this chapter
        self.fname = self.label = self.title = None
        self.source_text = norm(node.text())


class Group:
    def __init__(self, node):
        self.id = node.attrs["id"]                                   # g-Ch_I-IV, g-golovin
        main = node.kids(has("div", "main"))
        rail = node.kids(has("aside", "rail"))
        if len(main) != 1 or len(rail) != 1:
            raise SystemExit(f"build_epub: group {self.id} is not a main column and a rail")
        self.chapters = [Chapter(c, self.id) for c in main[0].kids(has("section", "chapter"))]
        if len(self.chapters) != len(main[0].kids()):
            raise SystemExit(f"build_epub: group {self.id} has something other than chapters in its main column")
        inner = rail[0].kids(has("div", "rail-inner"))[0]
        heads = inner.kids(has("h3"))
        if not heads or heads[0] is not inner.kids()[0]:
            raise SystemExit(f"build_epub: rail of {self.id} does not open with its heading")
        self.app_title = re.sub(r"Chapters ([IVXLC]+)$", r"Chapter \1", norm(heads[0].text()))
        drop = [heads[0]]
        if len(heads) > 1 and norm(heads[1].text()) == "Apparatus" and heads[1] is inner.kids()[1]:
            drop.append(heads[1])                                    # the instalment's own bare heading
        self.app_nodes = [c for c in inner.children if not any(c is d for d in drop)]
        self.app_source_text = norm("".join(c if isinstance(c, str) else c.text() for c in self.app_nodes))
        stem = "golovin" if self.id == "g-golovin" else self.id.replace("g-Ch_", "")
        self.app_id = "app-" + stem
        self.app_fname = f"apparatus-{stem}.xhtml"


def read_reader(src):
    root = parse(src)
    main = root.find(has("main"))
    nav = root.find(lambda x: x.tag == "nav" and x.attrs.get("id") == "toc")
    if main is None or nav is None:
        raise SystemExit("build_epub: index.html has no <main> / contents — is it the reader build.py wrote?")
    if main.find(lambda x: "gap" in x.cls() or "missing" in x.cls()):
        raise SystemExit("build_epub: the reader still has a missing-instalment placeholder — finish the reader first")
    book = main.find(has("header", "book"))
    footer = main.find(has("footer"))
    groups = [Group(g) for g in main.kids(has("section", "group"))]
    # the part each chapter opens comes from the reader's contents (in the body the part lines are hoisted
    # above the whole chapter group, which is right only when a part begins with its group)
    toc, cur = [], None
    for li in nav.find_all(has("li")):
        if "toc-part" in li.cls():
            cur = norm(li.text())
        else:
            a = li.find(has("a"))
            toc.append((cur, a.attrs["href"].lstrip("#"), norm(a.text())))
    body_parts = [norm(p.text()) for p in main.kids(has("p", "partline"))]
    toc_parts = list(dict.fromkeys(p for p, _, _ in toc))
    if body_parts != toc_parts:
        raise SystemExit(f"build_epub: part lines of the body and of the contents differ: {body_parts} / {toc_parts}")
    return book, footer, groups, toc


# ----------------------------------------------------------------------------------------
# the transform
# ----------------------------------------------------------------------------------------

def chapter_title(ch):
    h2 = ch.node.find(has("h2"))
    return norm(h2.text(br=" "))


def collect_notes(group):
    """The source notes the apparatus gives (<p><span class="note-num">n</span> …</p>), each assigned to the
    chapter of the group that carries its marker."""
    n_found = 0
    for p in [c for c in group.app_nodes if isinstance(c, Node) and c.tag == "p"]:
        kids = p.kids()
        if not kids or "note-num" not in kids[0].cls() or p.children[0] is not kids[0]:
            continue
        num = norm(kids[0].text())
        owners = [ch for ch in group.chapters
                  if ch.node.find(lambda x: x.tag == "sup" and "src" in x.cls() and norm(x.text()) == num)]
        marks = sum(len(ch.node.find_all(lambda x: x.tag == "sup" and "src" in x.cls() and norm(x.text()) == num))
                    for ch in group.chapters)
        if marks != 1:
            raise SystemExit(f"build_epub: source note {num} of {group.id} has {marks} markers in its chapters")
        owners[0].notes.append((num, p.children[1:]))
        n_found += 1
    return n_found


def transform_chapter(ch):
    node = ch.node
    notes = dict(ch.notes)
    for h2 in node.find_all(has("h2")):
        h2.tag = "h1"
        h2.attrs = {"class": "ch-title"}
    for sp in node.find_all(lambda x: x.tag == "span" and "style" in x.attrs):
        sp.attrs = {"class": "ch-sub"}
    for p in node.find_all(has("p", "ru-title")):
        p.attrs.update({"lang": "ru", "xml:lang": "ru"})
    for sup in node.find_all(has("sup", "src")):
        num = norm(sup.text())
        if num in notes:
            a = Node("a", {"class": "nm", "id": f"nr{num}", "href": f"#n{num}", "epub:type": "noteref",
                           "role": "doc-noteref"}, sup)
            a.children = sup.children
            sup.children = [a]
    if norm(node.text()) != ch.source_text:
        raise SystemExit(f"build_epub: the transform changed the text of {ch.id}")


def note_asides(ch):
    parts = []
    for num, children in ch.notes:
        body = []
        for c in children:
            serialize(c, body)
        parts.append(f'<aside epub:type="footnote" role="doc-footnote" id="n{num}" class="note">'
                     f'<p><span class="note-n">{esc(num)}</span>{"".join(body).rstrip()} '
                     f'<a href="#nr{num}" role="doc-backlink" class="backlink" title="back to the text">↑</a></p></aside>')
    return "\n".join(parts)


def chapter_xhtml(ch, group, epub_type):
    part = (f'<p class="partline" id="{ch.part_id}">{esc(ch.part)}</p>\n' if ch.part else "")
    to_app = f'<p class="to-app"><a href="{group.app_fname}">{esc(group.app_title)}</a></p>'
    role = {"chapter": "doc-chapter", "appendix": "doc-appendix"}[epub_type]
    body = (f'<section epub:type="{epub_type}" role="{role}" id="{ch.id}" class="chapter">\n{part}'
            f'{inner_xhtml(ch.node).strip()}\n{to_app}\n</section>\n')
    if ch.notes:
        body += (f'<section class="notes" epub:type="footnotes" aria-label="Notes">\n{note_asides(ch)}\n</section>\n')
    return body


def apparatus_xhtml(group):
    links = " · ".join(f'<a href="{ch.fname}">{esc(ch.roman or "Review")}</a>' for ch in group.chapters)
    inner = "".join(to_xhtml(c) for c in group.app_nodes).strip()
    return (f'<section class="apparatus" id="{group.app_id}">\n<h1 class="app-title">{esc(group.app_title)}</h1>\n'
            f'<p class="app-chapters">{links}</p>\n{inner}\n</section>\n')


def xhtml_doc(title, body, body_type="bodymatter"):
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_NS}" lang="en" xml:lang="en">\n<head>\n'
            f'<meta charset="utf-8"/>\n<title>{esc(title)}</title>\n'
            f'<link rel="stylesheet" type="text/css" href="style.css"/>\n</head>\n'
            f'<body epub:type="{body_type}">\n{body}\n</body>\n</html>\n')


def titlepage_xhtml(book):
    one = lambda c: norm(book.find(has("p", c)).text())
    imprints = [norm(p.text()) for p in book.find_all(has("p", "imprint"))]
    return ('<section epub:type="titlepage" id="titlepage">\n'
            f'<p class="tp-author">{esc(one("author"))}</p>\n'
            f'<h1 class="tp-title">{esc(norm(book.find(has("h1")).text()))}</h1>\n'
            f'<p class="tp-sub">{esc(one("subtitle"))}</p>\n'
            + "".join(f'<p class="tp-imprint">{esc(i)}</p>\n' for i in imprints) + '</section>')


def about_xhtml(book, n_notes, note_range, dropped_stale):
    note = book.find(has("p", "ed-note"))
    for i, c in enumerate(note.children):
        if isinstance(c, str):
            note.children[i] = re.sub(r"\s+", " ", c)
    if dropped_stale:
        last = note.children[-1]
        note.children[-1] = last.replace(" " + STALE, "").replace(STALE, "")
    words = "no one two three four five six seven eight nine ten eleven twelve".split()
    count = words[n_notes] if n_notes < len(words) else str(n_notes)
    pop = (f' The {count} source notes whose content the apparatus gives (nos. {note_range}) also open from '
           f'their markers as pop-up notes.' if n_notes else "")
    return ('<section epub:type="preface" role="doc-preface" id="about">\n<h1>About this edition</h1>\n'
            f'<p>{inner_xhtml(note).strip()}</p>\n<h2>This EPUB</h2>\n'
            '<p>This file was generated from the web reader edition by its <em>build_epub.py</em>, and says '
            'nothing the reader does not say. The apparatus, which the reader sets in the margin beside each '
            'chapter group, here follows the last chapter of its group as a section of its own; every chapter '
            'ends with a link to it, and it links back to its chapters.' + pop +
            ' The type is the reader’s — EB Garamond and Cormorant SC, embedded as subsets.</p>\n</section>')


def colophon_xhtml(footer, today):
    div = norm(footer.find(has("p", "divider")).text())
    col = norm(footer.find(has("p", "colophon")).text())
    if not col.startswith("Set in "):
        raise SystemExit(f"build_epub: unexpected reader colophon: {col!r}")
    faces = col.split(" · ")[0]          # the reader's second clause names its screen colours; the EPUB sets none
    return ('<section epub:type="colophon" role="doc-colophon" id="colophon">\n'
            f'<p class="divider">{esc(div)}</p>\n<p class="colophon">{esc(faces)}</p>\n'
            f'<p class="colophon">EPUB edition generated {today} from the reader edition.</p>\n'
            '<p class="colophon">EB Garamond © 2017 The EB Garamond Project Authors; Cormorant SC © 2015 The '
            'Cormorant Project Authors; Noto Sans Runic and Noto Sans Symbols 2 © The Noto Project Authors. '
            'All four are embedded as subsets under the SIL Open Font License, Version 1.1.</p>\n</section>')


# ----------------------------------------------------------------------------------------
# css and fonts
# ----------------------------------------------------------------------------------------

def css():
    faces = "\n".join(
        f'@font-face{{font-family:"{fam}";src:url("fonts/{name}");font-weight:{w};font-style:{s}}}'
        for name, _, _, fam, w, s in FACES)
    return f"""/* EPUB stylesheet — no fixed sizes and no colours: the reading app sets the body size and the page */
{faces}
body{{font-family:"GN Serif","GN Runic","GN Symbols",Georgia,"Times New Roman",serif;line-height:1.5}}
p{{margin:0 0 .9em;text-align:justify;-webkit-hyphens:auto;-epub-hyphens:auto;hyphens:auto}}
h1,h2,.eyebrow,.partline,.tp-author,.app-chapters,.to-app{{font-family:"GN SC","GN Serif",Georgia,serif;-webkit-hyphens:none;-epub-hyphens:none;hyphens:none}}
h1{{font-weight:bold;font-size:1.5em;line-height:1.2;text-align:center;margin:0 0 .4em;letter-spacing:.015em}}
h2{{font-weight:bold;font-size:1.15em;margin:1.6em 0 .6em}}
.ch-sub{{font-size:.78em}}
.partline{{text-align:center;font-size:1.15em;letter-spacing:.16em;text-transform:uppercase;margin:1.5em 0 3.5em;page-break-after:avoid;break-after:avoid}}
.eyebrow{{text-align:center;font-size:.82em;letter-spacing:.24em;text-transform:uppercase;margin:1.5em 0 .6em;page-break-after:avoid;break-after:avoid}}
.ru-title{{text-align:center;font-style:italic;font-size:.9em;margin:0 0 2em;-webkit-hyphens:none;-epub-hyphens:none;hyphens:none}}
sup{{font-size:.68em;line-height:0;vertical-align:super}}
sup.src{{font-weight:normal;letter-spacing:.02em}}
a.nm{{text-decoration:none;border-bottom:1px solid currentColor}}
blockquote{{margin:1.2em 0 1.2em .2em;padding:0 0 0 1em;border-left:2px solid currentColor;font-style:italic}}
blockquote p{{margin:0 0 .6em}}
ol,ul{{margin:0 0 .9em;padding-left:1.6em}}
li{{margin:0 0 .3em}}
.divider{{text-align:center;letter-spacing:.6em;margin:3em 0}}
.to-app{{text-align:center;font-size:.82em;letter-spacing:.12em;margin:3em 0 0}}
.to-app a,.app-chapters a{{text-decoration:none;border-bottom:1px solid currentColor;color:inherit}}
section.apparatus p{{text-align:left;font-size:.92em;margin:0 0 .8em}}
section.apparatus h1{{font-size:1.05em;letter-spacing:.1em;text-transform:uppercase;margin:1.5em 0 .6em}}
section.apparatus p.app-chapters{{text-align:center;font-size:.85em;letter-spacing:.1em;margin:0 0 2em}}
.note-num,.note-n{{font-weight:bold;margin-right:.3em}}
section.notes{{margin-top:2.5em;border-top:1px solid currentColor;padding-top:1em;font-size:.9em}}
aside.note p{{margin:0 0 .8em;text-align:left}}
.backlink{{text-decoration:none;margin-left:.3em}}
.tp-author{{text-align:center;letter-spacing:.3em;text-transform:uppercase;font-size:.9em;margin:3em 0 1em}}
.tp-title{{font-size:2em;line-height:1.15;margin:.2em 0 .3em}}
.tp-sub{{text-align:center;font-style:italic;margin:.2em 0 2.5em}}
.tp-imprint{{text-align:center;font-size:.88em;margin:.2em 0;-webkit-hyphens:none;-epub-hyphens:none;hyphens:none}}
.colophon{{text-align:center;font-size:.85em;font-style:italic;-webkit-hyphens:none;-epub-hyphens:none;hyphens:none}}
nav ol{{list-style:none;padding-left:0}}
nav ol ol{{padding-left:1.2em;margin:.3em 0 .8em}}
nav a{{text-decoration:none;color:inherit}}
"""


def plain(xhtml):
    return html.unescape(re.sub(r"<[^>]+>", "", xhtml))


def styled_text(docs, pattern):
    return "".join(plain(m.group(0)) for _, _, d in docs for m in re.finditer(pattern, d, re.S))


def build_fonts(docs, nav):
    """Subset every face to the characters of the book; return ({file: bytes}, report lines). Fails when a
    character of the book is not in the face it is set in."""
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
    except ImportError:
        raise SystemExit("build_epub: fontTools is needed (python3 -m pip install fonttools)")
    missing_src = [src for _, src, _, _, _, _ in FACES if not (FONTS / src).exists()]
    if missing_src:
        raise SystemExit(f"build_epub: font sources absent from {FONTS}: {missing_src}. Fetch them once "
                         f"(do not commit them):\n  {FONT_GET}")
    body_only = [(i, f, re.sub(r"<head>.*?</head>", "", d, flags=re.S)) for i, f, d in docs]
    everything = {c for _, _, d in body_only for c in plain(d)} | set(plain(re.sub(r"<head>.*?</head>", "", nav, flags=re.S)))
    everything = {c for c in everything if not c.isspace() or c == " "}
    # what is set in which face (the CSS above): small caps for headings and labels, italic and semibold by tag
    sc = set(styled_text(body_only, r'<h[12][ >].*?</h[12]>|<p class="(?:eyebrow|partline|tp-author|app-chapters|to-app)".*?</p>'))
    italic = set(styled_text(body_only, r'<em>.*?</em>|<blockquote>.*?</blockquote>|<p class="(?:ru-title|tp-sub|colophon)".*?</p>'))
    bold = set(styled_text(body_only, r'<strong>.*?</strong>|<span class="note-n(?:um)?">.*?</span>'))
    need = {"gn-serif-regular.ttf": everything, "gn-serif-italic.ttf": italic, "gn-serif-semibold.ttf": bold,
            "gn-sc-regular.ttf": sc, "gn-sc-semibold.ttf": sc}
    out, report, cmaps = {}, [], {}
    body_cmap = set(TTFont(FONTS / FACES[0][1]).getBestCmap())
    for name, src, wght, _, _, _ in FACES:
        font = TTFont(FONTS / src)
        # a fallback face carries only what the body face lacks
        wanted = {c for c in everything if ord(c) not in body_cmap} if name in FALLBACK_FACES else everything
        if wght is not None:
            font = instancer.instantiateVariableFont(font, {"wght": wght})
        opts = subset.Options()
        opts.hinting = False
        opts.notdef_outline = True
        opts.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]       # keeps the copyright and licence records
        opts.drop_tables += ["DSIG"]
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=[ord(c) for c in wanted])
        sub.subset(font)
        buf = io.BytesIO()
        font.save(buf)
        out[name] = buf.getvalue()
        cmaps[name] = set(TTFont(io.BytesIO(out[name])).getBestCmap())
        report.append(f"{name} {len(cmaps[name])} glyph-mapped characters, {len(out[name]):,} bytes")
    fallback = set().union(*(cmaps[f] for f in FALLBACK_FACES))
    problems = []
    for name, chars in need.items():
        miss = sorted(c for c in chars if not c.isspace() and ord(c) not in cmaps[name] and ord(c) not in fallback)
        if miss:
            problems.append(f"{name}: no glyph for {' '.join(f'{c} U+{ord(c):04X}' for c in miss)}")
    via = sorted(c for c in everything if ord(c) not in cmaps["gn-serif-regular.ttf"])
    report.append(f"{len(everything)} distinct characters in the book; by fallback face: "
                  + (" ".join(f"{c} U+{ord(c):04X}" for c in via) or "none"))
    if problems:
        print("\n".join(problems))
        raise SystemExit("build_epub: font coverage incomplete")
    return out, report


# ----------------------------------------------------------------------------------------
# nav and package
# ----------------------------------------------------------------------------------------

def nav_xhtml(front, parts, back, first_body):
    def li(href, label, children=None):
        sub = ("\n<ol>\n" + "\n".join(li(h, t) for h, t in children) + "\n</ol>\n") if children else ""
        return f'<li><a href="{href}">{esc(label)}</a>{sub}</li>'
    toc = "\n".join([li(h, t) for h, t in front] + [li(h, t, ch) for h, t, ch in parts] + [li(h, t) for h, t in back])
    body = (f'<nav epub:type="toc" role="doc-toc" id="toc"><h1>Contents</h1>\n<ol>\n{toc}\n</ol>\n</nav>\n'
            f'<nav epub:type="landmarks" hidden="hidden"><h1>Landmarks</h1>\n<ol>\n'
            f'<li><a epub:type="titlepage" href="titlepage.xhtml">Title page</a></li>\n'
            f'<li><a epub:type="bodymatter" href="{first_body}">Start of the text</a></li>\n'
            f'<li><a epub:type="colophon" href="colophon.xhtml">Colophon</a></li>\n</ol>\n</nav>')
    return xhtml_doc("Contents", body, body_type="frontmatter")


def package_opf(items, spine_ids, modified):
    man = "\n".join(f'<item id="{iid}" href="{href}" media-type="{mt}"' + (f' properties="{p}"' if p else "") + "/>"
                    for iid, href, mt, p in items)
    sp = "\n".join(f'<itemref idref="{i}"/>' for i in spine_ids)
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="en">\n'
            f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'<dc:identifier id="bookid">{BOOK_ID}</dc:identifier>\n'
            f'<dc:title id="t1">{esc(TITLE)}</dc:title>\n'
            f'<meta refines="#t1" property="title-type">main</meta>\n'
            f'<dc:title id="t2">{esc(SUBTITLE)}</dc:title>\n'
            f'<meta refines="#t2" property="title-type">subtitle</meta>\n'
            f'<dc:language>en</dc:language>\n<dc:language>ru</dc:language>\n'
            f'<dc:creator id="c1">Aleksandr Dugin</dc:creator>\n'
            f'<meta refines="#c1" property="role" scheme="marc:relators">aut</meta>\n'
            f'<meta refines="#c1" property="file-as">Dugin, Aleksandr</meta>\n'
            f'<dc:contributor id="c2">Evgeny Golovin</dc:contributor>\n'
            f'<meta refines="#c2" property="role" scheme="marc:relators">wst</meta>\n'
            f'<dc:date>1996</dc:date>\n'
            f'<dc:source>Метафизика Благой Вести (Moscow: Arktogeia, 1996)</dc:source>\n'
            f'<dc:description>English translation of Aleksandr Dugin, The Metaphysics of the Good News (Orthodox '
            f'Esotericism) (Moscow: Arktogeia, 1996): the fifty-six chapters with the translator’s critical '
            f'apparatus, and Evgeny Golovin’s contemporary review as a supplement.</dc:description>\n'
            f'<meta property="dcterms:modified">{modified}</meta>\n'
            f'</metadata>\n<manifest>\n{man}\n</manifest>\n<spine>\n{sp}\n</spine>\n</package>\n')


CONTAINER = ('<?xml version="1.0" encoding="utf-8"?>\n'
             '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
             '<rootfiles><rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles>\n'
             '</container>\n')


# ----------------------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------------------

def main():
    out_path = OUT_DEFAULT
    if "--out" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--out") + 1])
    src = READER.read_text(encoding="utf-8")
    book, footer, groups, toc = read_reader(src)

    chapters = [ch for g in groups for ch in g.chapters]
    by_id = {ch.id: ch for ch in chapters}
    if [t for _, t, _ in toc] != [ch.id for ch in chapters]:
        raise SystemExit("build_epub: the reader's contents and its chapters are not the same sequence")
    main_chapters = [ch for ch in chapters if ch.roman]
    if len(main_chapters) != 56 or len(chapters) != 57:
        raise SystemExit(f"build_epub: expected 56 chapters and the supplement, found {len(main_chapters)} + "
                         f"{len(chapters) - len(main_chapters)}")

    # names, labels, parts
    n = 0
    for ch in chapters:
        if ch.roman:
            n += 1
            ch.fname = f"ch{n:02d}.xhtml"
            ch.title = chapter_title(ch)
            ch.label = f"{ch.roman} · {ch.title}"
        else:
            ch.fname = "golovin.xhtml"
            ch.title = chapter_title(ch)
            ch.label = next(lbl for _, t, lbl in toc if t == ch.id)
    seen_parts = []
    for part, target, label in toc:
        ch = by_id[target]
        # the reader's own contents label drops the line break of a two-line title without a space; apart from
        # that the two must agree
        if label.replace(" ", "") != ch.label.replace(" ", ""):
            raise SystemExit(f"build_epub: contents label {label!r} is not the chapter's {ch.label!r}")
        if part not in seen_parts:
            seen_parts.append(part)
            ch.part, ch.part_id = part, f"part-{len(seen_parts)}"

    n_notes, note_nums = 0, []
    for g in groups:
        n_notes += collect_notes(g)
    for ch in chapters:
        note_nums += [int(num) for num, _ in ch.notes]
        transform_chapter(ch)
    note_range = (f"{min(note_nums)}–{max(note_nums)}" if note_nums and sorted(note_nums) ==
                  list(range(min(note_nums), max(note_nums) + 1)) else ", ".join(map(str, sorted(note_nums))))

    have = {ch.roman for ch in main_chapters}
    dropped_stale = STALE in norm(book.find(has("p", "ed-note")).text()) and \
        {"XIV", "XV", "XVI", "XVII", "XXVI", "XXVII"} <= have

    today = datetime.date.today().strftime("%-d %B %Y")
    # documents in spine order: (id, file, xhtml)
    docs = [("titlepage", "titlepage.xhtml", xhtml_doc("Title page", titlepage_xhtml(book), "frontmatter")),
            ("about", "about.xhtml", xhtml_doc("About this edition",
                                               about_xhtml(book, n_notes, note_range, dropped_stale), "frontmatter"))]
    for g in groups:
        supp = g.id == "g-golovin"
        for ch in g.chapters:
            docs.append((ch.fname[:-6], ch.fname,
                         xhtml_doc(ch.label, chapter_xhtml(ch, g, "appendix" if supp else "chapter"),
                                   "backmatter" if supp else "bodymatter")))
        docs.append((g.app_fname[:-6], g.app_fname,
                     xhtml_doc(g.app_title, apparatus_xhtml(g), "backmatter" if supp else "bodymatter")))
    docs.append(("colophon", "colophon.xhtml", xhtml_doc("Colophon", colophon_xhtml(footer, today), "backmatter")))

    # contents, nested by part; an apparatus stands after the last chapter of its group
    last_of_group = {g.chapters[-1].id: g for g in groups}
    parts = []
    for ch in chapters:
        if ch.part:
            parts.append((ch.fname, ch.part, []))       # the part line is the first thing in that file
        parts[-1][2].append((ch.fname, ch.label))
        if ch.id in last_of_group:
            g = last_of_group[ch.id]
            parts[-1][2].append((g.app_fname, g.app_title))
    nav = nav_xhtml([("titlepage.xhtml", "Title page"), ("about.xhtml", "About this edition")], parts,
                    [("colophon.xhtml", "Colophon")], chapters[0].fname)

    # ---- verification before writing -------------------------------------------------------------
    problems = []
    all_docs = docs + [("nav", "nav.xhtml", nav)]
    ids = {f: set(re.findall(r' id="([^"]+)"', d)) for _, f, d in all_docs}
    for _, fname, doc in all_docs:
        try:
            ET.fromstring(doc.split("<!DOCTYPE html>\n", 1)[1].encode("utf-8"))
        except ET.ParseError as e:
            problems.append(f"{fname}: not well-formed XML ({e})")
        dup = {i for i in ids[fname] if len(re.findall(rf' id="{re.escape(i)}"', doc)) > 1}
        if dup:
            problems.append(f"{fname}: duplicate ids {sorted(dup)}")
        for href in re.findall(r'<a [^>]*href="([^"]+)"', doc):
            f, _, frag = href.partition("#")
            f = f or fname
            if f not in ids or (frag and frag not in ids[f]):
                problems.append(f"{fname}: link {href} does not resolve")
        for nid in re.findall(r'epub:type="noteref"[^>]*href="#([^"]+)"', doc):
            if not re.search(rf'<aside [^>]*id="{re.escape(nid)}"', doc):
                problems.append(f"{fname}: noteref #{nid} has no footnote aside")
        for nid in re.findall(r'<aside [^>]*id="([^"]+)"', doc):
            if not re.search(rf'id="{re.escape(nid)}"[^>]*>.*?href="#nr{re.escape(nid[1:])}"', doc, re.S):
                problems.append(f"{fname}: aside #{nid} has no back-link")
            if f'href="#{nid}"' not in doc:
                problems.append(f"{fname}: aside #{nid} is not reachable from a noteref")
    # the text is the reader's text: every chapter and every apparatus, read back out of the documents
    doc_of = {f: d for _, f, d in docs}

    def section_text(doc, sid):
        m = re.search(rf'<section [^>]*id="{re.escape(sid)}"[^>]*>(.*?)\n</section>', doc, re.S)
        s = m.group(1)
        s = re.sub(r'<p class="(?:partline|to-app|app-chapters)".*?</p>|<h1 class="app-title">.*?</h1>', "", s, flags=re.S)
        return norm(plain(s))
    for ch in chapters:
        if section_text(doc_of[ch.fname], ch.id) != ch.source_text:
            problems.append(f"{ch.fname}: text differs from the reader's {ch.id}")
    for g in groups:
        if section_text(doc_of[g.app_fname], g.app_id) != g.app_source_text:
            problems.append(f"{g.app_fname}: text differs from the reader's rail of {g.id}")
    reader_marks = len(re.findall(r'<sup class="src">\d+</sup>', src))
    epub_marks = sum(len(re.findall(r'<sup class="src">(?:<a [^>]*>)?\d+(?:</a>)?</sup>', d)) for _, f, d in docs
                     if f.startswith(("ch", "golovin")))
    if reader_marks != epub_marks:
        problems.append(f"note markers: reader {reader_marks}, epub {epub_marks}")
    if problems:
        print("\n".join(problems[:40]))
        raise SystemExit(f"build_epub: {len(problems)} problem(s)")

    # ---- write -----------------------------------------------------------------------------------
    fonts, font_report = build_fonts(docs, nav)
    modified = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        items = [("nav", "nav.xhtml", "application/xhtml+xml", "nav"), ("css", "style.css", "text/css", "")]
        for iid, fname, doc in docs:
            zf.writestr("OEBPS/" + fname, doc, compress_type=zipfile.ZIP_DEFLATED)
            items.append((iid, fname, "application/xhtml+xml", ""))
        zf.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/style.css", css(), compress_type=zipfile.ZIP_DEFLATED)
        for i, (name, data) in enumerate(fonts.items()):
            zf.writestr("OEBPS/fonts/" + name, data, compress_type=zipfile.ZIP_DEFLATED)
            items.append((f"font{i}", "fonts/" + name, "font/ttf", ""))
        zf.writestr("OEBPS/package.opf", package_opf(items, [iid for iid, _, _ in docs], modified),
                    compress_type=zipfile.ZIP_DEFLATED)
    size = out_path.stat().st_size
    print(f"wrote {out_path.name}: {size:,} bytes; {len(docs)} documents — {len(main_chapters)} chapters in "
          f"{len(seen_parts) - 1} parts, the supplement, {len(groups)} apparatus sections; {epub_marks} note markers "
          f"(reader {reader_marks}), {n_notes} pop-up notes ({note_range})")
    print("fonts: " + "; ".join(font_report))
    if dropped_stale:
        print(f"note: the reader's edition note still says “{STALE}” — every chapter is present, so the EPUB "
              f"leaves that sentence out")
    if "--no-check" not in sys.argv:
        r = subprocess.run(["epubcheck", str(out_path)], capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().splitlines()
        print("\n".join(tail[-6:]))
        m = re.search(r"(\d+) fatal.*?(\d+) error.*?(\d+) warning", " ".join(tail), re.S | re.I)
        if r.returncode != 0 or not m or any(int(x) for x in m.groups()):
            raise SystemExit("build_epub: epubcheck did not pass clean")
        print("epubcheck: zero errors, zero warnings")


if __name__ == "__main__":
    main()
