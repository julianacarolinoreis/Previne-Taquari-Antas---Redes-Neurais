"""E2E: modo facilitador + bloco HAND + formulário abrigo."""

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
        page.locator("[data-facilitador-toggle]").click()
        hidden = page.locator("body.mesa-facilitador .facil-hide").first
        hidden.wait_for(state="hidden", timeout=5000)
        page.screenshot(path=str(ARTIFACTS / "mesa_st_facilitador_on.png"), full_page=False)
        results["st_facilitador"] = {"body_class": page.evaluate("() => document.body.classList.contains('mesa-facilitador')")}

        page.goto(BASE + "/pesquisas/briefing-gestores.html", wait_until="networkidle")
        page.locator("#abrigo-cap-form input[name=abrigo]").fill("Ginásio ST teste")
        page.locator("#abrigo-cap-form button[type=submit]").click()
        has_row = page.locator(".abrigo-row").count() > 0
        results["abrigo_form"] = {"row_saved": has_row}
        page.screenshot(path=str(ARTIFACTS / "briefing_abrigo_form.png"), full_page=False)

        page.goto(BASE + "/santa_tereza_previsao_inundacao.html", wait_until="networkidle")
        block = page.locator(".hand-vs-hidro-block").count()
        results["hand_block"] = {"visible": block > 0}
        page.screenshot(path=str(ARTIFACTS / "mapa_st_hand_block.png"), full_page=False)

        page.goto(BASE + "/pesquisas/santa-tereza-rota-fuga-ruas.html", wait_until="networkidle")
        page.wait_for_timeout(1500)
        bridges = page.locator(".leaflet-interactive").count()
        results["st_rota_bridges"] = {"markers": bridges > 0}
        page.screenshot(path=str(ARTIFACTS / "st_rota_pontes_unknown.png"), full_page=False)

        browser.close()

    assert results["st_facilitador"]["body_class"]
    assert results["abrigo_form"]["row_saved"]
    assert results["hand_block"]["visible"]
    assert results["st_rota_bridges"]["markers"]

    (ARTIFACTS / "pendencias_multiperspectiva_e2e.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print("PENDENCIAS_MULTIPERSPECTIVA_E2E_OK")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
