"""E2E lote 8: mesa Muçum v1/v2 + mensagem, overlay rotas."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ARTIFACTS = Path("/opt/cursor/artifacts")
BASE = "http://127.0.0.1:8765"


def main() -> None:
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        page.goto(BASE + "/pesquisas/estudo-caso-resposta-mucum.html", wait_until="networkidle")
        page.wait_for_function(
            "() => document.getElementById('exp-v2-pop')?.textContent.includes('2070')",
            timeout=10000,
        )
        page.wait_for_function(
            "() => document.getElementById('exp-v1-pop')?.textContent.includes('2117')",
            timeout=8000,
        )
        draft = page.locator("#messageDraft").inner_text()
        results["mucum_mesa"] = {
            "v1": page.locator("#exp-v1-pop").inner_text(),
            "v2": page.locator("#exp-v2-pop").inner_text(),
            "draft": "RASCUNHO" in draft,
        }
        page.locator("#exposure-compare").scroll_into_view_if_needed()
        page.screenshot(path=str(ARTIFACTS / "lote8_mucum_mesa_exp.png"), full_page=False)
        page.locator("#contingencySelect").select_option("combo")
        page.locator("#contingencyApply").click()
        page.wait_for_timeout(400)
        draft2 = page.locator("#messageDraft").inner_text()
        results["mucum_mesa"]["combo_draft"] = "combo" in draft2.lower() or "corredor" in draft2.lower()
        page.locator(".message-draft").scroll_into_view_if_needed()
        page.screenshot(path=str(ARTIFACTS / "lote8_mucum_message_draft.png"), full_page=False)

        page.goto(BASE + "/pesquisas/mucum-rota-fuga-ruas.html", wait_until="networkidle")
        page.wait_for_function(
            "() => document.querySelector('.leaflet-control-layers-overlays')?.textContent.includes('Exposição v2')",
            timeout=10000,
        )
        results["mucum_rota"] = {"overlay": True}
        page.locator(".leaflet-control-layers").hover()
        page.wait_for_timeout(400)
        page.screenshot(path=str(ARTIFACTS / "lote8_mucum_rota_overlay.png"), full_page=False)

        page.goto(BASE + "/pesquisas/santa-tereza-rota-fuga-ruas.html", wait_until="networkidle")
        page.wait_for_function(
            "() => document.querySelector('.leaflet-control-layers-overlays')?.textContent.includes('Exposição v2')",
            timeout=10000,
        )
        results["st_rota"] = {"overlay": True}
        page.locator(".leaflet-control-layers").hover()
        page.wait_for_timeout(400)
        page.screenshot(path=str(ARTIFACTS / "lote8_st_rota_overlay.png"), full_page=False)

        browser.close()

    assert "2117" in results["mucum_mesa"]["v1"], results
    assert "2070" in results["mucum_mesa"]["v2"], results
    assert results["mucum_mesa"]["draft"], results
    assert results["mucum_mesa"]["combo_draft"], results
    assert results["mucum_rota"]["overlay"], results
    assert results["st_rota"]["overlay"], results

    (ARTIFACTS / "lote8_e2e.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("LOTE8_E2E_OK")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
