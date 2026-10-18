"""Blog translations: mark the prose in docs/blog/index.html and check translations.

    python -m scripts.blog_i18n mark    # add data-i18n keys to new prose, rewrite assets/i18n/en.json
    python -m scripts.blog_i18n check [hi es ...]   # every translation has every key, same markup and code

The page loads assets/i18n/<lang>.json and swaps each keyed element's innerHTML.
Code, Cypher, terminals and diagrams are never keyed: they stay as written.
Strings built by the page script go through tr("...") / tf("... {x} ...", {x}) and
are extracted from the script into the "dyn" table.
"""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

BLOG = Path(__file__).resolve().parent.parent / "docs" / "blog"
PAGE = BLOG / "index.html"
I18N = BLOG / "assets" / "i18n"
LANGS = ("hi", "es", "fr", "he")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SKIP_INSIDE = {"script", "style", "svg", "pre", "code"}
BLOCK = {"h1", "h2", "h3", "h4", "h5", "p", "li", "blockquote", "figcaption", "th", "template"}


class Node:
    def __init__(self, tag: str, attrs: dict[str, str], start: int, inner: int, parent: Node | None):
        self.tag, self.attrs, self.start, self.inner, self.parent = tag, attrs, start, inner, parent
        self.end = inner
        self.cls = set((attrs.get("class") or "").split())

    def up(self):
        n = self.parent
        while n:
            yield n
            n = n.parent


