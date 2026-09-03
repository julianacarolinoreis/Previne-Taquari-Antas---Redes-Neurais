"""E2E lote 7: overlay v2, mesa ST exposição, rota campo ST."""

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

        page.goto(BASE + "/pesquisas/estudo-caso-resposta-santa-tereza.html", wait_until="networkidle")
        page.wait_for_selector("#exp-v2-pop", timeout=8000)
        page.wait_for_function(
            "() => { const t = document.getElementById('exp-v2-pop'); return t && t.textContent && t.textContent !== '—'; }",
            timeout=8000,
        )
        exp_v2 = page.locator("#exp-v2-pop").inner_text()
        results["st_mesa_exp"] = {"v2": exp_v2, "ok": "336" in exp_v2}
        page.screenshot(path=str(ARTIFACTS / "mesa_st_exposicao_v2.png"), full_page=False)

        page.goto(BASE + "/pesquisas/santa-tereza-rota-fuga-ruas.html", wait_until="networkidle")
        page.locator('summary:has-text("Registrar conferência local")').click()
        page.wait_for_selector("#fieldChecksBox", state="visible", timeout=8000)
        results["st_rota_field"] = {"checks": page.locator("#fieldChecksBox .field-check").count() == 4}
        page.wait_for_timeout(400)
        page.screenshot(path=str(ARTIFACTS / "st_rota_field_checks.png"), full_page=False)

        page.goto(BASE + "/mucum_previsao_inundacao.html", wait_until="networkidle")
        page.wait_for_function(
            "() => { const t = document.querySelector('.leaflet-control-layers-overlays'); return t && t.textContent.includes('Exposição v2'); }",
            timeout=10000,
        )
        has_overlay = page.evaluate(
            """() => !!(window.PREVINE_EXPOSICAO_OVERLAY && document.querySelector('.leaflet-control-layers'))"""
        )
        page.locator(".leaflet-control-layers").hover()
        page.wait_for_timeout(500)
        layers_text = page.locator(".leaflet-control-layers").inner_text()
        results["mucum_overlay"] = {
            "module": has_overlay,
            "label": "Exposição v2" in layers_text,
        }
        page.screenshot(path=str(ARTIFACTS / "mucum_previsao_exposicao_overlay.png"), full_page=False)

        page.goto(BASE + "/santa_tereza_previsao_inundacao.html", wait_until="networkidle")
        page.wait_for_function(
            "() => { const t = document.querySelector('.leaflet-control-layers-overlays'); return t && t.textContent.includes('Exposição v2'); }",
            timeout=10000,
        )
        page.locator(".leaflet-control-layers").hover()
        page.wait_for_timeout(500)
        st_layers = page.locator(".leaflet-control-layers").inner_text()
        results["st_overlay"] = {"label": "Exposição v2" in st_layers}
        page.screenshot(path=str(ARTIFACTS / "st_previsao_exposicao_overlay.png"), full_page=False)

        browser.close()

    assert results["st_mesa_exp"]["ok"], results
    assert results["st_rota_field"]["checks"], results
    assert results["mucum_overlay"]["label"], results
    assert results["st_overlay"]["label"], results

    (ARTIFACTS / "lote7_e2e.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("LOTE7_E2E_OK")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
