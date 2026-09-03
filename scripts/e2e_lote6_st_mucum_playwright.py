"""E2E lote 6: paridade Muçum mesa, pontes cenário, live-status Muçum."""

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
        page.wait_for_selector("#contingencySelect", timeout=8000)
        combo = page.locator('#contingencySelect option[value="combo"]')
        results["mucum_mesa"] = {
            "contingency": combo.count() > 0,
            "exp_v2": "2070" in page.locator("#exp-pop").inner_text() or page.locator("#exp-method-note").inner_text(),
        }
        page.screenshot(path=str(ARTIFACTS / "mesa_mucum_contingency.png"), full_page=False)

        page.goto(BASE + "/pesquisas/mucum-rota-fuga-ruas-cenario.html", wait_until="networkidle")
        page.wait_for_timeout(1500)
        content = page.content()
        results["mucum_cenario_bridges"] = {"bridgeLayer": "MUC_PONTES_UNKNOWN" in content}
        page.screenshot(path=str(ARTIFACTS / "mucum_cenario_bridges.png"), full_page=False)

        page.goto(BASE + "/mucum_previsao_inundacao.html", wait_until="networkidle")
        results["mucum_previsao"] = {"liveStatusNote": page.locator("#live-status-note").count() > 0}
        page.screenshot(path=str(ARTIFACTS / "mucum_previsao_live_status.png"), full_page=False)

        browser.close()

    assert results["mucum_mesa"]["contingency"], results
    assert results["mucum_cenario_bridges"]["bridgeLayer"], results
    assert results["mucum_previsao"]["liveStatusNote"], results

    (ARTIFACTS / "lote6_e2e.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("LOTE6_E2E_OK")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
