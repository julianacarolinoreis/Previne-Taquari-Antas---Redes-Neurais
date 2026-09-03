"""E2E lote 5: redirect rota, datum, abrigo ST."""

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

        page.goto(BASE + "/pesquisas/santa-tereza-rota-fuga.html", wait_until="networkidle")
        results["redirect"] = {"url": page.url, "ok": "rota-fuga-ruas" in page.url}

        page.goto(BASE + "/pesquisas/datum-cadeia.html", wait_until="networkidle")
        page.wait_for_selector("#estacao-rows tr td", timeout=8000)
        body = page.locator("#estacao-rows").inner_text()
        results["datum"] = {"stations": "86472600" in body and "86510000" in body}
        page.screenshot(path=str(ARTIFACTS / "datum_cadeia_page.png"), full_page=False)

        page.goto(BASE + "/pesquisas/estudo-caso-resposta-santa-tereza.html", wait_until="networkidle")
        results["st_abrigo"] = {"mount": page.locator("#abrigo-capacidade-mount").count() > 0}
        page.screenshot(path=str(ARTIFACTS / "mesa_st_abrigo_form.png"), full_page=False)

        browser.close()

    assert results["redirect"]["ok"], results
    assert results["datum"]["stations"], results
    assert results["st_abrigo"]["mount"], results

    (ARTIFACTS / "lote5_e2e.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("LOTE5_E2E_OK")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
