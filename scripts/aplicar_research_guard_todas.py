#!/usr/bin/env python3
"""Injeta previne_research_guard.js em todas as HTML sem gestor_chrome."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP = {"rascunhos/site_projeto_v1.html"}  # noindex draft

BLOCKED = {
    "santa_tereza_rota_fuga.html",
    "santa_tereza_rota_fuga_cenario.html",
    "pesquisas/santa-tereza-painel-evacuacao.html",
    "pesquisas/mucum-painel-evacuacao.html",
    "pesquisas/santa-tereza-rota-fuga.html",
}

SNAPSHOT = {
    "pesquisas/sace-mucum-live-20260811.html",
    "pesquisas/sace-mucum-anchor-live.html",
    "pesquisas/sace-mucum-anchor-20260812.html",
}

EXTRA = {
    "encostas_movimentos_massa.html": "Sensoriamento remoto · confirmar via CPRM/DC",
    "index.html": "282 modelos RNA · na crise use centro-resposta e briefing",
    "pesquisas/santa-tereza-painel-evacuacao.html": "Use santa-tereza-rota-fuga-ruas.html ou modo-campo.html",
    "pesquisas/mucum-painel-evacuacao.html": "Use mucum-rota-fuga-ruas.html ou modo-campo.html",
    "pesquisas/santa-tereza-rota-fuga.html": "Redirecione para rota-fuga-ruas.html",
}


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def prefix_for(path: Path) -> str:
    depth = len(path.relative_to(ROOT).parts) - 1
    return "../" * depth if depth else ""


def mode_for(rel_path: str) -> str:
    if rel_path in SNAPSHOT:
        return "snapshot"
    if rel_path in BLOCKED:
        return "blocked"
    return "research"


def inject_guard(path: Path) -> bool:
    rel_path = rel(path)
    if rel_path in SKIP:
        return False
    text = path.read_text(encoding="utf-8")
    if "gestor_chrome.js" in text or "previne_research_guard.js" in text:
        return False
    mode = mode_for(rel_path)
    extra = EXTRA.get(rel_path, "")
    prefix = prefix_for(path)
    attrs = f'data-mode="{mode}"'
    if extra:
        attrs += f' data-extra="{extra}"'
    tag = f'<script src="{prefix}assets/js/previne_research_guard.js" {attrs}></script>'
    if re.search(r"<body[^>]*>", text, re.I):
        new_text = re.sub(r"(<body[^>]*>)", r"\1\n" + tag, text, count=1, flags=re.I)
    else:
        return False
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> None:
    html_files = sorted(ROOT.rglob("*.html"))
    changed = []
    skipped = []
    for p in html_files:
        r = rel(p)
        if r in SKIP:
            skipped.append(r)
            continue
        if inject_guard(p):
            changed.append(r)
    print(f"GUARD_APPLIED {len(changed)}")
    for c in changed:
        print(f"  + {c}")
    print(f"SKIPPED {len(skipped)}")


if __name__ == "__main__":
    main()
