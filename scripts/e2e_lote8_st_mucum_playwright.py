"""E2E lote 8: mesa Muçum v1/v2 + mensagem, overlay rotas."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ARTIFACTS = Path("/opt/cursor/artifacts")
BASE = "http://127.0.0.1:8765"


def soft_bypass_sw(page, url: str) -> None:
    page.goto(url, wait_until="networkidle")
    page.evaluate(
        """async () => {
          if (!navigator.serviceWorker) return;
          const regs = await navigator.serviceWorker.getRegistrations();
          for (const r of regs) await r.unregister();
          const keys = await caches.keys();
          await Promise.all(keys.map((k) => caches.delete(k)));
        }"""
    )
    page.reload(wait_until="networkidle")


def expand_layers(page) -> None:
    page.evaluate(
        """() => {
          const c = document.querySelector('.leaflet-control-layers');
          if (c) c.classList.add('leaflet-control-layers-expanded');
        }"""
    )


def main() -> None:
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        soft_bypass_sw(page, BASE + "/pesquisas/estudo-caso-resposta-mucum.html")
        page.wait_for_function(
            "() => { const t = document.getElementById('exp-v2-pop'); return t && t.textContent.indexOf('2.070') >= 0; }",
            timeout=15000,
        )
        page.wait_for_function(
            "() => { const t = document.getElementById('exp-v1-pop'); return t && t.textContent.indexOf('2.117') >= 0; }",
            timeout=10000,
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
        results["mucum_mesa"]["combo_draft"] = (
            "combo" in draft2.lower() or "corredor" in draft2.lower()
        )
        page.locator(".message-draft").scroll_into_view_if_needed()
        page.screenshot(path=str(ARTIFACTS / "lote8_mucum_message_draft.png"), full_page=False)

        soft_bypass_sw(page, BASE + "/pesquisas/mucum-rota-fuga-ruas.html")
        page.wait_for_function(
            "() => { const t = document.querySelector('.leaflet-control-layers-overlays'); return t && t.textContent.indexOf('Exposição v2') >= 0; }",
            timeout=15000,
        )
        results["mucum_rota"] = {"overlay": True}
        expand_layers(page)
        page.wait_for_timeout(400)
        page.screenshot(path=str(ARTIFACTS / "lote8_mucum_rota_overlay.png"), full_page=False)

        soft_bypass_sw(page, BASE + "/pesquisas/santa-tereza-rota-fuga-ruas.html")
        page.wait_for_function(
            "() => { const t = document.querySelector('.leaflet-control-layers-overlays'); return t && t.textContent.indexOf('Exposição v2') >= 0; }",
            timeout=15000,
        )
        results["st_rota"] = {"overlay": True}
        expand_layers(page)
        page.wait_for_timeout(400)
        page.screenshot(path=str(ARTIFACTS / "lote8_st_rota_overlay.png"), full_page=False)

        browser.close()

    assert "2.117" in results["mucum_mesa"]["v1"], results
    assert "2.070" in results["mucum_mesa"]["v2"], results
    assert results["mucum_mesa"]["draft"], results
    assert results["mucum_mesa"]["combo_draft"], results
    assert results["mucum_rota"]["overlay"], results
    assert results["st_rota"]["overlay"], results

    (ARTIFACTS / "lote8_e2e.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("LOTE8_E2E_OK")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
