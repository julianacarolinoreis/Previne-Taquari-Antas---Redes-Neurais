#!/usr/bin/env python3
"""Add the PREVINE, UFRGS and LAGAM signature to the prepared Pages artifact.

Apply after copying the public files. Generated research pages receive the same
signature on every deploy, without rewriting their source or embedded datasets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path

VERSION = "20261008-top"
MARKER = 'data-previne-institutions="v1"'
LOGOS = (
    ("previne", "PREVINE Taquari-Antas", 1000, 1000),
    ("ufrgs", "UFRGS — Universidade Federal do Rio Grande do Sul", 279, 158),
    ("lagam", "LAGAM — Laboratório de Geoprocessamento e Análise Ambiental", 2000, 2000),
)


class PageStructure(HTMLParser):
    """Find real HTML boundaries, ignoring HTML-looking text inside scripts."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.offsets = [0]
        self.offsets.extend(m.end() for m in re.finditer(r"\n", source))
        self.head_end = None
        self.head_close_end = None
        self.head_start_end = None
        self.html_start_end = None
        self.body_end = None
        self.body_attributes_end = None
        self.has_body = False
        self.redirect = False
        self.fixed_map = False
        self.mobile_bottom_panel = False
        self.in_style = False
        self.feed(source)

    def source_offset(self) -> int:
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "body":
            self.has_body = True
            self.body_attributes_end = self.source_offset() + len(self.get_starttag_text()) - 1
        elif tag == "head":
            self.head_start_end = self.source_offset() + len(self.get_starttag_text())
        elif tag == "html":
            self.html_start_end = self.source_offset() + len(self.get_starttag_text())
        elif tag == "style":
            self.in_style = True
        elif tag == "meta" and attributes.get("http-equiv", "").lower() == "refresh":
            self.redirect = True

    def handle_endtag(self, tag):
        if tag == "head":
            self.head_end = self.source_offset()
            self.head_close_end = self.source_offset() + len("</head>")
        elif tag == "body":
            self.body_end = self.source_offset()
        elif tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style and re.search(r"#map\s*\{[^}]*\bposition\s*:\s*fixed\b", data, re.I):
            self.fixed_map = True
        if self.in_style and re.search(r"\.card\s*\{\s*top\s*:\s*auto\s*;[^}]*\bbottom\s*:", data, re.I):
            self.mobile_bottom_panel = True


def brand_page(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    if "rascunhos" in relative.parts or "raw" in relative.parts:
        return "excluded"
    source = path.read_bytes().decode("utf-8")
    if MARKER in source:
        return "already_present"
    page = PageStructure(source)
    if page.redirect:
        return "redirect"
    # HTML permits omitted head/body tags; some generated reports use them.
    # Keep their source intact and let the browser infer the same structure.
    if page.cdata_elem is not None:
        raise ValueError(f"Unclosed script/style: {relative.as_posix()}")
    head_position = page.head_end
    if head_position is None:
        head_position = page.head_start_end or page.html_start_end or 0
    body_position = (page.body_attributes_end + 1 if page.has_body
                     else page.head_close_end)
    if body_position is None:
        raise ValueError(f"Cannot locate start of page content: {relative.as_posix()}")
    prefix = Path(os.path.relpath(root, path.parent)).as_posix()
    prefix = "" if prefix == "." else prefix + "/"
    newline = "\r\n" if "\r\n" in source else "\n"
    style = f'<link rel="stylesheet" href="{prefix}assets/css/institutional_logos.css?v={VERSION}" data-previne-institutions-style="v1">{newline}'
    classes = "previne-institutions" + (" previne-institutions--map" if page.fixed_map else "")
    blocks = [f'{newline}<!-- PREVINE: institutional signature -->',
              f'<div id="previne-institutions" class="{classes}" {MARKER} role="group" aria-label="Identidade institucional: PREVINE, UFRGS e LAGAM">',
              '  <div class="previne-institutions__logos">']
    for name, label, width, height in LOGOS:
        blocks.append(f'    <span class="previne-institutions__frame previne-institutions__frame--{name}"><img src="{prefix}assets/logos/{name}.png?v={VERSION}" alt="{escape(label, quote=True)}" width="{width}" height="{height}" decoding="async"></span>')
    blocks.extend(['  </div>', '</div>', '<!-- /PREVINE: institutional signature -->', ''])
    signature = newline.join(blocks)
    additions = [(head_position, style), (body_position, signature)]
    if page.fixed_map and page.body_attributes_end is not None:
        attributes = ' data-previne-map-signature="v1"'
        if page.mobile_bottom_panel:
            attributes += ' data-previne-bottom-panel="v1"'
        additions.append((page.body_attributes_end, attributes))
    for position, addition in sorted(additions, reverse=True):
        source = source[:position] + addition + source[position:]
    path.write_bytes(source.encode("utf-8"))
    return "added_map" if page.fixed_map else "added"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.site_dir.resolve()
    required = [root / "assets/css/institutional_logos.css"]
    required.extend(root / f"assets/logos/{name}.png" for name, *_ in LOGOS)
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    report: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.html")):
        result = brand_page(path, root)
        report.setdefault(result, []).append(path.relative_to(root).as_posix())
    if not report.get("added") and not report.get("added_map") and not report.get("already_present"):
        raise ValueError("No public HTML pages found")
    print(json.dumps({"counts": {k: len(v) for k, v in report.items()}, "pages": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