class Tree(HTMLParser):
    def __init__(self, text: str):
        super().__init__(convert_charrefs=False)
        self.text = text
        self.nodes: list[Node] = []
        self.stack: list[Node] = []
        self.lines = [0]
        for m in re.finditer("\n", text):
            self.lines.append(m.end())
        self.feed(text)

    def pos(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        start = self.pos()
        raw = self.get_starttag_text() or ""
        node = Node(tag, {k: v or "" for k, v in attrs}, start, start + len(raw), self.stack[-1] if self.stack else None)
        self.nodes.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        start = self.pos()
        raw = self.get_starttag_text() or ""
        self.nodes.append(Node(tag, {k: v or "" for k, v in attrs}, start, start + len(raw), self.stack[-1] if self.stack else None))

    def handle_endtag(self, tag):
        while self.stack:
            n = self.stack.pop()
            if n.tag == tag:
                n.end = self.pos()
                return


def wanted(n: Node) -> bool:
    ups = list(n.up())
    if any(u.tag in SKIP_INSIDE or "term" in u.cls for u in ups) or n.tag in SKIP_INSIDE:
        return False
    if not any(u.tag == "body" for u in ups) or n.attrs.get("id") in {"dminfo", "copybtn"}:
        return False
    p = n.parent
    pc = p.cls if p else set()
    return (n.tag in BLOCK
            or bool(n.cls & {"crumb", "kicker", "dek", "eyebrow", "tag-live"})
            or (n.tag == "div" and "n" in n.cls and "lesson" in pc)
            or (n.tag == "span" and "tile" in pc)
            or (n.tag == "a" and bool(pc & {"btns", "toc"}))
            or (n.tag == "b" and (bool(pc & {"dh", "toc"}) or (n.attrs.get("id") is None and p is not None and p.tag == "span" and "play" in (p.parent.cls if p.parent else set()))))
            or (n.tag == "span" and "m" in n.cls and "dh" in pc)
            or (n.tag == "button" and bool(pc & {"seg2", "mbtns"}))
            or n.attrs.get("id") == "vidnote"
            or (n.tag == "span" and p is not None and "byline" in pc and "avs" not in n.cls)
            or (n.tag == "span" and p is not None and p.tag == "footer" and "<a" not in TEXT[n.inner:n.end]))


TEXT = ""


def letters(html: str) -> bool:
    return bool(re.search(r"[A-Za-z]", re.sub(r"<[^>]+>", "", html)))


def dyn_strings(text: str) -> list[str]:
    script = text[text.rfind("<script>"):]
    out: list[str] = []
    for m in re.finditer(r'\b(?:tr|tf|T)\("((?:[^"\\]|\\.)*)"', script):
        s = json.loads('"' + m.group(1) + '"')
        if s not in out:
            out.append(s)
    return out


def mark() -> None:
    global TEXT
    text = PAGE.read_text()
    TEXT = text
    tree = Tree(text)
    used = [int(m.group(1)) for m in re.finditer(r'data-i18n(?:-alt)?="[ka](\d+)"', text)]
    nxt = max(used, default=0) + 1
    chosen: list[Node] = []
    for n in tree.nodes:
        if "data-i18n" in n.attrs or (wanted(n) and letters(text[n.inner:n.end]) and not any(c in chosen for c in n.up())
                                      and not any("data-i18n" in u.attrs for u in n.up())):
            chosen.append(n)
    inserts: list[tuple[int, str]] = []
    for n in chosen:
        if "data-i18n" not in n.attrs:
            n.attrs["data-i18n"] = f"k{nxt}"
            inserts.append((n.start + 1 + len(n.tag), f' data-i18n="k{nxt}"'))
            nxt += 1
    alts: list[Node] = []
    for n in tree.nodes:
        if n.tag == "img" and n.attrs.get("alt") and any(u.tag == "article" for u in n.up()):
            alts.append(n)
            if "data-i18n-alt" not in n.attrs:
                n.attrs["data-i18n-alt"] = f"a{nxt}"
                inserts.append((n.start + 4, f' data-i18n-alt="a{nxt}"'))
                nxt += 1
    for at, s in sorted(inserts, reverse=True):
        text = text[:at] + s + text[at:]
    PAGE.write_text(text)
    tree = Tree(text)  # re-read so the extracted HTML has the final offsets
    html = {n.attrs["data-i18n"]: text[n.inner:n.end].strip() for n in tree.nodes if "data-i18n" in n.attrs}
    attr = {n.attrs["data-i18n-alt"]: n.attrs["alt"] for n in tree.nodes if "data-i18n-alt" in n.attrs}
    found = re.search(r"<title>(.*?)</title>", text)
    title = found.group(1) if found else ""
    desc = re.search(r'<meta name="description" content="([^"]*)"', text)
    meta = {"title": title, "description": desc.group(1) if desc else ""}
    I18N.mkdir(parents=True, exist_ok=True)
    en = {"lang": "en", "meta": meta, "html": html, "alt": attr, "dyn": {s: s for s in dyn_strings(text)}}
    (I18N / "en.json").write_text(json.dumps(en, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(html)} elements, {len(attr)} alt texts, {len(en['dyn'])} script strings; {len(inserts)} new keys")


def shape(s: str) -> tuple[list[str], list[str], list[str]]:
    tags = sorted(re.findall(r"</?([a-z0-9]+)", s))
    code = sorted(re.findall(r"<code>(.*?)</code>", s))
    holes = sorted(re.findall(r"\{[a-z]+\}", s))
    return tags, code, holes


def check(langs: tuple[str, ...] = LANGS) -> int:
    en = json.loads((I18N / "en.json").read_text())
    bad = 0
    for lang in langs:
        p = I18N / f"{lang}.json"
        if not p.exists():
            print(f"{lang}: missing")
            bad += 1
            continue
        t = json.loads(p.read_text())
        for part in ("html", "alt", "dyn"):
            for k, v in en[part].items():
                got = t.get(part, {}).get(k)
                if not got:
                    print(f"{lang} {part} {k[:50]!r}: missing")
                    bad += 1
                elif part != "alt" and shape(got) != shape(v):
                    print(f"{lang} {part} {k[:50]!r}: markup, code or placeholders differ")
                    bad += 1
                elif v.count("|") != got.count("|"):
                    print(f"{lang} {part} {k[:50]!r}: slide separators differ")
                    bad += 1
        for k in ("title", "description"):
            if not t.get("meta", {}).get(k):
                print(f"{lang} meta {k}: missing")
                bad += 1
    print("ok" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "mark":
        mark()
    else:
        sys.exit(check(tuple(sys.argv[2:]) or LANGS))
