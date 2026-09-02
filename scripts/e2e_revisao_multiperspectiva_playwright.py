"""Revisão mobile (320) + desktop (1440) pós melhorias multiperspectiva."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ARTIFACTS = Path("/opt/cursor/artifacts")
ARTIFACTS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8765"

PAGES = [
    ("centro-resposta", "/pesquisas/centro-resposta.html", "#live-title"),
    ("modo-campo", "/pesquisas/modo-campo.html", "#field-check-title"),
    ("briefing-gestores", "/pesquisas/briefing-gestores.html", "h1"),
    ("revisao-multiperspectiva", "/pesquisas/revisao-multiperspectiva.html", "h1"),
    ("exposicao-cruzada", "/pesquisas/exposicao-cruzada.html", "h1"),
    ("painel-evac-bloqueado", "/pesquisas/santa-tereza-painel-evacuacao.html", ".hud h1"),
]


def check_page(page, path: str, selector: str, width: int, name: str) -> dict:
    page.set_viewport_size({"width": width, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + path, wait_until="networkidle")
    page.locator(selector).first.wait_for(timeout=15000)
    has_guard = page.locator(".previne-research-guard, .gestor-chrome-seal").count() > 0
    overflow = page.evaluate(
        "() => ({sw: document.documentElement.scrollWidth, vw: window.innerWidth})"
    )
    ok_overflow = overflow["sw"] <= overflow["vw"] + 2
    shot = ARTIFACTS / f"revisao_{name}_{width}px.png"
    page.screenshot(path=str(shot), full_page=False)
    return {
        "width": width,
        "guard_visible": has_guard,
        "overflow_ok": ok_overflow,
        "scroll_width": overflow["sw"],
        "errors": errors,
        "screenshot": str(shot),
    }


def main() -> None:
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for name, path, sel in PAGES:
            results[name] = {
                "mobile": check_page(page, path, sel, 320, name),
                "desktop": check_page(page, path, sel, 1440, name),
            }
        browser.close()

    for name, data in results.items():
        for mode in ("mobile", "desktop"):
            assert not data[mode]["errors"], f"{name}/{mode}: {data[mode]['errors']}"
            assert data[mode]["overflow_ok"], f"{name}/{mode} overflow"
        if name == "painel-evac-bloqueado":
            assert data["mobile"]["guard_visible"] or data["desktop"]["guard_visible"]

    (ARTIFACTS / "revisao_multiperspectiva_e2e.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("REVISAO_MULTIPERSPECTIVA_E2E_OK")
    print(json.dumps({k: {m: {"guard": v[m]["guard_visible"], "overflow": v[m]["overflow_ok"]} for m in v} for k, v in results.items()}, indent=2))


if __name__ == "__main__":
    main()
